# 🏗️ LLM-Traffic Architecture Deep Dive

This document provides a comprehensive technical analysis of the LLM-Traffic system architecture, explaining every design decision and its rationale.

## Table of Contents

1. [System Overview](#system-overview)
2. [Multi-Process Architecture](#multi-process-architecture)
3. [Data Flow Pipeline](#data-flow-pipeline)
4. [Component Deep Dive](#component-deep-dive)
5. [Design Patterns](#design-patterns)
6. [Performance Considerations](#performance-considerations)

---

## System Overview

### Why This Architecture?

The LLM-Traffic system is designed around three core principles:

1. **Safety First**: No LLM decision can violate traffic safety rules
2. **Real-time Performance**: Decisions must be made within control intervals
3. **Fault Tolerance**: System continues operating even if LLM fails

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │   REST API      │  │  WebSocket      │  │  Background     │    │
│  │   Endpoints     │  │  Server         │  │  Tasks          │    │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘    │
│           │                    │                     │              │
│           └────────────────────┼─────────────────────┘              │
│                                │                                    │
│  ┌─────────────────────────────▼───────────────────────────────┐   │
│  │                    Process Manager                           │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │   │
│  │  │ State Queue │    │ Stop Event  │    │ Lock        │     │   │
│  │  │ (mp.Queue)  │    │ (mp.Event)  │    │ (threading) │     │   │
│  │  └─────────────┘    └─────────────┘    └─────────────┘     │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Simulation Process                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      SUMO Engine                            │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │   │
│  │  │ TraCI       │    │ Traffic     │    │ Metrics     │     │   │
│  │  │ Connection  │    │ Lights      │    │ Collection  │     │   │
│  │  └─────────────┘    └─────────────┘    └─────────────┘     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Decision Pipeline                         │   │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐              │   │
│  │  │ LLM      │───▶│ Coord    │───▶│ Constr   │              │   │
│  │  │ Client   │    │ Engine   │    │ Engine   │              │   │
│  │  └──────────┘    └──────────┘    └──────────┘              │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Multi-Process Architecture

### The Problem

SUMO's TraCI library uses TCP sockets for communication. This creates several challenges:

1. **Thread Safety**: TraCI sockets are not thread-safe
2. **Event Loop Conflict**: SUMO's event loop conflicts with uvicorn's async loop
3. **Crash Isolation**: SUMO crashes shouldn't take down the API server

### The Solution: Process Isolation

We run SUMO in a dedicated subprocess using Python's `multiprocessing` module:

```python
def _sim_process_fn(cfg: dict, state_queue: mp.Queue, stop_event: mp.Event):
    """Simulation process target.
    
    Architecture:
    - Main Process: FastAPI server + WebSocket handling
    - Child Process: SUMO simulation + LLM decisions
    
    Communication:
    - state_queue: Child → Main (push simulation snapshots)
    - stop_event: Main → Child (signal termination)
    """
```

### Why Not Threads?

```python
# ❌ Thread-based (problematic)
import threading
def run_simulation():
    import traci  # TraCI uses global state
    traci.start(...)  # Not thread-safe!

# ✅ Process-based (our approach)
import multiprocessing
def _sim_process_fn(cfg, state_queue, stop_event):
    import traci  # Each process has its own TraCI instance
    traci.start(...)  # Safe!
```

### Inter-Process Communication

We use `multiprocessing.Queue` for state transfer:

```python
# Main Process
_state_queue = mp.Queue(maxsize=500)

# Child Process pushes snapshots
state_queue.put({
    "time": current_time,
    "queues": queue_lengths,
    "vehicles": vehicle_counts,
    "is_running": True
})

# Main Process reads snapshots
msg = _state_queue.get_nowait()
```

**Why maxsize=500?**
- Prevents memory exhaustion if main process is slow
- 500 snapshots ≈ 500 seconds of simulation data
- Old snapshots are dropped if queue is full (acceptable for real-time visualization)

---

## Data Flow Pipeline

### 1. Perception Layer

Collects traffic state from SUMO:

```python
def get_snapshot(self) -> Dict:
    """Collect comprehensive traffic state.
    
    Returns:
        {
            "time": float,                    # Simulation time
            "queues": Dict[str, Dict[str, int]],  # Per-intersection queue lengths
            "vehicles": Dict[str, Dict[str, int]], # Per-intersection vehicle counts
            "signals": List[Dict],            # Current signal states
            "metrics": Dict                   # Aggregated metrics
        }
    """
```

### 2. LLM Decision Layer

Sends state to LLM and receives recommendations:

```python
def get_batch_recommendation(self, all_states: Dict) -> Dict:
    """Get signal timing recommendations for all intersections.
    
    Why batch?
    - Reduces API calls from N to 1
    - LLM can consider network-wide effects
    - Lower latency and cost
    
    Input:
        {
            "A0": {"queue_lengths": {...}, "vehicle_counts": {...}},
            "B0": {"queue_lengths": {...}, "vehicle_counts": {...}},
            ...
        }
    
    Output:
        {
            "A0": {"phase_durations": {0: 30, 2: 45}},
            "B0": {"phase_durations": {0: 25, 2: 50}},
            ...
        }
    """
```

### 3. Coordination Layer

Adjusts timings based on upstream/downstream relationships:

```python
def compute_adjustments(self, all_queues, current_phases):
    """Compute coordination adjustments.
    
    Algorithm:
    1. For each intersection, identify upstream neighbors
    2. Check if upstream queue > threshold
    3. If yes, boost green time for incoming direction
    4. If upstream queue > critical_threshold, force phase switch
    
    Example:
        A0 eastbound queue = 15 vehicles
        → B0 westbound green += 10s
        → Prevents queue spillover from A0 to B0
    """
```

### 4. Constraint Validation Layer

Ensures all decisions are safe:

```python
def validate(self, green_phases, cycle_length):
    """Validate signal timing against safety constraints.
    
    Constraints:
    - min_green: 10s (pedestrian safety)
    - max_green: 60s (prevent starvation)
    - min_cycle: 30s (minimum complete cycle)
    - max_cycle: 180s (maximum for responsiveness)
    
    Returns:
        (valid, violations, corrected)
        - valid: True if all constraints pass
        - violations: List of violation descriptions
        - corrected: List of corrected durations
    """
```

---

## Component Deep Dive

### SumoEngine

The core simulation engine that interfaces with SUMO:

```python
class SumoEngine:
    """Network-agnostic SUMO simulation engine.
    
    Key Design Decisions:
    1. Auto-discovery: Automatically finds traffic lights in the network
    2. Direction mapping: Maps edges to compass directions (N/S/E/W)
    3. Metrics collection: Collects per-intersection statistics
    
    Why network-agnostic?
    - Works with any SUMO network (grid, real-world, synthetic)
    - No hardcoded intersection IDs
    - Easy to switch between test scenarios
    """
    
    def _discover_network(self):
        """Auto-discover traffic lights and their approach edges.
        
        Process:
        1. Get all traffic light IDs from SUMO
        2. For each TLS, find controlled links
        3. Map edges to compass directions using geometry
        4. Build approach_edges mapping
        
        Why compass directions?
        - Intuitive for LLM prompt construction
        - Consistent across different networks
        - Easy to understand for debugging
        """
```

### LLMClient

Handles communication with the LLM API:

```python
class LLMClient:
    """LLM API client with batch processing support.
    
    Features:
    1. Batch mode: Send all intersections in one prompt
    2. Response parsing: Handle multiple JSON formats
    3. Fallback mechanism: Use default timing if LLM fails
    4. Reasoning model support: Extract from reasoning_content
    
    Why batch mode?
    - Reduces API calls from N intersections to 1
    - LLM can consider network-wide effects
    - Lower latency and cost
    """
```

### SignalConstraintEngine

Validates and corrects LLM decisions:

```python
class SignalConstraintEngine:
    """Rule engine for signal timing validation.
    
    Design Philosophy:
    - Safety is non-negotiable
    - LLM decisions are suggestions, not commands
    - Constraint engine has final authority
    
    Constraints:
    - Physical: Min/max green times, cycle lengths
    - Safety: Pedestrian clearance, yellow intervals
    - Operational: Prevent starvation, ensure fairness
    """
```

### CoordinationEngine

Implements multi-intersection coordination:

```python
class CoordinationEngine:
    """Upstream-downstream queue-based coordination.
    
    Algorithm:
    1. Monitor queue lengths at all intersections
    2. For each intersection, check upstream neighbors
    3. If upstream queue > threshold:
       - Boost green time for incoming direction
    4. If upstream queue > critical_threshold:
       - Force phase switch to prevent spillback
    
    Parameters:
    - queue_threshold: 5 vehicles (trigger coordination)
    - critical_threshold: 12 vehicles (force phase switch)
    - boost_seconds: 10s (extra green per trigger)
    - max_boost: 25s (maximum boost per cycle)
    """
```

---

## Design Patterns

### 1. Strategy Pattern

All signal controllers implement the same interface:

```python
class BaseController(ABC):
    @abstractmethod
    def compute_timing(self, phase_flows: Dict[str, float]) -> List[int]:
        """Compute green durations for each phase."""
        pass

class FixedTimeController(BaseController):
    def compute_timing(self, phase_flows):
        # Equal green splits
        pass

class WebsterController(BaseController):
    def compute_timing(self, phase_flows):
        # Webster's formula
        pass

class LLMController(BaseController):
    def compute_timing(self, phase_flows):
        # LLM recommendation
        pass
```

### 2. Observer Pattern

WebSocket clients receive real-time updates:

```python
# Observer registration
ws_clients: List[WebSocket] = []

# Notify all observers
for ws in ws_clients:
    await ws.send_json(snapshot)
```

### 3. Producer-Consumer Pattern

Simulation process produces snapshots, main process consumes them:

```python
# Producer (simulation process)
state_queue.put(snapshot)

# Consumer (main process)
msg = state_queue.get_nowait()
```

### 4. Circuit Breaker Pattern

LLM failures don't crash the system:

```python
try:
    batch_result = llm_client.get_batch_recommendation(all_states)
except Exception as e:
    logger.warning("LLM failed: %s", e)
    # Fallback to default timing
    for iid in intersections:
        timing_cache[iid] = {0: 30, 1: 3, 2: 30, 3: 3}
```

---

## Performance Considerations

### 1. Batch Processing

**Problem**: N API calls per decision cycle
**Solution**: Batch all intersections into one prompt

```python
# Before: 6 API calls
for iid in intersections:
    decision = llm.get_recommendation(state[iid])  # 6 calls

# After: 1 API call
decisions = llm.get_batch_recommendation(all_states)  # 1 call
```

**Impact**: 6x reduction in API calls, lower latency

### 2. Queue Size Management

**Problem**: Memory exhaustion if main process is slow
**Solution**: Bounded queue with maxsize=500

```python
_state_queue = mp.Queue(maxsize=500)

# If queue is full, drop oldest snapshot
try:
    state_queue.put_nowait(snapshot)
except Exception:
    pass  # Drop snapshot
```

### 3. Lock Contention

**Problem**: Multiple threads accessing shared state
**Solution**: Fine-grained locking

```python
_latest_lock = threading.Lock()

# Only lock when updating/reading shared state
with _latest_lock:
    _latest.update(msg)
```

### 4. Process Cleanup

**Problem**: Zombie processes if simulation crashes
**Solution**: Daemon processes + explicit cleanup

```python
_sim_proc = mp.Process(
    target=_sim_process_fn,
    args=(...),
    daemon=True,  # Auto-terminate when main process exits
)

# Explicit cleanup on shutdown
_stop_event.set()
if _sim_proc and _sim_proc.is_alive():
    _sim_proc.join(timeout=5)
```

---

## Future Improvements

### 1. Distributed Architecture
- Deploy LLM inference on separate GPU cluster
- Use message queue (Redis/RabbitMQ) for communication

### 2. Caching Layer
- Cache LLM responses for similar traffic states
- Reduce API calls by 50-70%

### 3. Real-time Streaming
- Use Server-Sent Events (SSE) instead of polling
- Lower latency for frontend updates

### 4. Model Fine-tuning
- Fine-tune smaller model on traffic-specific data
- Reduce inference cost while maintaining quality
