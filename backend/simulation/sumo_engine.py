"""
SUMO simulation wrapper using TraCI.
"""
import os
import sys
import logging
from typing import Dict, List, Optional

# Set SUMO_HOME before importing traci
os.environ["SUMO_HOME"] = "/usr/share/sumo"

# Add SUMO tools to path
if "SUMO_HOME" in os.environ:
    tools = os.path.join(os.environ["SUMO_HOME"], "tools")
    if tools not in sys.path:
        sys.path.append(tools)

try:
    import traci
    TRACI_AVAILABLE = True
except ImportError:
    TRACI_AVAILABLE = False
    logging.warning("TraCI not available. SUMO simulation will not work.")

try:
    from backend.config.settings import (
        SUMO_BINARY, SUMO_CONFIG, TLS_ID, EDGES,
        DEFAULT_SIM_DURATION, DEFAULT_STEP_LENGTH
    )
except ImportError:
    from config.settings import (
        SUMO_BINARY, SUMO_CONFIG, TLS_ID, EDGES,
        DEFAULT_SIM_DURATION, DEFAULT_STEP_LENGTH
    )

logger = logging.getLogger(__name__)


class SumoEngine:
    """Wrapper around SUMO TraCI for traffic simulation control."""

    def __init__(self):
        self._is_running = False
        self._current_step = 0
        self._step_length = DEFAULT_STEP_LENGTH

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self, config_file: Optional[str] = None, step_length: int = 1, extra_args: Optional[List[str]] = None):
        """Start the SUMO simulation."""
        if self._is_running:
            logger.warning("Simulation already running, stopping first.")
            self.stop()

        cfg = config_file or SUMO_CONFIG
        self._step_length = step_length
        self._current_step = 0

        sumo_cmd = [SUMO_BINARY, "-c", cfg, "--step-length", str(step_length), "--no-step-log", "true"]
        if extra_args:
            sumo_cmd.extend(extra_args)

        logger.info(f"Starting SUMO with command: {' '.join(sumo_cmd)}")
        try:
            traci.start(sumo_cmd)
            self._is_running = True
            logger.info("SUMO simulation started successfully.")
        except Exception as e:
            logger.error(f"Failed to start SUMO: {e}")
            raise RuntimeError(f"Failed to start SUMO simulation: {e}")

    def stop(self):
        """Stop the SUMO simulation."""
        if self._is_running:
            try:
                traci.close()
            except Exception as e:
                logger.warning(f"Error closing TraCI: {e}")
            self._is_running = False
            self._current_step = 0
            logger.info("SUMO simulation stopped.")

    def step(self) -> bool:
        """Advance the simulation by one step. Returns False if simulation ended."""
        if not self._is_running:
            return False
        try:
            traci.simulationStep()
            self._current_step += 1
            return True
        except traci.exceptions.TraCIException as e:
            logger.error(f"TraCI error during step: {e}")
            self._is_running = False
            return False

    def get_vehicle_count(self) -> Dict[str, int]:
        """Get vehicle count per incoming edge."""
        counts = {}
        for direction, edge_id in EDGES.items():
            try:
                counts[direction] = traci.edge.getLastStepVehicleNumber(edge_id)
            except Exception:
                counts[direction] = 0
        return counts

    def get_queue_length(self) -> Dict[str, int]:
        """Get queue length (number of halting vehicles) per incoming edge."""
        queues = {}
        for direction, edge_id in EDGES.items():
            try:
                queues[direction] = traci.edge.getLastStepHaltingNumber(edge_id)
            except Exception:
                queues[direction] = 0
        return queues

    def get_avg_speed(self) -> Dict[str, float]:
        """Get average speed per incoming edge in m/s."""
        speeds = {}
        for direction, edge_id in EDGES.items():
            try:
                speeds[direction] = round(traci.edge.getLastStepMeanSpeed(edge_id), 2)
            except Exception:
                speeds[direction] = 0.0
        return speeds

    def get_waiting_time(self) -> Dict[str, float]:
        """Get average waiting time per incoming edge."""
        waiting = {}
        for direction, edge_id in EDGES.items():
            try:
                waiting[direction] = round(traci.edge.getWaitingTime(edge_id), 2)
            except Exception:
                waiting[direction] = 0.0
        return waiting

    def get_current_phase(self) -> tuple:
        """Get current traffic light phase index and its remaining duration."""
        try:
            phase = traci.trafficlight.getPhase(TLS_ID)
            # Get the complete logics to find current phase duration
            logics = traci.trafficlight.getAllProgramLogics(TLS_ID)
            if logics:
                current_logic = logics[0]
                phases = current_logic.getPhases()
                if 0 <= phase < len(phases):
                    duration = phases[phase].duration
                else:
                    duration = 0
            else:
                duration = 0
            return phase, duration
        except Exception as e:
            logger.error(f"Error getting traffic light phase: {e}")
            return 0, 0

    def get_total_vehicles(self) -> int:
        """Get total number of vehicles currently in the simulation."""
        try:
            return traci.vehicle.getIDCount()
        except Exception:
            return 0

    def set_phase(self, phase_index: int, duration: int = 30):
        """Set traffic light to a specific phase with given duration."""
        if not self._is_running:
            raise RuntimeError("Simulation is not running.")
        try:
            traci.trafficlight.setPhase(TLS_ID, phase_index)
            # Set phase duration by modifying the program
            traci.trafficlight.setPhaseDuration(TLS_ID, duration)
            logger.info(f"Set traffic light to phase {phase_index} for {duration}s")
        except Exception as e:
            logger.error(f"Error setting phase: {e}")
            raise

    def set_phase_durations(self, phase_durations: Dict[int, int]):
        """Set durations for all phases. phase_durations maps phase index to duration."""
        if not self._is_running:
            raise RuntimeError("Simulation is not running.")
        try:
            logics = traci.trafficlight.getAllProgramLogics(TLS_ID)
            if not logics:
                raise RuntimeError("No traffic light programs found.")

            current_logic = logics[0]
            phases = list(current_logic.getPhases())

            # Update phase durations
            for idx, phase_obj in enumerate(phases):
                if idx in phase_durations:
                    new_dur = phase_durations[idx]
                    # Create new phase with updated duration
                    from traci._trafficlight import Phase
                    phases[idx] = Phase(new_dur, phase_obj.state, new_dur, new_dur)

            # Rebuild and set the logic
            from traci._trafficlight import Logic
            new_logic = Logic(
                current_logic.programID,
                current_logic.type,
                current_logic.currentPhaseIndex,
                phases
            )
            traci.trafficlight.setProgramLogic(TLS_ID, new_logic)
            logger.info(f"Updated phase durations: {phase_durations}")
        except Exception as e:
            logger.error(f"Error setting phase durations: {e}")
            raise

    def get_traffic_state(self) -> Dict:
        """Get complete traffic state snapshot."""
        vehicle_counts = self.get_vehicle_count()
        queue_lengths = self.get_queue_length()
        avg_speeds = self.get_avg_speed()
        waiting_times = self.get_waiting_time()
        current_phase, phase_duration = self.get_current_phase()
        total_vehicles = self.get_total_vehicles()

        return {
            "time": self._current_step * self._step_length,
            "vehicle_counts": vehicle_counts,
            "queue_lengths": queue_lengths,
            "avg_speeds": avg_speeds,
            "avg_waiting_times": waiting_times,
            "current_phase": current_phase,
            "current_phase_duration": phase_duration,
            "total_vehicles": total_vehicles,
            "is_running": self._is_running,
        }

    @property
    def simulation_time(self) -> float:
        return self._current_step * self._step_length

    def __del__(self):
        self.stop()
