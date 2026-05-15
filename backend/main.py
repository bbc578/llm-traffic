"""
FastAPI Backend for LLM-Traffic Simulation — Multi-Intersection Edition

Architecture Overview:
======================
This module implements the main API server for the LLM-Traffic system.
It uses a multi-process architecture where:

1. **Main Process**: Runs FastAPI server (REST + WebSocket)
2. **Child Process**: Runs SUMO simulation + LLM decisions

Why Multi-Process?
- TraCI (SUMO's Python interface) uses TCP sockets that are NOT thread-safe
- SUMO's event loop conflicts with uvicorn's async event loop
- Process isolation prevents SUMO crashes from taking down the API server

Communication:
- mp.Queue: Child → Main (push simulation snapshots)
- mp.Event: Main → Child (signal termination)
- threading.Lock: Protect shared state in main process

Data Flow:
==========
Simulation Process:
    SUMO step → Collect metrics → LLM decision → Validate → Execute → Push snapshot

Main Process:
    Receive snapshot → Update state → Broadcast to WebSocket clients

API Endpoints:
==============
- POST /api/simulation/start: Start simulation with given strategy
- POST /api/simulation/stop: Stop running simulation
- GET /api/simulation/state: Get current simulation state
- GET /api/simulation/metrics: Get aggregated metrics
- GET /api/intersections: Get discovered intersections
- POST /api/experiment/compare: Run comparative experiments

Strategies:
===========
- fixed: Static 30s+3s+30s+3s cycle
- random: Randomized green durations [10, 60]s
- webster: Queue-based adaptive timing (classical formula)
- llm: LLM recommendations + coordination + constraints

Author: Yihao Tang
Date: 2024
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

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Simulation Process Target
# ============================================================================
def _sim_process_fn(cfg: dict, state_queue: mp.Queue, stop_event: mp.Event):
    """Runs SUMO simulation in its own process.
    
    This function is the entry point for the simulation subprocess.
    It handles:
    1. SUMO initialization and network discovery
    2. Signal control based on selected strategy
    3. Metrics collection at each simulation step
    4. Pushing snapshots to the main process via state_queue
    
    Args:
        cfg: Simulation configuration dictionary containing:
            - strategy: Control strategy ('fixed', 'random', 'webster', 'llm')
            - speed_factor: Simulation speed multiplier
            - duration: Total simulation steps
            - llm_interval: Seconds between LLM calls
            - config_file: Path to .sumocfg file
        state_queue: multiprocessing.Queue for pushing snapshots to main process
        stop_event: multiprocessing.Event to signal termination
    
    Why separate process?
    - TraCI uses TCP sockets, not thread-safe
    - SUMO's event loop conflicts with uvicorn's async loop
    - Process isolation prevents crashes from taking down API server
    """
    # Set SUMO_HOME environment variable
    import os as _os
    _os.environ["SUMO_HOME"] = _os.environ.get("SUMO_HOME", "/usr/share/sumo")
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

    # Import modules (handle both relative and absolute imports)
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

    # Initialize components
    engine = SumoEngine()                    # SUMO simulation engine
    webster = WebsterController()            # Webster's formula controller
    constraint_engine = SignalConstraintEngine()  # Safety constraint validator
    coordination = CoordinationEngine()      # Multi-intersection coordinator
    
    # Extract configuration
    strategy = cfg.get("strategy", "fixed")
    speed_factor = cfg.get("speed_factor", 5.0)
    duration = cfg.get("duration", 600)
    llm_interval = cfg.get("llm_interval", 30)
    step_delay = max(0.01, 0.1 / speed_factor)  # Delay between steps

    # LLM client (only instantiated if strategy == "llm")
    # This saves memory and API calls when LLM is not needed
    llm_client = None
    if strategy == "llm":
        llm_client = LLMClient()
        logger.info("LLM strategy enabled, interval=%ds", llm_interval)

    # Per-intersection timing cache
    # Stores LLM recommendations and coordination adjustments
    # Key: intersection_id, Value: {phase: duration}
    _timing_cache: Dict[str, Dict[int, int]] = {}

    try:
        # Start SUMO simulation
        config_file = cfg.get("config_file")
        engine.start(
            step_length=cfg.get("step_length", 1),
            config_file=config_file,
        )

        # Get discovered intersections from SUMO
        # These are automatically found by scanning the network
        _INTS = engine.intersections
        state_queue.put({
            "event": "started",
            "running": engine.is_running,
            "intersections": _INTS,
        })

        # Green wave offsets (auto-compute from network geometry)
        # This creates a "green wave" effect for platoons of vehicles
        if cfg.get("green_wave"):
            try:
                import traci
                for i, iid in enumerate(_INTS):
                    traci.trafficlight.setPhaseOffset(iid, float(i * 15))
            except Exception:
                pass

        # Main simulation loop
        step_count = 0
        while not stop_event.is_set():
            # Check if simulation time exceeded
            if engine.simulation_time >= duration:
                break
            
            # Advance one simulation step
            if not engine.step():
                break
            step_count += 1

            # Collect snapshot for visualization
            snapshot = engine.get_snapshot()
            snapshot["is_running"] = True
            snapshot["strategy"] = strategy

            # Strategy-based signal control
            # Control interval depends on strategy:
            # - LLM: Uses configured llm_interval (default 30s)
            # - Others: Fixed 30s interval
            t = snapshot["time"]
            control_interval = llm_interval if strategy == "llm" else 30

            # Execute control logic at each interval
            if int(t) % control_interval == 0 and t > 0:
                try:
                    # Collect current traffic state
                    queues = engine.get_all_queue_lengths()
                    vehicle_counts = engine.get_all_vehicle_counts()

                    # ============================================================
                    # Webster Strategy
                    # ============================================================
                    if strategy == "webster":
                        for iid in _INTS:
                            q = queues[iid]
                            # Convert queue lengths to flow estimates
                            # Multiply by 120 (assuming 120 vehicles/hour/lane)
                            ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                            ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                            
                            # Compute optimal timing using Webster's formula
                            timings = webster.compute_timing({"EW": ew, "NS": ns})
                            
                            # Select phase with longer green time
                            phase = 0 if timings[0] >= timings[1] else 2
                            engine.set_phase(iid, phase, duration=int(max(timings)))

                    # ============================================================
                    # LLM Strategy (with coordination and constraints)
                    # ============================================================
                    elif strategy == "llm" and llm_client:
                        # Step 1: Batch LLM call for all intersections
                        # This reduces API calls from N to 1
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
                            # Get LLM recommendations for all intersections
                            batch_result = llm_client.get_batch_recommendation(all_states)
                            
                            # Cache the recommendations
                            for iid in _INTS:
                                pd = batch_result.get(iid, {}).get(
                                    "phase_durations", 
                                    {0: 30, 1: 3, 2: 30, 3: 3}
                                )
                                _timing_cache[iid] = {int(k): int(v) for k, v in pd.items()}
                        except Exception as llm_err:
                            # Fallback to default timing if LLM fails
                            logger.warning("LLM batch call failed: %s", llm_err)
                            for iid in _INTS:
                                _timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}

                        # Step 2: Apply coordination adjustments
                        # This adjusts timings based on upstream/downstream queues
                        try:
                            adj = coordination.compute_adjustments(queues, {})
                            _timing_cache = coordination.apply_adjustments(_timing_cache, adj)
                            coord_reasons = {iid: a.get("reason", "") for iid, a in adj.items()}
                            snapshot["coordination"] = coord_reasons
                        except Exception as coord_err:
                            logger.warning("Coordination failed: %s", coord_err)

                        # Step 3: Validate with constraint engine and apply
                        # This ensures all decisions are safe
                        for iid in _INTS:
                            timings = _timing_cache.get(iid, {0: 30, 1: 3, 2: 30, 3: 3})
                            green_phases = [timings.get(0, 30), timings.get(2, 30)]
                            cycle_len = sum(timings.values())
                            
                            # Validate and correct if needed
                            valid, violations, corrected = constraint_engine.validate(
                                green_phases, cycle_len
                            )
                            if not valid:
                                # Apply corrections
                                timings[0] = corrected[0] if len(corrected) > 0 else 30
                                timings[2] = corrected[1] if len(corrected) > 1 else 30
                            
                            # Set dominant phase (the one with longer green)
                            phase = 0 if timings.get(0, 30) >= timings.get(2, 30) else 2
                            duration_val = max(timings.get(0, 30), timings.get(2, 30))
                            engine.set_phase(iid, phase, duration=duration_val)

                        # Store LLM decisions in snapshot for visualization
                        snapshot["llm_decisions"] = {
                            iid: _timing_cache.get(iid, {})
                            for iid in _INTS
                        }

                except Exception as e:
                    logger.warning("Signal control error at t=%.0f: %s", t, e)

            # Push snapshot to main process (drop if queue is full)
            # This prevents memory exhaustion if main process is slow
            try:
                state_queue.put_nowait(snapshot)
            except Exception:
                pass  # Drop snapshot if queue is full

            # Delay between steps (controls simulation speed)
            _time.sleep(step_delay)

    except Exception as e:
        state_queue.put({"event": "error", "error": str(e)})
    finally:
        # Always collect final metrics and clean up
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


# ============================================================================
# Global State
# ============================================================================
# Simulation process
_sim_proc: mp.Process = None

# Inter-process communication
_state_queue: mp.Queue = mp.Queue(maxsize=500)  # Bounded to prevent memory exhaustion
_stop_event: mp.Event = mp.Event()

# Latest snapshot for REST API (thread-safe)
_latest: Dict = {"is_running": False, "time": 0}
import threading as _thr
_latest_lock = _thr.Lock()

# WebSocket clients
ws_clients: List[WebSocket] = []

# Discovered intersections (updated when simulation starts)
_current_intersections: List[str] = []
_current_approaches: Dict[str, Dict[str, str]] = {}

# Default simulation configuration
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


# ============================================================================
# Async Forwarder: Reads from mp.Queue, broadcasts to WS clients
# ============================================================================
async def _forward_loop():
    """Background task that reads from state_queue and broadcasts to WebSocket clients.
    
    This runs in the main process's event loop and:
    1. Reads messages from the simulation process
    2. Updates the latest state (for REST API)
    3. Broadcasts to all connected WebSocket clients
    
    Why async?
    - Non-blocking reads from queue
    - Non-blocking sends to WebSocket clients
    - Can handle multiple clients concurrently
    """
    global _current_intersections
    while True:
        try:
            # Try to get message from queue (non-blocking)
            try:
                msg = _state_queue.get_nowait()
            except Exception:
                msg = None

            if msg:
                # Update intersection list from started event
                if "intersections" in msg:
                    _current_intersections = msg["intersections"]

                # Update latest state (thread-safe)
                with _latest_lock:
                    _latest.update(msg)

                # Broadcast to all WebSocket clients
                disconnected = []
                for ws in ws_clients:
                    try:
                        await ws.send_json(msg)
                    except Exception:
                        disconnected.append(ws)
                
                # Remove disconnected clients
                for ws in disconnected:
                    ws_clients.remove(ws)
            else:
                # No message, wait a bit
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            break


# ============================================================================
# Application Lifespan
# ============================================================================
_fwd_task: asyncio.Task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager.
    
    Handles startup and shutdown:
    - Startup: Create background task for state forwarding
    - Shutdown: Stop simulation, cancel tasks, clean up
    """
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


