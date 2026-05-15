"""
Webster's Formula for Optimal Signal Timing

This module implements Webster's formula, a classical traffic engineering method
for computing optimal signal timing based on traffic flow.

What is Webster's Formula?
==========================
Webster's formula computes the optimal cycle length that minimizes total delay:

    C_opt = (1.5L + 5) / (1 - ΣYi)

Where:
- C_opt: Optimal cycle length (seconds)
- L: Total lost time (sum of yellow/clearance phases)
- Yi: Critical flow ratio for phase i (flow / saturation_flow)
- ΣYi: Sum of all critical flow ratios

Why Webster's Formula?
======================
1. **Theoretically grounded**: Based on queuing theory
2. **Widely used**: Standard in traffic engineering
3. **Simple to compute**: Easy to implement and understand
4. **Good baseline**: Strong performance in moderate traffic

Limitations:
============
1. **Local optimization**: Only considers one intersection at a time
2. **Static**: Doesn't adapt to changing traffic patterns
3. **Assumes uniform arrivals**: May not hold in real traffic

Author: Yihao Tang
Date: 2024
"""

from typing import Dict, List


class WebsterController:
    """Compute optimal signal timing using Webster's formula.
    
    This controller implements Webster's formula for signal timing optimization.
    It's used as a baseline to compare against our LLM-based approach.
    
    Algorithm:
    1. Compute critical flow ratios: Yi = flow_i / saturation_flow
    2. Sum all flow ratios: ΣYi
    3. Compute optimal cycle length: C = (1.5L + 5) / (1 - ΣYi)
    4. Distribute green time proportional to flow ratios
    5. Apply min/max constraints
    
    Usage:
        controller = WebsterController()
        
        # Compute timing for two phases
        timings = controller.compute_timing({
            "EW": 800,  # East-West flow (vehicles/hour)
            "NS": 600,  # North-South flow (vehicles/hour)
        })
        # Returns: [35, 28] (EW=35s, NS=28s)
    """

    def compute_timing(
        self,
        phase_flows: Dict[str, float],
        saturation_flow: float = 1800,
        min_green: int = 10,
        max_green: int = 60,
        yellow_time: int = 3,
    ) -> List[int]:
        """Compute green durations for each phase using Webster's formula.
        
        Args:
            phase_flows: dict mapping phase name -> flow (veh/hr)
                        e.g. {"EW": 800, "NS": 600}
            saturation_flow: saturation flow rate per phase (veh/hr), default 1800
                            This is the maximum flow a phase can handle
            min_green: minimum green time per phase (seconds)
            max_green: maximum green time per phase (seconds)
            yellow_time: yellow/clearance time per phase (seconds)
        
        Returns:
            List of green durations (int, seconds), one per phase in dict order.
            Example: [35, 28] for {"EW": 800, "NS": 600}
        
        Raises:
            None (handles edge cases gracefully)
        """
        if not phase_flows:
            return []

        phases = list(phase_flows.keys())
        n = len(phases)

        # Step 1: Compute critical flow ratios Yi = flow_i / saturation_flow
        # Flow ratio represents how much of the phase's capacity is being used
        flow_ratios = {}
        for name, flow in phase_flows.items():
            flow_ratios[name] = max(0.0, flow / saturation_flow)

        # Step 2: Sum of all flow ratios
        # If ΣYi >= 1.0, the intersection is oversaturated
        y_total = sum(flow_ratios.values())

        # Step 3: Total lost time: one yellow interval per phase
        L = n * yellow_time

        # Step 4: Webster's optimal cycle length
        if y_total >= 1.0:
            # Oversaturated: use max cycle with all phases at max_green
            cycle_opt = 180.0
        else:
            denominator = 1.0 - y_total
            if denominator <= 0.0:
                cycle_opt = 180.0
            else:
                # Webster's formula: C_opt = (1.5L + 5) / (1 - ΣYi)
                cycle_opt = (1.5 * L + 5.0) / denominator

        # Step 5: Clamp cycle length to reasonable bounds
        min_cycle = n * (min_green + yellow_time)
        max_cycle = n * (max_green + yellow_time)
        cycle_opt = max(min_cycle, min(cycle_opt, max_cycle))

        # Step 6: Effective green = cycle - total yellow
        total_green = cycle_opt - (n * yellow_time)

        # Step 7: Distribute green time proportional to flow ratios
        if y_total > 0:
            greens = []
            raw_greens = []
            for name in phases:
                yi = flow_ratios[name]
                raw = (yi / y_total) * total_green
                raw_greens.append(raw)

            # Apply min/max constraints iteratively
            remaining = total_green
            fixed = [False] * n
            greens = [0.0] * n

            # First pass: clamp
            for i in range(n):
                greens[i] = raw_greens[i]

            # Iterative rebalancing to respect min/max
            # This ensures all phases get at least min_green
            for _ in range(10):
                free_sum = 0.0
                fixed_count = 0
                for i in range(n):
                    if greens[i] < min_green:
                        greens[i] = min_green
                        fixed[i] = True
                    elif greens[i] > max_green:
                        greens[i] = max_green
                        fixed[i] = True

                    if fixed[i]:
                        fixed_count += 1
                    else:
                        free_sum += greens[i]

                if fixed_count == n:
                    break

                remaining = total_green - sum(
                    greens[i] for i in range(n) if fixed[i]
                )

                if free_sum > 0 and remaining > 0:
                    scale = remaining / free_sum
                    for i in range(n):
                        if not fixed[i]:
                            greens[i] *= scale
                elif remaining > 0:
                    # Distribute remaining equally among unfixed phases
                    unfixed = [i for i in range(n) if not fixed[i]]
                    if unfixed:
                        share = remaining / len(unfixed)
                        for i in unfixed:
                            greens[i] = share
        else:
            # No traffic: distribute equally
            greens = [total_green / n] * n

        # Step 8: Final clamp and round
        result = []
        for g in greens:
            g = max(min_green, min(max_green, round(g)))
            result.append(g)

        return result


def compute_timing_for_intersection(
    flows: Dict[str, float],
    saturation_flow: float = 1800,
    min_green: int = 10,
    max_green: int = 60,
    yellow_time: int = 3,
) -> List[int]:
    """Compute optimal signal timing using Webster's formula (convenience wrapper).
    
    This is a convenience function that creates a WebsterController instance
    and computes timing in one call.
    
    Args:
        flows: Dict mapping phase name to flow rate in veh/hr.
              Example: {"EW": 800, "NS": 600}
        saturation_flow: Saturation flow rate per phase (veh/hr).
                        Default 1800 (standard value for urban intersections)
        min_green: Minimum green time per phase (seconds).
                  Default 10 (pedestrian safety)
        max_green: Maximum green time per phase (seconds).
                  Default 60 (prevent starvation)
        yellow_time: Yellow/clearance time per phase (seconds).
                    Default 3 (standard traffic engineering value)
    
    Returns:
        List of green durations (int, seconds), one per phase in dict order.
        Example: [35, 28] for {"EW": 800, "NS": 600}
    """
    ctrl = WebsterController()
    return ctrl.compute_timing(flows, saturation_flow, min_green, max_green, yellow_time)
