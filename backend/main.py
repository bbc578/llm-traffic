"""
FastAPI backend for LLM-Traffic simulation — multi-intersection edition.

Architecture: SUMO runs in a dedicated subprocess (TraCI TCP socket is not
compatible with uvicorn's asyncio event loop in the same process).
A multiprocessing.Queue carries snapshots from the sim process to the API.
"""
import asyncio
import json
import logging
import multiprocessing as mp
import os
import sys
import time as _time
from contextlib import asynccontextmanager
from typing import List, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simulation process target
# ---------------------------------------------------------------------------
def _sim_process_fn(cfg: dict, state_queue: mp.Queue, stop_event: mp.Event):
    """Runs SUMO in its own process. Pushes snapshots to state_queue."""
    import os as _os
    _os.environ["SUMO_HOME"] = _os.environ.get("SUMO_HOME", "/usr/share/sumo")
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

    try:
        from simulation.sumo_engine import SumoEngine
        from algorithms.webster import WebsterController
        from algorithms.constraints import SignalConstraintEngine
        from algorithms.coordination import CoordinationEngine
        from llm.xiaomi_client import LLMClient
    except ImportError:
        from backend.simulation.sumo_engine import SumoEngine
        from backend.algorithms.webster import WebsterController
        from backend.algorithms.constraints import SignalConstraintEngine
        from backend.algorithms.coordination import CoordinationEngine
        from backend.llm.xiaomi_client import LLMClient

    engine = SumoEngine()
    webster = WebsterController()
    constraint_engine = SignalConstraintEngine()
    coordination = CoordinationEngine()
    strategy = cfg.get("strategy", "fixed")
    speed_factor = cfg.get("speed_factor", 5.0)
    duration = cfg.get("duration", 600)
    llm_interval = cfg.get("llm_interval", 30)
    step_delay = max(0.01, 0.1 / speed_factor)

    # LLM client (only instantiated if strategy == "llm")
    llm_client = None
    if strategy == "llm":
        llm_client = LLMClient()
        logger.info("LLM strategy enabled, interval=%ds", llm_interval)

    # Per-intersection timing cache (used by LLM and coordination)
    _timing_cache: Dict[str, Dict[int, int]] = {}

    try:
        config_file = cfg.get("config_file")
        engine.start(
            step_length=cfg.get("step_length", 1),
            config_file=config_file,
        )

        # Get discovered intersections
        _INTS = engine.intersections
        state_queue.put({
            "event": "started",
            "running": engine.is_running,
            "intersections": _INTS,
        })

        # Green wave offsets (auto-compute from network geometry)
        if cfg.get("green_wave"):
            try:
                import traci
                for i, iid in enumerate(_INTS):
                    traci.trafficlight.setPhaseOffset(iid, float(i * 15))
            except Exception:
                pass

        step_count = 0
        while not stop_event.is_set():
            if engine.simulation_time >= duration:
                break
            if not engine.step():
                break
            step_count += 1

            snapshot = engine.get_snapshot()
            snapshot["is_running"] = True
            snapshot["strategy"] = strategy

            # Strategy-based signal control
            t = snapshot["time"]
            control_interval = llm_interval if strategy == "llm" else 30

            if int(t) % control_interval == 0 and t > 0:
                try:
                    queues = engine.get_all_queue_lengths()
                    vehicle_counts = engine.get_all_vehicle_counts()

                    if strategy == "webster":
                        for iid in _INTS:
                            q = queues[iid]
                            ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                            ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                            timings = webster.compute_timing({"EW": ew, "NS": ns})
                            phase = 0 if timings[0] >= timings[1] else 2
                            engine.set_phase(iid, phase, duration=int(max(timings)))

                    elif strategy == "llm" and llm_client:
                        # 1) Batch LLM call for all intersections
                        all_states = {}
                        for iid in _INTS:
                            q = queues.get(iid, {})
                            vc = vehicle_counts.get(iid, {})
                            all_states[iid] = {
                                "vehicle_counts": vc,
                                "queue_lengths": q,
                                "avg_waiting_times": {d: 0 for d in q},
                                "total_vehicles": sum(vc.values()),
                                "time": t,
                                "current_phase": 0,
                            }
                        try:
                            batch_result = llm_client.get_batch_recommendation(all_states)
                            for iid in _INTS:
                                pd = batch_result.get(iid, {}).get("phase_durations", {0: 30, 1: 3, 2: 30, 3: 3})
                                _timing_cache[iid] = {int(k): int(v) for k, v in pd.items()}
                        except Exception as llm_err:
                            logger.warning("LLM batch call failed: %s", llm_err)
                            for iid in _INTS:
                                _timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}

                        # 2) Apply coordination adjustments
                        try:
                            adj = coordination.compute_adjustments(queues, {})
                            _timing_cache = coordination.apply_adjustments(_timing_cache, adj)
                            coord_reasons = {iid: a.get("reason", "") for iid, a in adj.items()}
                            snapshot["coordination"] = coord_reasons
                        except Exception as coord_err:
                            logger.warning("Coordination failed: %s", coord_err)

                        # 3) Validate with constraint engine and apply
                        for iid in _INTS:
                            timings = _timing_cache.get(iid, {0: 30, 1: 3, 2: 30, 3: 3})
                            green_phases = [timings.get(0, 30), timings.get(2, 30)]
                            cycle_len = sum(timings.values())
                            valid, violations, corrected = constraint_engine.validate(green_phases, cycle_len)
                            if not valid:
                                timings[0] = corrected[0] if len(corrected) > 0 else 30
                                timings[2] = corrected[1] if len(corrected) > 1 else 30
                            # Set dominant phase
                            phase = 0 if timings.get(0, 30) >= timings.get(2, 30) else 2
                            duration_val = max(timings.get(0, 30), timings.get(2, 30))
                            engine.set_phase(iid, phase, duration=duration_val)

                        snapshot["llm_decisions"] = {
                            iid: _timing_cache.get(iid, {})
                            for iid in _INTS
                        }

                except Exception as e:
                    logger.warning("Signal control error at t=%.0f: %s", t, e)

            # Push snapshot (drop if full)
            try:
                state_queue.put_nowait(snapshot)
            except Exception:
                pass

            _time.sleep(step_delay)

    except Exception as e:
        state_queue.put({"event": "error", "error": str(e)})
    finally:
        metrics = engine.metrics.summary()
        engine.stop()
        try:
            state_queue.put_nowait({
                "event": "ended",
                "is_running": False,
                "message": "Simulation ended",
                "final_metrics": metrics,
            })
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_sim_proc: mp.Process = None
_state_queue: mp.Queue = mp.Queue(maxsize=500)
_stop_event: mp.Event = mp.Event()

