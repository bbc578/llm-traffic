"""
Multi-intersection SUMO simulation engine using TraCI.

Network-agnostic: auto-discovers traffic lights and approach edges
from whatever .sumocfg is loaded (grid6, Cologne subnetwork, etc.).
"""
import os
import sys
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Set SUMO_HOME before importing traci
os.environ["SUMO_HOME"] = os.environ.get("SUMO_HOME", "/usr/share/sumo")
_tools = os.path.join(os.environ["SUMO_HOME"], "tools")
if _tools not in sys.path:
    sys.path.append(_tools)

try:
    import traci
    TRACI_AVAILABLE = True
except ImportError:
    TRACI_AVAILABLE = False
    logging.warning("TraCI not available. SUMO simulation will not work.")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "data", "grid6.sumocfg")


@dataclass
class IntersectionMetrics:
    """Metrics for a single intersection."""
    total_wait_time: float = 0.0
    total_queue_length: int = 0
    total_vehicle_count: int = 0
    sample_count: int = 0

    @property
    def avg_wait_time(self) -> float:
        return self.total_wait_time / self.sample_count if self.sample_count else 0.0

    @property
    def avg_queue_length(self) -> float:
        return self.total_queue_length / self.sample_count if self.sample_count else 0.0

    @property
    def avg_vehicle_count(self) -> float:
        return self.total_vehicle_count / self.sample_count if self.sample_count else 0.0


@dataclass
class SimulationMetrics:
    """Aggregate simulation metrics."""
    per_intersection: Dict[str, IntersectionMetrics] = field(default_factory=dict)
    total_steps: int = 0
    vehicles_departed: int = 0
    vehicles_arrived: int = 0

    @property
    def avg_wait_time(self) -> float:
        vals = [m.avg_wait_time for m in self.per_intersection.values()]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_queue_length(self) -> float:
        vals = [m.avg_queue_length for m in self.per_intersection.values()]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def throughput(self) -> float:
        return self.vehicles_arrived / self.total_steps if self.total_steps else 0.0

    def summary(self) -> Dict:
        return {
            "total_steps": self.total_steps,
            "throughput": round(self.throughput, 4),
            "avg_wait_time": round(self.avg_wait_time, 2),
            "avg_queue_length": round(self.avg_queue_length, 2),
            "vehicles_departed": self.vehicles_departed,
            "vehicles_arrived": self.vehicles_arrived,
            "per_intersection": {
                iid: {
                    "avg_wait_time": round(m.avg_wait_time, 2),
                    "avg_queue_length": round(m.avg_queue_length, 2),
                    "avg_vehicle_count": round(m.avg_vehicle_count, 2),
                }
                for iid, m in self.per_intersection.items()
            },
        }


