"""
Upstream-Downstream Coordination for Multi-Intersection Signal Control

This module implements queue-based signal coordination between neighboring
intersections. It detects queue spillover from upstream intersections and
adjusts downstream green times to prevent congestion propagation.

Why Coordination?
=================
Independent intersection control causes problems:
- A0 gets green, vehicles flow to B0
- B0 is still red, queue builds up
- Queue spills back to A0, blocking it
- Cascading congestion across the network

Solution: Coordinate signals so downstream intersections
are ready to receive traffic from upstream.

How It Works:
=============
1. Monitor queue lengths at all intersections
2. For each intersection, check its upstream neighbors
3. If upstream queue > threshold in a direction flowing here:
   - Boost green time for that direction at this intersection
4. If upstream queue > critical_threshold:
   - Force phase switch to prevent spillback

Example:
========
A0 (upstream) has 15 vehicles eastbound
→ B0 (downstream) increases westbound green by 10s
→ Prevents queue from spilling from A0 to B0

Network Topology (3×2 grid):
============================
  A1  B1  C1
  A0  B0  C0

Horizontal flows: A0→B0→C0, A1→B1→C1
Vertical flows:   A0↔A1, B0↔B1, C0↔C1

Author: Yihao Tang
Date: 2024
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Network Topology (auto-derived from SUMO controlled links)
# ============================================================================
# Adjacency: intersection → {direction: neighbor_intersection_id}
# This maps each intersection to its neighbors in each direction
GRID6_NEIGHBORS: Dict[str, Dict[str, str]] = {
    "A0": {"east": "B0", "north": "A1"},
    "A1": {"east": "B1", "south": "A0"},
    "B0": {"east": "C0", "west": "A0", "north": "B1"},
    "B1": {"east": "C1", "west": "A1", "south": "B0"},
    "C0": {"west": "B0", "north": "C1"},
    "C1": {"west": "B1", "south": "C0"},
}

# Upstream mapping: which intersections feed into this one
# {intersection: [(upstream_id, arrival_direction), ...]}
# Example: B0 receives traffic from A0 (westbound) and B1 (southbound)
GRID6_UPSTREAM: Dict[str, List[Tuple[str, str]]] = {
    "A0": [("A1", "north")],           # A1's southbound traffic arrives at A0's north
    "A1": [("A0", "south")],           # A0's northbound traffic arrives at A1's south
    "B0": [("A0", "west"), ("B1", "north")],  # A0 eastbound + B1 southbound
    "B1": [("A1", "west"), ("B0", "south")],  # A1 eastbound + B0 northbound
    "C0": [("B0", "west"), ("C1", "north")],  # B0 eastbound + C1 southbound
    "C1": [("B1", "west"), ("C0", "south")],  # B1 eastbound + C0 northbound
}

# Direction pairs: if upstream has queue in direction X, downstream should
# prioritize direction Y
# Example: upstream has eastbound queue → downstream should serve westbound (incoming)
DIRECTION_PAIR = {
    "east": "west",    # upstream eastbound → downstream should serve westbound
    "west": "east",
    "north": "south",
    "south": "north",
}


class CoordinationEngine:
    """Implements upstream-downstream queue-based signal coordination.
    
    This engine detects when upstream intersections have large queues
    and adjusts downstream signals to prevent congestion propagation.
    
    Algorithm:
    1. At each decision step, collect queue lengths from all intersections
    2. For each intersection, check its upstream neighbors
    3. If an upstream has queue > threshold in a direction flowing here,
       boost the green time for that direction at this intersection
    4. If upstream queue is critical, trigger a phase switch
    
    Parameters:
    - queue_threshold: 5 vehicles (trigger coordination)
    - critical_threshold: 12 vehicles (force phase switch)
    - boost_seconds: 10s (extra green per trigger)
    - max_boost: 25s (maximum boost per cycle)
    
    Usage:
        engine = CoordinationEngine()
        
        # Get current queue lengths
        all_queues = {
            "A0": {"east": 5, "west": 3, "north": 8, "south": 2},
            "B0": {"east": 2, "west": 15, "north": 4, "south": 1},
            ...
        }
        
        # Compute adjustments
        adjustments = engine.compute_adjustments(all_queues, {})
        
        # Apply to base timings
        adjusted = engine.apply_adjustments(base_timings, adjustments)
    """

    def __init__(
        self,
        queue_threshold: int = 5,       # queue length to trigger coordination
        critical_threshold: int = 12,   # queue length to force phase switch
        boost_seconds: int = 10,        # extra green seconds per coordination trigger
        max_boost: int = 25,            # max total boost per cycle
    ):
        """Initialize the coordination engine with tuning parameters.
        
        Args:
            queue_threshold: Minimum queue length to trigger green time boost.
                            Why 5? Small queues don't need coordination.
            critical_threshold: Queue length that forces an immediate phase switch.
                               Why 12? Prevents queue spillback.
            boost_seconds: Extra green seconds added per coordination trigger.
                          Why 10? Enough to clear 2-3 vehicles per cycle.
            max_boost: Maximum total boost seconds allowed per cycle.
                      Why 25? Prevents excessive green time for one direction.
        """
        self.queue_threshold = queue_threshold
        self.critical_threshold = critical_threshold
        self.boost_seconds = boost_seconds
        self.max_boost = max_boost

    def compute_adjustments(
        self,
        all_queues: Dict[str, Dict[str, int]],
        current_phases: Dict[str, int],
    ) -> Dict[str, Dict]:
        """Compute signal timing adjustments for all intersections.
        
        For each intersection, checks upstream neighbors and determines:
        1. How much to boost NS green time
        2. How much to boost EW green time
        3. Whether to force a phase switch
        
        Args:
            all_queues: {intersection_id: {"north": N, "south": N, "east": N, "west": N}}
            current_phases: {intersection_id: phase_number}
        
        Returns:
            {intersection_id: {
                "boost_ns": int,      # extra seconds for NS green
                "boost_ew": int,      # extra seconds for EW green
                "force_phase": int or None,  # force switch to this phase if critical
                "reason": str,        # human-readable explanation
            }}
        
        Example:
            all_queues = {
                "A0": {"east": 15, ...},  # 15 vehicles eastbound (critical!)
                "B0": {"west": 3, ...},
            }
            adjustments = engine.compute_adjustments(all_queues, {})
            # B0 gets boost_ew = 10 (to absorb A0's eastbound traffic)
        """
        adjustments = {}

        for iid in all_queues:
            neighbors = GRID6_NEIGHBORS.get(iid, {})
            upstream_list = GRID6_UPSTREAM.get(iid, [])

            boost_ns = 0
            boost_ew = 0
            force_phase = None
            reasons = []

            # Check each upstream intersection
            for upstream_id, arrival_dir in upstream_list:
                if upstream_id not in all_queues:
                    continue

                upstream_q = all_queues[upstream_id]
                
                # The upstream direction that feeds into this intersection
                # Example: upstream=A0, arrival_dir="west" → A0's eastbound queue matters
                feed_dir = self._reverse_dir(arrival_dir)
                queue_len = upstream_q.get(feed_dir, 0)

                # Critical threshold: force phase switch
                if queue_len >= self.critical_threshold:
                    if arrival_dir in ("north", "south"):
                        force_phase = 0  # NS green
                        reasons.append(f"{upstream_id}.{feed_dir}={queue_len} CRITICAL→force NS")
                    else:
                        force_phase = 2  # EW green
                        reasons.append(f"{upstream_id}.{feed_dir}={queue_len} CRITICAL→force EW")

                # Moderate threshold: boost green time
                elif queue_len >= self.queue_threshold:
                    if arrival_dir in ("north", "south"):
                        boost_ns += self.boost_seconds
                        reasons.append(f"{upstream_id}.{feed_dir}={queue_len}→+{self.boost_seconds}s NS")
                    else:
                        boost_ew += self.boost_seconds
                        reasons.append(f"{upstream_id}.{feed_dir}={queue_len}→+{self.boost_seconds}s EW")

            # Clamp boosts to maximum
            boost_ns = min(boost_ns, self.max_boost)
            boost_ew = min(boost_ew, self.max_boost)

            adjustments[iid] = {
                "boost_ns": boost_ns,
                "boost_ew": boost_ew,
                "force_phase": force_phase,
                "reason": "; ".join(reasons) if reasons else "no coordination needed",
            }

        return adjustments

    def apply_adjustments(
        self,
        base_timings: Dict[str, Dict[int, int]],
        adjustments: Dict[str, Dict],
    ) -> Dict[str, Dict[int, int]]:
        """Apply coordination adjustments to base signal timings.
        
        This method:
        1. Takes base timings (from LLM or Webster)
        2. Adds boost from coordination engine
        3. Forces phase switch if critical
        4. Clamps to safe limits
        
        Args:
            base_timings: {intersection_id: {phase: duration_seconds}}
                         Example: {"A0": {0: 30, 1: 3, 2: 25, 3: 3}}
            adjustments: output from compute_adjustments()
        
        Returns:
            Adjusted timings in same format
        
        Example:
            base = {"B0": {0: 30, 1: 3, 2: 25, 3: 3}}
            adj = {"B0": {"boost_ew": 10, ...}}
            result = engine.apply_adjustments(base, adj)
            # result = {"B0": {0: 30, 1: 3, 2: 35, 3: 3}}  (EW boosted by 10s)
        """
        result = {}

        for iid, base in base_timings.items():
            adj = adjustments.get(iid, {})
            adjusted = dict(base)

            # Phase 0 = NS green, Phase 1 = NS yellow
            # Phase 2 = EW green, Phase 3 = EW yellow
            boost_ns = adj.get("boost_ns", 0)
            boost_ew = adj.get("boost_ew", 0)

            # Apply NS boost (clamped to 90s max)
            if boost_ns > 0:
                adjusted[0] = min(90, adjusted.get(0, 30) + boost_ns)
            
            # Apply EW boost (clamped to 90s max)
            if boost_ew > 0:
                adjusted[2] = min(90, adjusted.get(2, 30) + boost_ew)

            # Force phase override for critical situations
            force = adj.get("force_phase")
            if force is not None:
                if force == 0:
                    # Force NS green (minimum 45s for critical)
                    adjusted[0] = max(adjusted.get(0, 30), 45)
                elif force == 2:
                    # Force EW green (minimum 45s for critical)
                    adjusted[2] = max(adjusted.get(2, 30), 45)

            result[iid] = adjusted

        return result

    @staticmethod
    def _reverse_dir(d: str) -> str:
        """Return the opposite compass direction.
        
        Args:
            d: A compass direction string ('north', 'south', 'east', 'west').
        
        Returns:
            The opposite direction, or the input if unrecognized.
        
        Example:
            _reverse_dir("east") → "west"
            _reverse_dir("north") → "south"
        """
        return {"north": "south", "south": "north", "east": "west", "west": "east"}.get(d, d)