# Latest snapshot for REST API
_latest: Dict = {"is_running": False, "time": 0}
import threading as _thr
_latest_lock = _thr.Lock()

# WebSocket clients
ws_clients: List[WebSocket] = []

# Discovered intersections (updated when simulation starts)
_current_intersections: List[str] = []
_current_approaches: Dict[str, Dict[str, str]] = {}

# Sim config
sim_config = {
    "duration": 600,
    "step_length": 1,
    "speed_factor": 5.0,
    "strategy": "fixed",
    "llm_enabled": False,
    "llm_interval": 30,
    "green_wave": False,
    "config_file": None,  # None = use default (Cologne subnetwork)
}


# ---------------------------------------------------------------------------
# Async forwarder: reads from mp.Queue, broadcasts to WS clients
# ---------------------------------------------------------------------------
async def _forward_loop():
    global _current_intersections
    while True:
        try:
            try:
                msg = _state_queue.get_nowait()
            except Exception:
                msg = None

            if msg:
                # Update intersection list from started event
                if "intersections" in msg:
                    _current_intersections = msg["intersections"]

                with _latest_lock:
                    _latest.update(msg)

                # Broadcast to WS clients
                disconnected = []
                for ws in ws_clients:
                    try:
                        await ws.send_json(msg)
                    except Exception:
                        disconnected.append(ws)
                for ws in disconnected:
                    ws_clients.remove(ws)
            else:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            break


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
_fwd_task: asyncio.Task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _fwd_task
    logger.info("LLM-Traffic backend starting (v2, multiprocessing).")
    _fwd_task = asyncio.create_task(_forward_loop())
    yield
    logger.info("Shutting down.")
    _stop_event.set()
    if _sim_proc and _sim_proc.is_alive():
        _sim_proc.join(timeout=5)
    _fwd_task.cancel()
    try:
        await _fwd_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="LLM-Traffic Backend",
    description="Multi-intersection traffic simulation with LLM-based signal optimization",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class SimulationRequest(BaseModel):
    duration: int = 600
    step_length: int = 1
    speed_factor: float = 5.0
    strategy: str = "fixed"
    llm_enabled: bool = False
    llm_interval: int = 30
    green_wave: bool = False
    config_file: str = None  # Path to .sumocfg, None = default


class ExperimentRequest(BaseModel):
    strategies: List[str] = ["fixed", "webster", "random"]
    steps: int = 300
    config_file: str = None


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------
@app.post("/api/simulation/start")
async def start_simulation(req: SimulationRequest = None):
    global _sim_proc

    if _sim_proc and _sim_proc.is_alive():
        return {"status": "error", "message": "Simulation already running. Stop it first."}

    if req:
        sim_config.update(req.model_dump())

    # Drain queue
    while not _state_queue.empty():
        try:
            _state_queue.get_nowait()
        except Exception:
            break

    _stop_event.clear()

    with _latest_lock:
        _latest.clear()
        _latest.update({"is_running": False, "time": 0})

    _sim_proc = mp.Process(
        target=_sim_process_fn,
        args=(dict(sim_config), _state_queue, _stop_event),
        daemon=True,
    )
    _sim_proc.start()
    return {"status": "started", "config": sim_config}


@app.post("/api/simulation/stop")
async def stop_simulation():
    global _sim_proc
    if _sim_proc and _sim_proc.is_alive():
        _stop_event.set()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sim_proc.join, 5)
        return {"status": "stopped"}
    return {"status": "no_simulation_running"}


