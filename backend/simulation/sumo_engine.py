"""
Multi-Intersection SUMO Simulation Engine using TraCI

This module provides a network-agnostic interface to SUMO traffic simulation.
It automatically discovers traffic lights and their approach edges from whatever
.sumocfg file is loaded (grid6, Cologne subnetwork, etc.).

Key Design Decisions:
=====================
1. **Network-agnostic**: Works with any SUMO network without modification
2. **Auto-discovery**: Automatically finds traffic lights and edges
3. **Direction mapping**: Maps edges to compass directions (N/S/E/W)
4. **Metrics collection**: Collects per-intersection statistics

Why Network-agnostic?
- Easy to switch between test scenarios
- No hardcoded intersection IDs
- Works with real-world networks

Architecture:
=============
SumoEngine
├── start(): Initialize SUMO and discover network
├── step(): Advance one simulation step
├── get_snapshot(): Collect current state
├── set_phase(): Control signal timing
└── stop(): Clean up and close SUMO

Data Flow:
==========
1. start() → Connect to SUMO, discover traffic lights
2. step() → Advance simulation, collect metrics
3. get_snapshot() → Return current state for visualization
4. set_phase() → Apply signal timing decisions
5. stop() → Close TraCI connection

Metrics Collected:
==================
- Wait time: Time vehicles spend waiting at red lights
- Queue length: Number of stopped vehicles per approach
- Vehicle count: Total vehicles on each approach
- Delay: Wait time + time loss
- Stops: Number of complete stops per vehicle

Author: Yihao Tang
Date: 2024
"""

import os
import sys
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Set SUMO_HOME before importing traci
# This is required for TraCI to find SUMO binaries
os.environ["SUMO_HOME"] = os.environ.get("SUMO_HOME", "/usr/share/sumo")
_tools = os.path.join(os.environ["SUMO_HOME"], "tools")
if _tools not in sys.path:
    sys.path.append(_tools)

# Import TraCI with graceful fallback
try:
    import traci
    TRACI_AVAILABLE = True
except ImportError:
    TRACI_AVAILABLE = False
    logging.warning("TraCI not available. SUMO simulation will not work.")

logger = logging.getLogger(__name__)


# ============================================================================
# Default Configuration
# ============================================================================
DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "data", "grid6.sumocfg")


# ============================================================================
# Metrics Data Classes
# ============================================================================
@dataclass
class IntersectionMetrics:
    """Metrics for a single intersection.
    
    Collects statistics for each intersection including:
    - Wait time: How long vehicles wait at red lights
    - Queue length: Number of stopped vehicles
    - Vehicle count: Total vehicles on approaches
    - Delay: Wait time + time loss (more accurate than wait time alone)
    - Stops: Number of complete stops (speed < 0.1 m/s)
    
    All metrics are accumulated over time and averaged when requested.
    """
    total_wait_time: float = 0.0
    total_queue_length: int = 0
    total_vehicle_count: int = 0
    total_delay: float = 0.0
    total_stops: int = 0
    sample_count: int = 0

    @property
    def avg_wait_time(self) -> float:
        """Average wait time across all samples.
        
        Returns:
            Average wait time in seconds, or 0.0 if no samples.
        """
        return self.total_wait_time / self.sample_count if self.sample_count else 0.0

    @property
    def avg_queue_length(self) -> float:
        """Average queue length across all samples.
        
        Returns:
            Average number of stopped vehicles, or 0.0 if no samples.
        """
        return self.total_queue_length / self.sample_count if self.sample_count else 0.0

    @property
    def avg_vehicle_count(self) -> float:
        """Average vehicle count across all samples.
        
        Returns:
            Average number of vehicles on approaches, or 0.0 if no samples.
        """
        return self.total_vehicle_count / self.sample_count if self.sample_count else 0.0