# ============================================================================
# FastAPI Application
# ============================================================================
app = FastAPI(
    title="LLM-Traffic Backend",
    description="Multi-intersection traffic simulation with LLM-based signal optimization",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware (allow all origins for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Request Models
# ============================================================================
class SimulationRequest(BaseModel):
    """Request model for starting a simulation.
    
    Attributes:
        duration: Total simulation steps (default: 600)
        step_length: Duration of each step in seconds (default: 1)
        speed_factor: Simulation speed multiplier (default: 5.0)
        strategy: Control strategy ('fixed', 'random', 'webster', 'llm')
        llm_enabled: Whether to enable LLM (deprecated, use strategy='llm')
        llm_interval: Seconds between LLM calls (default: 30)
        green_wave: Whether to enable green wave coordination
        config_file: Path to .sumocfg file (None = default)
    """
    duration: int = 600
    step_length: int = 1
    speed_factor: float = 5.0
    strategy: str = "fixed"
    llm_enabled: bool = False
    llm_interval: int = 30
    green_wave: bool = False
    config_file: str = None


class ExperimentRequest(BaseModel):
    """Request model for running comparative experiments.
    
    Attributes:
        strategies: List of strategies to compare
        steps: Number of simulation steps per strategy
        config_file: Path to .sumocfg file (None = default)
    """
    strategies: List[str] = ["fixed", "random", "webster", "maxpressure", "rl", "llm"]
    steps: int = 3600
    config_file: str = None


# ============================================================================
# REST API Endpoints
# ============================================================================
@app.post("/api/simulation/start")
async def start_simulation(req: SimulationRequest = None):
    """Start a new simulation with the given configuration.
    
    This endpoint:
    1. Checks if simulation is already running
    2. Updates configuration
    3. Clears old state
    4. Starts simulation in a new process
    5. Returns immediately (non-blocking)
    
    Args:
        req: Simulation configuration (optional, uses defaults if not provided)
    
    Returns:
        Dict with status and configuration
    """
    global _sim_proc

    # Check if simulation is already running
    if _sim_proc and _sim_proc.is_alive():
        return {"status": "error", "message": "Simulation already running. Stop it first."}

    # Update configuration
    if req:
        sim_config.update(req.model_dump())

    # Drain queue (clear old snapshots)
    while not _state_queue.empty():
        try:
            _state_queue.get_nowait()
        except Exception:
            break

    # Clear stop event
    _stop_event.clear()

    # Reset latest state
    with _latest_lock:
        _latest.clear()
        _latest.update({"is_running": False, "time": 0})

    # Start simulation in new process
    _sim_proc = mp.Process(
        target=_sim_process_fn,
        args=(dict(sim_config), _state_queue, _stop_event),
        daemon=True,  # Auto-terminate when main process exits
    )
    _sim_proc.start()
    return {"status": "started", "config": sim_config}


@app.post("/api/simulation/stop")
async def stop_simulation():
    """Stop the running simulation.
    
    This endpoint:
    1. Sets the stop event (signals simulation process)
    2. Waits for process to finish (with timeout)
    3. Returns status
    
    Returns:
        Dict with status
    """
    global _sim_proc
    if _sim_proc and _sim_proc.is_alive():
        _stop_event.set()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sim_proc.join, 5)
        return {"status": "stopped"}
    return {"status": "no_simulation_running"}


@app.get("/api/simulation/state")
async def get_state():
    """Get the current simulation state.
    
    Returns the latest snapshot from the simulation process.
    This includes:
    - Current time
    - Queue lengths
    - Vehicle counts
    - Signal states
    - LLM decisions (if using LLM strategy)
    
    Returns:
        Dict with current simulation state
    """
    with _latest_lock:
        return dict(_latest)


@app.get("/api/simulation/metrics")
async def get_metrics():
    """Get aggregated simulation metrics.
    
    Returns metrics collected during simulation:
    - Average wait time
    - Average queue length
    - Throughput
    - Per-intersection breakdown
    
    Returns:
        Dict with simulation metrics
    """
    with _latest_lock:
        return _latest.get("metrics", _latest.get("final_metrics", {}))


@app.get("/api/intersections")
async def get_intersections():
    """Get discovered intersections from the current (or last) simulation.
    
    Intersections are automatically discovered from the SUMO network.
    Returns empty list if no simulation has run yet.
    
    Returns:
        Dict with list of intersection IDs
    """
    if _current_intersections:
        return {"intersections": _current_intersections}
    return {"intersections": [], "message": "Start a simulation to discover intersections."}


@app.get("/api/health")
async def health_check():
    """Health check endpoint.
    
    Returns:
        Dict with status and version info
    """
    return {
        "status": "healthy",
        "version": "2.0.0",
        "simulation_running": _sim_proc is not None and _sim_proc.is_alive(),
    }


@app.post("/api/experiment/compare")
async def run_experiment(req: ExperimentRequest = None):
    """Run comparative experiments sequentially in a subprocess.
    
    This endpoint runs multiple strategies back-to-back and collects
    metrics for comparison. Useful for A/B testing different approaches.
    
    Args:
        req: Experiment configuration (optional, uses defaults if not provided)
    
    Returns:
        Dict with results for each strategy
    """
    if not req:
        req = ExperimentRequest()

    def _run_one(strategy: str) -> dict:
        """Run a single strategy experiment.
        
        Args:
            strategy: Control strategy name
        
        Returns:
            Dict with simulation metrics
        """
        import os as _os
        _os.environ["SUMO_HOME"] = _os.environ.get("SUMO_HOME", "/usr/share/sumo")
        sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        
        # Import modules
        try:
            from simulation.sumo_engine import SumoEngine
            from algorithms.webster import WebsterController
            from algorithms.baseline import FixedTimeController, RandomController, MaxPressureController
            from algorithms.rl_controller import RLController
            from algorithms.constraints import SignalConstraintEngine
            from algorithms.coordination import CoordinationEngine
            from llm.xiaomi_client import LLMClient
        except ImportError:
            from backend.simulation.sumo_engine import SumoEngine
            from backend.algorithms.webster import WebsterController
            from backend.algorithms.baseline import FixedTimeController, RandomController, MaxPressureController
            from backend.algorithms.rl_controller import RLController
            from backend.algorithms.constraints import SignalConstraintEngine
            from backend.algorithms.coordination import CoordinationEngine
            from backend.llm.xiaomi_client import LLMClient

        # Initialize controller based on strategy
        ctrl_map = {
            "fixed": FixedTimeController(),
            "random": RandomController(seed=42),
            "webster": WebsterController(),
            "maxpressure": MaxPressureController(
                phase_directions={
                    "EW": ["east", "west"],
                    "NS": ["north", "south"],
                }
            ),
        }
        controller = ctrl_map.get(strategy)
        is_llm = strategy == "llm"
        is_rl = strategy == "rl"

        if not controller and not is_llm and not is_rl:
            return {"error": f"Unknown strategy: {strategy}"}

        # Initialize components
        engine = SumoEngine()
        constraint_engine = SignalConstraintEngine()
        coordination = CoordinationEngine()
        llm_client = LLMClient() if is_llm else None
        timing_cache: Dict[str, Dict[int, int]] = {}

        try:
            # Start simulation
            engine.start(config_file=req.config_file)
            _INTS = engine.intersections
            
            # Run simulation steps
            for step in range(req.steps):
                if not engine.step():
                    break
                
                # Control logic at each interval
                if step > 0 and step % 30 == 0:
                    queues = engine.get_all_queue_lengths()

                    if is_llm and llm_client:
                        # LLM strategy
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
                                pd = batch_result.get(iid, {}).get(
                                    "phase_durations", 
                                    {0: 30, 1: 3, 2: 30, 3: 3}
                                )
                                timing_cache[iid] = {int(k): int(v) for k, v in pd.items()}
                        except Exception:
                            for iid in _INTS:
                                timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}

                        # Apply coordination
                        adj = coordination.compute_adjustments(queues, {})
                        timing_cache = coordination.apply_adjustments(timing_cache, adj)

                        # Validate and apply
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
                    elif strategy == "maxpressure":
                        # MaxPressure: use raw queue lengths for pressure calc
                        for iid in _INTS:
                            q = queues.get(iid, {})
                            timings = controller.compute_timing(
                                {"EW": 1, "NS": 1},
                                queue_data=q,
                            )
                            phase = 0 if timings[0] >= timings[1] else 2
                            engine.set_phase(iid, phase, duration=int(max(timings)))
                    elif strategy == "rl":
                        # RL strategy (placeholder - needs RL controller implementation)
                        # For now, use random controller as placeholder
                        for iid in _INTS:
                            q = queues.get(iid, {})
                            ew = max((q.get("east", 0) + q.get("west", 0)) * 120, 100)
                            ns = max((q.get("north", 0) + q.get("south", 0)) * 120, 100)
                            timings = RandomController(seed=step).compute_timing({"EW": ew, "NS": ns})
                            phase = 0 if timings[0] >= timings[1] else 2
                            engine.set_phase(iid, phase, duration=int(max(timings)))
                    else:
                        # Other strategies
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

    # Run experiments sequentially
    loop = asyncio.get_event_loop()
    results = {}
    for s in req.strategies:
        results[s] = await loop.run_in_executor(None, _run_one, s)

    return {"status": "completed", "steps_per_strategy": req.steps, "results": results}
