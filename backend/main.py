"""
FastAPI backend for LLM-Traffic simulation.
"""
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from backend.config.settings import DEFAULT_SIM_DURATION, LLM_CALL_INTERVAL
    from backend.models.schemas import (
        SimulationState, LLMRecommendation, SimulationConfig, PhaseRequest
    )
    from backend.simulation.sumo_engine import SumoEngine
    from backend.llm.xiaomi_client import LLMClient
except ImportError:
    from config.settings import DEFAULT_SIM_DURATION, LLM_CALL_INTERVAL
    from models.schemas import (
        SimulationState, LLMRecommendation, SimulationConfig, PhaseRequest
    )
    from simulation.sumo_engine import SumoEngine
    from llm.xiaomi_client import LLMClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
sumo_engine = SumoEngine()
llm_client = LLMClient()
simulation_task: asyncio.Task = None
ws_clients: List[WebSocket] = []
simulation_config: SimulationConfig = SimulationConfig()


async def broadcast_state(state: dict):
    """Send state to all connected WebSocket clients."""
    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_json(state)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        ws_clients.remove(ws)


async def simulation_loop():
    """Background task that runs the simulation."""
    global sumo_engine, llm_client, simulation_config
    llm_interval = simulation_config.llm_call_interval
    last_llm_call = 0

    try:
        sumo_engine.start(step_length=simulation_config.step_length)
        logger.info("Simulation loop started.")

        while sumo_engine.is_running:
            # Check if simulation exceeded configured duration
            if sumo_engine.simulation_time >= simulation_config.duration:
                logger.info("Simulation duration reached, stopping.")
                break

            # Step the simulation
            if not sumo_engine.step():
                break

            # Get current state
            state = sumo_engine.get_traffic_state()

            # LLM optimization
            if simulation_config.llm_enabled:
                current_time = state["time"]
                if current_time - last_llm_call >= llm_interval and current_time > 0:
                    try:
                        logger.info(f"Calling LLM at t={current_time}s")
                        recommendation = llm_client.get_recommendation(state)
                        phase_durations = recommendation["phase_durations"]
                        # Apply LLM recommendation
                        if phase_durations:
                            sumo_engine.set_phase_durations(phase_durations)
                            state["llm_recommendation"] = recommendation
                        last_llm_call = current_time
                    except Exception as e:
                        logger.error(f"LLM call failed: {e}")

            state["is_running"] = True
            await broadcast_state(state)

            # Real-time pacing: delay between steps based on speed_factor
            # speed_factor=1.0 means real-time, 5.0 means 5x faster
            delay = simulation_config.step_length / simulation_config.speed_factor
            await asyncio.sleep(delay)

    except Exception as e:
        logger.error(f"Simulation error: {e}")
    finally:
        sumo_engine.stop()
        final_state = {
            "time": sumo_engine.simulation_time,
            "is_running": False,
            "total_vehicles": 0,
            "vehicle_counts": {"north": 0, "south": 0, "east": 0, "west": 0},
            "queue_lengths": {"north": 0, "south": 0, "east": 0, "west": 0},
            "avg_speeds": {"north": 0.0, "south": 0.0, "east": 0.0, "west": 0.0},
            "avg_waiting_times": {"north": 0.0, "south": 0.0, "east": 0.0, "west": 0.0},
            "current_phase": 0,
            "current_phase_duration": 0.0,
            "message": "Simulation ended",
        }
        await broadcast_state(final_state)
        logger.info("Simulation loop ended.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("LLM-Traffic backend starting.")
    yield
    logger.info("LLM-Traffic backend shutting down.")
    if sumo_engine.is_running:
        sumo_engine.stop()


app = FastAPI(
    title="LLM-Traffic Backend",
    description="Traffic simulation with LLM-based signal optimization",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/simulation/start")
async def start_simulation(config: SimulationConfig = None):
    """Start a new simulation with the given configuration."""
    global simulation_task, simulation_config

    if simulation_task and not simulation_task.done():
        return {"status": "error", "message": "Simulation already running. Stop it first."}

    if config:
        simulation_config = config
    else:
        simulation_config = SimulationConfig()

    simulation_task = asyncio.create_task(simulation_loop())
    return {
        "status": "started",
        "config": simulation_config.model_dump(),
    }


@app.post("/api/simulation/stop")
async def stop_simulation():
    """Stop the current simulation."""
    global simulation_task

    if simulation_task and not simulation_task.done():
        sumo_engine.stop()
        simulation_task.cancel()
        try:
            await simulation_task
        except asyncio.CancelledError:
            pass
        return {"status": "stopped"}
    return {"status": "no_simulation_running"}


@app.get("/api/simulation/state", response_model=SimulationState)
async def get_state():
    """Get the current simulation state."""
    if sumo_engine.is_running:
        state = sumo_engine.get_traffic_state()
        return SimulationState(**state)
    return SimulationState(is_running=False)


@app.post("/api/simulation/set-phase")
async def set_phase(request: PhaseRequest):
    """Manually set the traffic light phase."""
    if not sumo_engine.is_running:
        return {"status": "error", "message": "Simulation not running"}
    try:
        sumo_engine.set_phase(request.phase_index, request.duration)
        return {
            "status": "ok",
            "phase_index": request.phase_index,
            "duration": request.duration,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/health")
async def health():
    return {"status": "ok", "simulation_running": sumo_engine.is_running}


@app.websocket("/ws/simulation")
async def websocket_simulation(ws: WebSocket):
    """WebSocket endpoint for streaming real-time simulation data."""
    await ws.accept()
    ws_clients.append(ws)
    logger.info(f"WebSocket client connected. Total: {len(ws_clients)}")

    try:
        while True:
            # Keep connection alive, wait for messages (like ping)
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
