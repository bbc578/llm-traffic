"""
Webster's formula for optimal signal timing.

Formula: C_opt = (1.5*L + 5) / (1 - sum(Yi))
where:
  L = total lost time (sum of yellow/clearance phases)
  Yi = critical flow ratio for phase i (flow / saturation_flow)
"""

from typing import Dict, List


class WebsterController:
    """Compute optimal signal timing using Webster's formula."""

    def compute_timing(
        self,
        phase_flows: Dict[str, float],
        saturation_flow: float = 1800,
        min_green: int = 10,
        max_green: int = 60,
        yellow_time: int = 3,
    ) -> List[int]:
        """
        Compute green durations for each phase using Webster's formula.

        Args:
            phase_flows: dict mapping phase name -> flow (veh/hr)
                         e.g. {"north_south": 800, "east_west": 600}
            saturation_flow: saturation flow rate per phase (veh/hr), default 1800
            min_green: minimum green time per phase (seconds)
            max_green: maximum green time per phase (seconds)
            yellow_time: yellow/clearance time per phase (seconds)

        Returns:
            List of green durations (int, seconds), one per phase in dict order.
        """
        if not phase_flows:
            return []

        phases = list(phase_flows.keys())
        n = len(phases)

        # Compute critical flow ratios Yi = flow_i / saturation_flow
        flow_ratios = {}
        for name, flow in phase_flows.items():
            flow_ratios[name] = max(0.0, flow / saturation_flow)

        # Sum of all flow ratios
        y_total = sum(flow_ratios.values())

        # Total lost time: one yellow interval per phase
        L = n * yellow_time

        # Webster's optimal cycle length
        if y_total >= 1.0:
            # Oversaturated: use max cycle with all phases at max_green
            cycle_opt = 180.0
        else:
            denominator = 1.0 - y_total
            if denominator <= 0.0:
                cycle_opt = 180.0
            else:
                cycle_opt = (1.5 * L + 5.0) / denominator

        # Clamp cycle length to reasonable bounds
        min_cycle = n * (min_green + yellow_time)
        max_cycle = n * (max_green + yellow_time)
        cycle_opt = max(min_cycle, min(cycle_opt, max_cycle))

        # Effective green = cycle - total yellow
        total_green = cycle_opt - (n * yellow_time)

        # Distribute green time proportional to flow ratios
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

        # Final clamp and round
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

    Args:
        flows: Dict mapping phase name to flow rate in veh/hr.
        saturation_flow: Saturation flow rate per phase (veh/hr).
        min_green: Minimum green time per phase (seconds).
        max_green: Maximum green time per phase (seconds).
        yellow_time: Yellow/clearance time per phase (seconds).

    Returns:
        List of green durations (int, seconds), one per phase in dict order.
    """
    ctrl = WebsterController()
    return ctrl.compute_timing(flows, saturation_flow, min_green, max_green, yellow_time)