@app.get("/api/simulation/state")
async def get_state():
    with _latest_lock:
        return dict(_latest)


@app.get("/api/simulation/metrics")
async def get_metrics():
    with _latest_lock:
        return _latest.get("metrics", _latest.get("final_metrics", {}))


@app.get("/api/intersections")
async def get_intersections():
    """Return discovered intersections from the current (or last) simulation."""
    if _current_intersections:
        return {"intersections": _current_intersections}
    # If no simulation has run yet, try to discover from the default config
    return {"intersections": [], "message": "Start a simulation to discover intersections."}


@app.post("/api/experiment/compare")
async def run_experiment(req: ExperimentRequest = None):
    """Run comparative experiments sequentially in a subprocess."""
    if not req:
        req = ExperimentRequest()

    def _run_one(strategy: str) -> dict:
        import os as _os
        _os.environ["SUMO_HOME"] = _os.environ.get("SUMO_HOME", "/usr/share/sumo")
        sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        try:
            from simulation.sumo_engine import SumoEngine
            from algorithms.webster import WebsterController
            from algorithms.baseline import FixedTimeController, RandomController
            from algorithms.constraints import SignalConstraintEngine
            from algorithms.coordination import CoordinationEngine
            from llm.xiaomi_client import LLMClient
        except ImportError:
            from backend.simulation.sumo_engine import SumoEngine
            from backend.algorithms.webster import WebsterController
            from backend.algorithms.baseline import FixedTimeController, RandomController
            from backend.algorithms.constraints import SignalConstraintEngine
            from backend.algorithms.coordination import CoordinationEngine
            from backend.llm.xiaomi_client import LLMClient

        ctrl_map = {
            "fixed": FixedTimeController(),
            "random": RandomController(seed=42),
            "webster": WebsterController(),
        }
        controller = ctrl_map.get(strategy)
        is_llm = strategy == "llm"

        if not controller and not is_llm:
            return {"error": f"Unknown strategy: {strategy}"}

        engine = SumoEngine()
        constraint_engine = SignalConstraintEngine()
        coordination = CoordinationEngine()
        llm_client = LLMClient() if is_llm else None
        timing_cache: Dict[str, Dict[int, int]] = {}

        try:
            engine.start(config_file=req.config_file)
            _INTS = engine.intersections
            for step in range(req.steps):
                if not engine.step():
                    break
                if step > 0 and step % 30 == 0:
                    queues = engine.get_all_queue_lengths()

                    if is_llm and llm_client:
                        vehicle_counts = engine.get_all_vehicle_counts()
                        all_states = {}
                        for iid in _INTS:
                            q = queues.get(iid, {})
                            vc = vehicle_counts.get(iid, {})
                            all_states[iid] = {
                                "vehicle_counts": vc,
                                "queue_lengths": q,
                                "avg_waiting_times": {d: 0 for d in q},
                                "total_vehicles": sum(vc.values()),
                                "time": step,
                                "current_phase": 0,
                            }
                        try:
                            batch_result = llm_client.get_batch_recommendation(all_states)
                            for iid in _INTS:
                                pd = batch_result.get(iid, {}).get("phase_durations", {0: 30, 1: 3, 2: 30, 3: 3})
                                timing_cache[iid] = {int(k): int(v) for k, v in pd.items()}
                        except Exception:
                            for iid in _INTS:
                                timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}

                        adj = coordination.compute_adjustments(queues, {})
                        timing_cache = coordination.apply_adjustments(timing_cache, adj)

                        for iid in _INTS:
                            timings = timing_cache.get(iid, {0: 30, 1: 3, 2: 30, 3: 3})
                            green_phases = [timings.get(0, 30), timings.get(2, 30)]
                            cycle_len = sum(timings.values())
                            _, _, corrected = constraint_engine.validate(green_phases, cycle_len)
                            if corrected:
                                timings[0] = corrected[0]
                                timings[2] = corrected[1] if len(corrected) > 1 else 30
                            phase = 0 if timings.get(0, 30) >= timings.get(2, 30) else 2
                            engine.set_phase(iid, phase, duration=max(timings.get(0, 30), timings.get(2, 30)))
                    else:
                        for iid in _INTS:
                            q = queues[iid]
                            ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                            ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                            timings = controller.compute_timing({"EW": ew, "NS": ns})
                            phase = 0 if timings[0] >= timings[1] else 2
                            engine.set_phase(iid, phase, duration=int(max(timings)))

            return engine.metrics.summary()
        except Exception as e:
            return {"error": str(e)}
        finally:
            engine.stop()

    loop = asyncio.get_event_loop()
    results = {}
    for s in req.strategies:
        results[s] = await loop.run_in_executor(None, _run_one, s)

    return {"status": "completed", "steps_per_strategy": req.steps, "results": results}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "simulation_running": _sim_proc.is_alive() if _sim_proc else False,
        "version": "2.0.0",
    }


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws/simulation")
async def websocket_simulation(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    logger.info(f"WS client connected. Total: {len(ws_clients)}")
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)


if __name__ == "__main__":
    import uvicorn
    mp.set_start_method("spawn")
    uvicorn.run(app, host="0.0.0.0", port=8000)