@dataclass
class SimulationMetrics:
    """Aggregate simulation metrics.
    
    Collects metrics across all intersections and provides:
    - Per-intersection breakdown
    - Aggregate statistics
    - Vehicle departure/arrival counts
    """
    per_intersection: Dict[str, IntersectionMetrics] = field(default_factory=dict)
    total_steps: int = 0
    vehicles_departed: int = 0
    vehicles_arrived: int = 0

    @property
    def avg_wait_time(self) -> float:
        """Mean average wait time across all intersections.
        
        Returns:
            Average wait time in seconds, or 0.0 if no data.
        """
        vals = [m.avg_wait_time for m in self.per_intersection.values()]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_queue_length(self) -> float:
        """Mean average queue length across all intersections.
        
        Returns:
            Average queue length, or 0.0 if no data.
        """
        vals = [m.avg_queue_length for m in self.per_intersection.values()]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def throughput(self) -> float:
        """Vehicles arrived per simulation step.
        
        This is the key performance metric:
        - Higher throughput = more vehicles passing through
        - Indicates efficient signal timing
        
        Returns:
            Vehicles per step, or 0.0 if no steps.
        """
        return self.vehicles_arrived / self.total_steps if self.total_steps else 0.0

    @property
    def avg_delay(self) -> float:
        """Mean average delay across all intersections.
        
        Delay = wait time + time loss (more accurate than wait time alone)
        
        Returns:
            Average delay in seconds, or 0.0 if no data.
        """
        vals = [m.total_delay / m.sample_count if m.sample_count else 0 for m in self.per_intersection.values()]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_stops(self) -> float:
        """Mean average stops per vehicle across all intersections.
        
        Fewer stops = smoother traffic flow
        
        Returns:
            Average stops per vehicle, or 0.0 if no data.
        """
        vals = [m.total_stops / m.sample_count if m.sample_count else 0 for m in self.per_intersection.values()]
        return sum(vals) / len(vals) if vals else 0.0

    def summary(self) -> Dict:
        """Return a serializable summary of all simulation metrics.
        
        Returns:
            Dict with:
            - total_steps: Number of simulation steps
            - throughput: Vehicles arrived per step
            - avg_wait_time: Average wait time across intersections
            - avg_queue_length: Average queue length across intersections
            - avg_delay: Average delay across intersections
            - avg_stops: Average stops per vehicle
            - vehicles_departed: Total vehicles that entered the network
            - vehicles_arrived: Total vehicles that exited the network
            - per_intersection: Per-intersection breakdown
        """
        return {
            "total_steps": self.total_steps,
            "throughput": round(self.throughput, 4),
            "avg_wait_time": round(self.avg_wait_time, 2),
            "avg_queue_length": round(self.avg_queue_length, 2),
            "avg_delay": round(self.avg_delay, 2),
            "avg_stops": round(self.avg_stops, 2),
            "vehicles_departed": self.vehicles_departed,
            "vehicles_arrived": self.vehicles_arrived,
            "per_intersection": {
                iid: {
                    "avg_wait_time": round(m.avg_wait_time, 2),
                    "avg_queue_length": round(m.avg_queue_length, 2),
                    "avg_vehicle_count": round(m.avg_vehicle_count, 2),
                    "avg_delay": round(m.total_delay / m.sample_count if m.sample_count else 0, 2),
                    "avg_stops": round(m.total_stops / m.sample_count if m.sample_count else 0, 2),
                }
                for iid, m in self.per_intersection.items()
            },
        }