class SumoEngine:
    """Network-agnostic SUMO simulation engine."""

    def __init__(self):
        self._is_running = False
        self._current_step = 0
        self._step_length = 1
        self._metrics = SimulationMetrics()
        self._intersections: List[str] = []
        self._approach_edges: Dict[str, Dict[str, str]] = {}

    # -- lifecycle ----------------------------------------------------------

    def start(
        self,
        config_file: Optional[str] = None,
        step_length: int = 1,
        extra_args: Optional[List[str]] = None,
    ):
        """Start SUMO with the given config.

        Auto-discovers traffic lights and their approach edges from the network.
        """
        if self._is_running:
            logger.warning("Simulation already running, stopping first.")
            self.stop()

        cfg = config_file or DEFAULT_CONFIG
        if not os.path.isabs(cfg):
            cfg = os.path.abspath(cfg)

        self._step_length = step_length
        self._current_step = 0
        self._metrics = SimulationMetrics()

        sumo_binary = "sumo"
        sumo_home = os.environ.get("SUMO_HOME", "/usr/share/sumo")
        for candidate in ["sumo", os.path.join(sumo_home, "bin", "sumo")]:
            if os.path.isfile(candidate) or candidate == "sumo":
                sumo_binary = candidate
                break

        sumo_cmd = [
            sumo_binary,
            "-c", cfg,
            "--step-length", str(step_length),
            "--no-step-log", "true",
        ]
        if extra_args:
            sumo_cmd.extend(extra_args)

        logger.info("Starting SUMO: %s", " ".join(sumo_cmd))
        try:
            traci.start(sumo_cmd)
            self._is_running = True
            self._discover_network()
            logger.info("SUMO started. Discovered %d intersections.", len(self._intersections))
        except Exception as e:
            logger.error(f"Failed to start SUMO: {e}")
            raise RuntimeError(f"Failed to start SUMO: {e}")

    @staticmethod
    def _lane_to_edge(lane_id: str) -> str:
        """Convert a lane ID ('edgeId_laneIdx') to its edge ID ('edgeId')."""
        # Lane IDs look like 'some_edge_0' or 'some_edge#1_2'
        # The last '_N' is the lane index; strip it
        parts = lane_id.rsplit('_', 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0]
        return lane_id

    def _discover_network(self):
        """Auto-discover TLS IDs and their approach edges from the running SUMO instance."""
        self._intersections = []
        self._approach_edges = {}

        tl_ids = traci.trafficlight.getIDList()
        logger.info("Found %d traffic lights: %s", len(tl_ids), list(tl_ids))

        for tl_id in tl_ids:
            self._intersections.append(tl_id)
            self._approach_edges[tl_id] = {}

            try:
                controlled_links = traci.trafficlight.getControlledLinks(tl_id)
                # getControlledLinks returns [[(fromLane, toLane, viaLane), ...], ...]
                # Each element is one signal phase; each tuple is one connection.
                seen_edges = {}  # edge_id -> lane_id (for position lookup)
                for phase_links in controlled_links:
                    for link in phase_links:
                        from_lane = link[0]
                        if from_lane and not from_lane.startswith(':'):
                            edge_id = self._lane_to_edge(from_lane)
                            seen_edges[edge_id] = from_lane

                # Map edges to compass directions relative to TLS position
                # SUMO 1.12.0 doesn't have trafficlight.getPosition;
                # use junction.getPosition (TLS ID == junction ID)
                try:
                    tls_pos = traci.junction.getPosition(tl_id)
                except Exception:
                    tls_pos = (0, 0)

                for edge_id, lane_id in seen_edges.items():
                    try:
                        end_pos = traci.lane.getShape(lane_id)[-1]
                        dx = end_pos[0] - tls_pos[0]
                        dy = end_pos[1] - tls_pos[1]
                        if abs(dx) > abs(dy):
                            direction = "east" if dx > 0 else "west"
                        else:
                            direction = "north" if dy > 0 else "south"
                        self._approach_edges[tl_id][direction] = edge_id
                    except Exception:
                        pass

                if not self._approach_edges[tl_id]:
                    for i, edge_id in enumerate(seen_edges):
                        self._approach_edges[tl_id][f"approach_{i}"] = edge_id

            except Exception as e:
                logger.warning("Failed to discover edges for TLS %s: %s", tl_id, e)

        for iid in self._intersections:
            self._metrics.per_intersection[iid] = IntersectionMetrics()

    def stop(self):
        """Stop the SUMO simulation and reset state."""
        if self._is_running:
            try:
                traci.close()
            except Exception:
                pass
            self._is_running = False
            logger.info("SUMO simulation stopped after %d steps.", self._current_step)

    def step(self) -> bool:
        """Advance one simulation step. Returns False when simulation ends."""
        if not self._is_running:
            return False
        try:
            traci.simulationStep()
            self._current_step += 1
            self._collect_metrics()
            return True
        except Exception as e:
            logger.error(f"Simulation step failed: {e}")
            self._is_running = False
            return False

    def _collect_metrics(self):
        """Collect per-intersection metrics."""
        for iid in self._intersections:
            m = self._metrics.per_intersection[iid]
            m.sample_count += 1

            # Queue length
            queue_sum = 0
            for edge_id in self._approach_edges.get(iid, {}).values():
                try:
                    queue_sum += traci.edge.getLastStepHaltingNumber(edge_id)
                except Exception:
                    pass
            m.total_queue_length += queue_sum

            # Vehicle count
            veh_sum = 0
            for edge_id in self._approach_edges.get(iid, {}).values():
                try:
                    veh_sum += traci.edge.getLastStepVehicleNumber(edge_id)
                except Exception:
                    pass
            m.total_vehicle_count += veh_sum

            # Wait time (from vehicles on approach edges)
            wait_sum = 0.0
            count = 0
            for edge_id in self._approach_edges.get(iid, {}).values():
                try:
                    for vid in traci.edge.getLastStepVehicleIDs(edge_id):
                        wait_sum += traci.vehicle.getWaitingTime(vid)
                        count += 1
                except Exception:
                    pass
            m.total_wait_time += (wait_sum / count if count else 0)

        self._metrics.total_steps = self._current_step
        try:
            self._metrics.vehicles_departed += traci.simulation.getDepartedNumber()
            self._metrics.vehicles_arrived += traci.simulation.getArrivedNumber()
        except Exception:
            pass

    # -- signal control -----------------------------------------------------

    def set_signal_program(self, intersection_id: str, program_id: int):
        """Switch an intersection to a named program."""
        if not self._is_running:
            raise RuntimeError("Simulation is not running.")
        if intersection_id not in self._intersections:
            raise ValueError(f"Unknown intersection: {intersection_id}")
        try:
            traci.trafficlight.setProgram(intersection_id, str(program_id))
        except Exception as e:
            logger.error(f"Error setting program on {intersection_id}: {e}")
            raise

    def set_phase(self, intersection_id: str, phase_index: int, duration: int = 30):
        """Set a specific phase on an intersection."""
        if not self._is_running:
            raise RuntimeError("Simulation is not running.")
        try:
            traci.trafficlight.setPhase(intersection_id, phase_index)
            traci.trafficlight.setPhaseDuration(intersection_id, duration)
        except Exception as e:
            logger.error(f"Error setting phase on {intersection_id}: {e}")
            raise

    def get_signal_state(self, intersection_id: str) -> Dict:
        """Return current phase index, program ID, and state string."""
        try:
            phase = traci.trafficlight.getPhase(intersection_id)
            program = traci.trafficlight.getProgram(intersection_id)
            state = traci.trafficlight.getRedYellowGreenState(intersection_id)
            return {
                "intersection": intersection_id,
                "program": program,
                "phase": phase,
                "state": state,
            }
        except Exception as e:
            logger.error(f"Error reading signal state for {intersection_id}: {e}")
            return {"intersection": intersection_id, "program": "?", "phase": -1, "state": "?"}

    def get_all_signal_states(self) -> List[Dict]:
        return [self.get_signal_state(iid) for iid in self._intersections]

    # -- per-intersection data retrieval ------------------------------------

    def get_queue_lengths(self, intersection_id: str) -> Dict[str, int]:
        """Queue length (halting vehicles) per approach for one intersection."""
        result = {}
        for direction, edge_id in self._approach_edges.get(intersection_id, {}).items():
            try:
                result[direction] = traci.edge.getLastStepHaltingNumber(edge_id)
            except Exception:
                result[direction] = 0
        return result

    def get_vehicle_counts(self, intersection_id: str) -> Dict[str, int]:
        """Vehicle count per approach for one intersection."""
        result = {}
        for direction, edge_id in self._approach_edges.get(intersection_id, {}).items():
            try:
                result[direction] = traci.edge.getLastStepVehicleNumber(edge_id)
            except Exception:
                result[direction] = 0
        return result

    def get_all_queue_lengths(self) -> Dict[str, Dict[str, int]]:
        return {iid: self.get_queue_lengths(iid) for iid in self._intersections}

    def get_all_vehicle_counts(self) -> Dict[str, Dict[str, int]]:
        return {iid: self.get_vehicle_counts(iid) for iid in self._intersections}

    def get_total_vehicles(self) -> int:
        try:
            return traci.vehicle.getIDCount()
        except Exception:
            return 0

    # -- properties ---------------------------------------------------------

    @property
    def intersections(self) -> List[str]:
        return list(self._intersections)

    @property
    def approach_edges(self) -> Dict[str, Dict[str, str]]:
        return dict(self._approach_edges)

    @property
    def metrics(self) -> SimulationMetrics:
        return self._metrics

    @property
    def simulation_time(self) -> float:
        try:
            return traci.simulation.getTime()
        except Exception:
            return self._current_step * self._step_length

    @property
    def current_step(self) -> int:
        return self._current_step

    @property
    def is_running(self) -> bool:
        return self._is_running

    def get_snapshot(self) -> Dict:
        """Full snapshot: all signals, all queues, all counts, metrics."""
        return {
            "step": self._current_step,
            "time": self.simulation_time,
            "total_vehicles": self.get_total_vehicles(),
            "signals": self.get_all_signal_states(),
            "queue_lengths": self.get_all_queue_lengths(),
            "vehicle_counts": self.get_all_vehicle_counts(),
            "metrics": self._metrics.summary(),
        }

    def __del__(self):
        self.stop()
