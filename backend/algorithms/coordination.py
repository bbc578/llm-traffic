"""
Upstream-downstream coordination for multi-intersection signal control.

Detects queue spillover from upstream intersections and adjusts downstream
green times to prevent congestion propagation.

In a 3×2 grid:
  A1  B1  C1
  A0  B0  C0

Horizontal flows: A0→B0→C0, A1→B1→C1
Vertical flows:   A0↔A1, B0↔B1, C0↔C1
"""
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Network topology (auto-derived from SUMO controlled links) ───────────────
# Direction mapping: which edge goes where
# For each intersection, maps upstream intersection → arrival direction
# e.g., A0's east neighbor is B0, so B0 receives eastbound traffic from A0

# Adjacency: intersection → {direction: neighbor_intersection_id}
GRID6_NEIGHBORS: Dict[str, Dict[str, str]] = {
    "A0": {"east": "B0", "north": "A1"},
    "A1": {"east": "B1", "south": "A0"},
    "B0": {"east": "C0", "west": "A0", "north": "B1"},
    "B1": {"east": "C1", "west": "A1", "south": "B0"},
    "C0": {"west": "B0", "north": "C1"},
    "C1": {"west": "B1", "south": "C0"},
}

# For each intersection, which upstream intersections feed into it,
# and from which direction the traffic arrives.
# {intersection: [(upstream_id, arrival_direction), ...]}
GRID6_UPSTREAM: Dict[str, List[Tuple[str, str]]] = {
    "A0": [("A1", "north")],           # A1's southbound traffic arrives at A0's north
    "A1": [("A0", "south")],           # A0's northbound traffic arrives at A1's south
    "B0": [("A0", "west"), ("B1", "north")],
    "B1": [("A1", "west"), ("B0", "south")],
    "C0": [("B0", "west"), ("C1", "north")],
    "C1": [("B1", "west"), ("C0", "south")],
}

# Direction pairs: if upstream has queue in direction X, downstream should
# prioritize direction Y
DIRECTION_PAIR = {
    "east": "west",    # upstream eastbound → downstream should serve westbound (incoming)
    "west": "east",
    "north": "south",
    "south": "north",
}


class CoordinationEngine:
    """
    Implements upstream-downstream queue-based signal coordination.

    Logic:
    1. At each decision step, collect queue lengths from all intersections
    2. For each intersection, check its upstream neighbors
    3. If an upstream has queue > threshold in a direction flowing here,
       boost the green time for that direction at this intersection
    4. If upstream queue is critical, trigger a phase switch
    """

    def __init__(
        self,
        queue_threshold: int = 5,       # queue length to trigger coordination
        critical_threshold: int = 12,   # queue length to force phase switch
        boost_seconds: int = 10,        # extra green seconds per coordination trigger
        max_boost: int = 25,            # max total boost per cycle
    ):
        self.queue_threshold = queue_threshold
        self.critical_threshold = critical_threshold
        self.boost_seconds = boost_seconds
        self.max_boost = max_boost

    def compute_adjustments(
        self,
        all_queues: Dict[str, Dict[str, int]],
        current_phases: Dict[str, int],
    ) -> Dict[str, Dict]:
        """
        Compute signal timing adjustments for all intersections.

        Args:
            all_queues: {intersection_id: {"north": N, "south": N, "east": N, "west": N}}
            current_phases: {intersection_id: phase_number}

        Returns:
            {intersection_id: {
                "boost_ns": int,      # extra seconds for NS green
                "boost_ew": int,      # extra seconds for EW green
                "force_phase": int or None,  # force switch to this phase if critical
                "reason": str,
            }}
        """
        adjustments = {}

        for iid in all_queues:
            neighbors = GRID6_NEIGHBORS.get(iid, {})
            upstream_list = GRID6_UPSTREAM.get(iid, [])

            boost_ns = 0
            boost_ew = 0
            force_phase = None
            reasons = []

            for upstream_id, arrival_dir in upstream_list:
                if upstream_id not in all_queues:
                    continue

                upstream_q = all_queues[upstream_id]
                # The upstream direction that feeds into this intersection
                # e.g., upstream=A0, arrival_dir="west" → A0's eastbound queue matters
                feed_dir = self._reverse_dir(arrival_dir)
                queue_len = upstream_q.get(feed_dir, 0)

                if queue_len >= self.critical_threshold:
                    # Critical: force phase switch to serve incoming traffic
                    if arrival_dir in ("north", "south"):
                        force_phase = 0  # NS green
                        reasons.append(f"{upstream_id}.{feed_dir}={queue_len} CRITICAL→force NS")
                    else:
                        force_phase = 2  # EW green
                        reasons.append(f"{upstream_id}.{feed_dir}={queue_len} CRITICAL→force EW")

                elif queue_len >= self.queue_threshold:
                    # Moderate: boost green time
                    if arrival_dir in ("north", "south"):
                        boost_ns += self.boost_seconds
                        reasons.append(f"{upstream_id}.{feed_dir}={queue_len}→+{self.boost_seconds}s NS")
                    else:
                        boost_ew += self.boost_seconds
                        reasons.append(f"{upstream_id}.{feed_dir}={queue_len}→+{self.boost_seconds}s EW")

            # Clamp boosts
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
        """
        Apply coordination adjustments to base signal timings.

        Args:
            base_timings: {intersection_id: {phase: duration_seconds}}
            adjustments: output from compute_adjustments()

        Returns:
            Adjusted timings in same format
        """
        result = {}

        for iid, base in base_timings.items():
            adj = adjustments.get(iid, {})
            adjusted = dict(base)

            # Phase 0 = NS green, Phase 1 = NS yellow, Phase 2 = EW green, Phase 3 = EW yellow
            boost_ns = adj.get("boost_ns", 0)
            boost_ew = adj.get("boost_ew", 0)

            if boost_ns > 0:
                adjusted[0] = min(90, adjusted.get(0, 30) + boost_ns)
            if boost_ew > 0:
                adjusted[2] = min(90, adjusted.get(2, 30) + boost_ew)

            # Force phase override
            force = adj.get("force_phase")
            if force is not None:
                if force == 0:
                    adjusted[0] = max(adjusted.get(0, 30), 45)
                elif force == 2:
                    adjusted[2] = max(adjusted.get(2, 30), 45)

            result[iid] = adjusted

        return result

    @staticmethod
    def _reverse_dir(d: str) -> str:
        return {"north": "south", "south": "north", "east": "west", "west": "east"}.get(d, d)