# ============================================================================
# Main Simulation Engine
# ============================================================================
class SumoEngine:
    """Network-agnostic SUMO simulation engine.
    
    This class provides a high-level interface to SUMO simulation:
    1. Auto-discovers traffic lights and their approach edges
    2. Provides simple methods to control signals
    3. Collects comprehensive metrics
    4. Handles SUMO lifecycle (start/stop)
    
    Usage:
        engine = SumoEngine()
        engine.start(config_file="path/to/network.sumocfg")
        
        for step in range(1000):
            if not engine.step():
                break
            
            # Get current state
            snapshot = engine.get_snapshot()
            
            # Control signals
            engine.set_phase("intersection_id", phase=0, duration=30)
        
        metrics = engine.metrics.summary()
        engine.stop()
    """

    def __init__(self):
        """Initialize the SUMO simulation engine.
        
        Sets up internal state:
        - _is_running: Whether simulation is active
        - _current_step: Number of steps completed
        - _step_length: Duration of each step
        - _metrics: Collected metrics
        - _intersections: Discovered traffic light IDs
        - _approach_edges: Mapping of intersection to direction→edge
        """
        self._is_running = False
        self._current_step = 0
        self._step_length = 1
        self._metrics = SimulationMetrics()
        self._intersections: List[str] = []
        self._approach_edges: Dict[str, Dict[str, str]] = {}


    # ========================================================================
    # Lifecycle Methods
    # ========================================================================
    def start(
        self,
        config_file: Optional[str] = None,
        step_length: int = 1,
        extra_args: Optional[List[str]] = None,
    ):
        """Start SUMO with the given config and auto-discover the network.
        
        This method:
        1. Stops any running simulation
        2. Constructs SUMO command line
        3. Starts SUMO via TraCI
        4. Auto-discovers traffic lights and edges
        5. Initializes metrics collection
        
        Args:
            config_file: Path to a .sumocfg file. Defaults to data/grid6.sumocfg.
            step_length: Simulation step duration in seconds.
            extra_args: Additional CLI arguments passed to the SUMO binary.
        
        Raises:
            RuntimeError: If SUMO fails to start.
        """
        # Stop any existing simulation
        if self._is_running:
            logger.warning("Simulation already running, stopping first.")
            self.stop()

        # Resolve config file path
        cfg = config_file or DEFAULT_CONFIG
        if not os.path.isabs(cfg):
            cfg = os.path.abspath(cfg)

        # Initialize state
        self._step_length = step_length
        self._current_step = 0
        self._metrics = SimulationMetrics()

        # Find SUMO binary
        # Try multiple locations for robustness
        sumo_binary = "sumo"
        sumo_home = os.environ.get("SUMO_HOME", "/usr/share/sumo")
        for candidate in ["sumo", os.path.join(sumo_home, "bin", "sumo")]:
            if os.path.isfile(candidate) or candidate == "sumo":
                sumo_binary = candidate
                break

        # Construct SUMO command
        # --no-step-log: Suppress per-step logging
        sumo_cmd = [
            sumo_binary,
            "-c", cfg,
            "--step-length", str(step_length),
            "--no-step-log", "true",
        ]
        if extra_args:
            sumo_cmd.extend(extra_args)

        # Start SUMO
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
        """Convert a lane ID ('edgeId_laneIdx') to its edge ID ('edgeId').
        
        SUMO lane IDs look like 'some_edge_0' or 'some_edge#1_2'
        The last '_N' is the lane index; we strip it to get the edge ID.
        
        Args:
            lane_id: SUMO lane ID (e.g., 'edge1_0')
        
        Returns:
            Edge ID (e.g., 'edge1')
        """
        parts = lane_id.rsplit('_', 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0]
        return lane_id


    def _discover_network(self):
        """Auto-discover TLS IDs and their approach edges from the running SUMO instance.
        
        This method:
        1. Gets all traffic light IDs from SUMO
        2. For each TLS, finds controlled links
        3. Maps edges to compass directions using geometry
        4. Builds _approach_edges mapping
        
        Why compass directions?
        - Intuitive for LLM prompt construction
        - Consistent across different networks
        - Easy to understand for debugging
        
        Direction mapping logic:
        - Compare edge endpoint position to TLS position
        - If horizontal distance > vertical distance: east/west
        - Otherwise: north/south
        """
        self._intersections = []
        self._approach_edges = {}

        # Get all traffic light IDs
        tl_ids = traci.trafficlight.getIDList()
        logger.info("Found %d traffic lights: %s", len(tl_ids), list(tl_ids))

        for tl_id in tl_ids:
            self._intersections.append(tl_id)
            self._approach_edges[tl_id] = {}

            try:
                # Get controlled links for this TLS
                # Returns [[(fromLane, toLane, viaLane), ...], ...]
                # Each element is one signal phase; each tuple is one connection
                controlled_links = traci.trafficlight.getControlledLinks(tl_id)
                
                # Collect all unique edges that feed into this TLS
                seen_edges = {}  # edge_id -> lane_id (for position lookup)
                for phase_links in controlled_links:
                    for link in phase_links:
                        from_lane = link[0]
                        # Skip internal edges (start with ':')
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
                        # Get the end point of the lane (where it meets the TLS)
                        end_pos = traci.lane.getShape(lane_id)[-1]
                        
                        # Calculate direction relative to TLS
                        dx = end_pos[0] - tls_pos[0]
                        dy = end_pos[1] - tls_pos[1]
                        
                        # Determine compass direction
                        if abs(dx) > abs(dy):
                            direction = "east" if dx > 0 else "west"
                        else:
                            direction = "north" if dy > 0 else "south"
                        
                        self._approach_edges[tl_id][direction] = edge_id
                    except Exception:
                        pass

                # Fallback: if no directions found, use generic names
                if not self._approach_edges[tl_id]:
                    for i, edge_id in enumerate(seen_edges):
                        self._approach_edges[tl_id][f"approach_{i}"] = edge_id

            except Exception as e:
                logger.warning("Failed to discover edges for TLS %s: %s", tl_id, e)

        # Initialize per-intersection metrics
        for iid in self._intersections:
            self._metrics.per_intersection[iid] = IntersectionMetrics()


    def stop(self):
        """Stop the SUMO simulation and reset state.
        
        This method:
        1. Closes TraCI connection
        2. Resets running state
        3. Logs final statistics
        """
        if self._is_running:
            try:
                traci.close()
            except Exception:
                pass
            self._is_running = False
            logger.info("SUMO simulation stopped after %d steps.", self._current_step)


    def step(self) -> bool:
        """Advance one simulation step.
        
        This method:
        1. Advances SUMO by one step
        2. Increments step counter
        3. Collects metrics
        4. Returns success/failure
        
        Returns:
            True if step succeeded, False if simulation ended or failed.
        """
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
        """Collect per-intersection metrics.
        
        For each intersection, collects:
        1. Queue length: Number of stopped vehicles on each approach
        2. Vehicle count: Total vehicles on each approach
        3. Wait time: Average wait time of vehicles on approaches
        4. Delay: Wait time + time loss
        5. Stops: Number of complete stops (speed < 0.1 m/s)
        
        Metrics are accumulated over time and averaged when requested.
        """
        for iid in self._intersections:
            m = self._metrics.per_intersection[iid]
            m.sample_count += 1

            # Queue length: vehicles with speed < 0.1 m/s
            queue_sum = 0
            for edge_id in self._approach_edges.get(iid, {}).values():
                try:
                    queue_sum += traci.edge.getLastStepHaltingNumber(edge_id)
                except Exception:
                    pass
            m.total_queue_length += queue_sum

            # Vehicle count: all vehicles on approach edges
            veh_sum = 0
            for edge_id in self._approach_edges.get(iid, {}).values():
                try:
                    veh_sum += traci.edge.getLastStepVehicleNumber(edge_id)
                except Exception:
                    pass
            m.total_vehicle_count += veh_sum

            # Wait time and delay: from individual vehicles
            wait_sum = 0.0
            delay_sum = 0.0
            stops_sum = 0
            count = 0
            for edge_id in self._approach_edges.get(iid, {}).values():
                try:
                    for vid in traci.edge.getLastStepVehicleIDs(edge_id):
                        wait_sum += traci.vehicle.getWaitingTime(vid)
                        # Delay = waiting time + time loss (approximate)
                        delay_sum += traci.vehicle.getAccumulatedWaitingTime(vid)
                        # Count stops (speed < 0.1 m/s)
                        if traci.vehicle.getSpeed(vid) < 0.1:
                            stops_sum += 1
                        count += 1
                except Exception:
                    pass
            
            # Update metrics (avoid division by zero)
            m.total_wait_time += (wait_sum / count if count else 0)
            m.total_delay += (delay_sum / count if count else 0)
            m.total_stops += stops_sum

        # Update global metrics
        self._metrics.total_steps = self._current_step
        try:
            self._metrics.vehicles_departed += traci.simulation.getDepartedNumber()
            self._metrics.vehicles_arrived += traci.simulation.getArrivedNumber()
        except Exception:
            pass


    # ========================================================================
    # Signal Control Methods
    # ========================================================================
    def set_signal_program(self, intersection_id: str, program_id: int):
        """Switch an intersection to a named signal program.
        
        Args:
            intersection_id: ID of the traffic light intersection.
            program_id: The program ID to activate.
        
        Raises:
            RuntimeError: If the simulation is not running.
            ValueError: If the intersection_id is unknown.
        """
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
        """Set a specific phase and duration on an intersection.
        
        This is the primary method for controlling signal timing:
        - phase_index: Which phase to activate (0=NS green, 2=EW green)
        - duration: How long to hold this phase (in seconds)
        
        Args:
            intersection_id: ID of the traffic light intersection.
            phase_index: Phase index to activate.
            duration: Duration of the phase in seconds.
        
        Raises:
            RuntimeError: If the simulation is not running.
        """
        if not self._is_running:
            raise RuntimeError("Simulation is not running.")
        try:
            traci.trafficlight.setPhase(intersection_id, phase_index)
            traci.trafficlight.setPhaseDuration(intersection_id, duration)
        except Exception as e:
            logger.error(f"Error setting phase on {intersection_id}: {e}")
            raise


    def get_signal_state(self, intersection_id: str) -> Dict:
        """Return current signal state for one intersection.
        
        Args:
            intersection_id: ID of the traffic light intersection.
        
        Returns:
            Dict with 'intersection', 'program', 'phase', and 'state' keys.
        """
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
        """Return signal state for every discovered intersection.
        
        Returns:
            List of signal state dicts, one per intersection.
        """
        return [self.get_signal_state(iid) for iid in self._intersections]


    # ========================================================================
    # Data Retrieval Methods
    # ========================================================================
    def get_queue_lengths(self, intersection_id: str) -> Dict[str, int]:
        """Return queue length (halting vehicles) per approach for one intersection.
        
        Queue length = number of vehicles with speed < 0.1 m/s
        
        Args:
            intersection_id: ID of the traffic light intersection.
        
        Returns:
            Dict mapping direction name to number of halting vehicles.
        """
        result = {}
        for direction, edge_id in self._approach_edges.get(intersection_id, {}).items():
            try:
                result[direction] = traci.edge.getLastStepHaltingNumber(edge_id)
            except Exception:
                result[direction] = 0
        return result


    def get_vehicle_counts(self, intersection_id: str) -> Dict[str, int]:
        """Return vehicle count per approach for one intersection.
        
        Vehicle count = total vehicles on each approach edge
        
        Args:
            intersection_id: ID of the traffic light intersection.
        
        Returns:
            Dict mapping direction name to number of vehicles on that approach.
        """
        result = {}
        for direction, edge_id in self._approach_edges.get(intersection_id, {}).items():
            try:
                result[direction] = traci.edge.getLastStepVehicleNumber(edge_id)
            except Exception:
                result[direction] = 0
        return result


    def get_all_queue_lengths(self) -> Dict[str, Dict[str, int]]:
        """Return queue lengths for every discovered intersection.
        
        Returns:
            Dict mapping intersection ID to its queue-length dict.
        """
        return {iid: self.get_queue_lengths(iid) for iid in self._intersections}


    def get_all_vehicle_counts(self) -> Dict[str, Dict[str, int]]:
        """Return vehicle counts for every discovered intersection.
        
        Returns:
            Dict mapping intersection ID to its vehicle-count dict.
        """
        return {iid: self.get_vehicle_counts(iid) for iid in self._intersections}


    def get_total_vehicles(self) -> int:
        """Return the total number of vehicles currently in the simulation.
        
        Returns:
            Vehicle count, or 0 if the simulation is not running.
        """
        try:
            return traci.vehicle.getIDCount()
        except Exception:
            return 0


    # ========================================================================
    # Properties
    # ========================================================================
    @property
    def intersections(self) -> List[str]:
        """List of discovered traffic light intersection IDs."""
        return list(self._intersections)

    @property
    def approach_edges(self) -> Dict[str, Dict[str, str]]:
        """Mapping of intersection ID to {direction: edge_id} dict."""
        return dict(self._approach_edges)

    @property
    def metrics(self) -> SimulationMetrics:
        """Aggregate simulation metrics collected so far."""
        return self._metrics

    @property
    def simulation_time(self) -> float:
        """Current simulation time in seconds."""
        try:
            return traci.simulation.getTime()
        except Exception:
            return self._current_step * self._step_length

    @property
    def current_step(self) -> int:
        """Number of simulation steps completed."""
        return self._current_step


    # ========================================================================
    # Snapshot Method
    # ========================================================================
    def get_snapshot(self) -> Dict:
        """Return a comprehensive snapshot of the current simulation state.
        
        This method collects:
        1. Current simulation time
        2. Queue lengths for all intersections
        3. Vehicle counts for all intersections
        4. Signal states for all intersections
        5. Aggregate metrics
        
        Returns:
            Dict with complete simulation state.
        """
        return {
            "time": self.simulation_time,
            "step": self._current_step,
            "queues": self.get_all_queue_lengths(),
            "vehicles": self.get_all_vehicle_counts(),
            "signals": self.get_all_signal_states(),
            "metrics": self._metrics.summary(),
        }
