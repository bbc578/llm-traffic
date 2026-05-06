"""
Baseline controllers for traffic signal timing.
- FixedTimeController: equal green splits for all phases
- RandomController: random green splits within constraints
"""

import random as rng
from typing import Dict, List


class FixedTimeController:
    """Distributes green time equally among all phases."""

    def __init__(self, cycle_length: int = 60, yellow_time: int = 3):
        self.cycle_length = cycle_length
        self.yellow_time = yellow_time

    def compute_timing(
        self,
        phase_flows: Dict[str, float] = None,
        saturation_flow: float = 1800,
        min_green: int = 10,
        max_green: int = 60,
        yellow_time: int = 3,
        num_phases: int = 2,
    ) -> List[int]:
        """
        Compute equal green durations for all phases.

        If phase_flows is provided, the number of phases is inferred from it.
        Otherwise num_phases is used.

        Args:
            phase_flows: optional dict of phase flows (used to count phases)
            saturation_flow: unused (for API compatibility)
            min_green: minimum green time per phase
            max_green: maximum green time per phase
            yellow_time: yellow time per phase
            num_phases: number of phases if phase_flows not given

        Returns:
            List of green durations (int, seconds)
        """
        if phase_flows is not None:
            n = len(phase_flows)
        else:
            n = num_phases

        if n == 0:
            return []

        total_yellow = n * yellow_time
        total_green = self.cycle_length - total_yellow
        green_per_phase = max(min_green, total_green // n)
        green_per_phase = min(max_green, green_per_phase)

        result = [green_per_phase] * n

        # Adjust last phase to account for rounding
        remainder = total_green - sum(result)
        if n > 0:
            result[-1] += remainder
            result[-1] = max(min_green, min(max_green, result[-1]))

        return result


class RandomController:
    """Generates random green splits within constraint bounds."""

    def __init__(self, cycle_length: int = 60, yellow_time: int = 3, seed: int = None):
        self.cycle_length = cycle_length
        self.yellow_time = yellow_time
        self._rng = rng.Random(seed)

    def compute_timing(
        self,
        phase_flows: Dict[str, float] = None,
        saturation_flow: float = 1800,
        min_green: int = 10,
        max_green: int = 60,
        yellow_time: int = 3,
        num_phases: int = 2,
    ) -> List[int]:
        """
        Compute random green durations within constraints.

        Each phase gets at least min_green, at most max_green,
        and total green + yellow = cycle_length.

        Args:
            phase_flows: optional dict of phase flows (used to count phases)
            saturation_flow: unused (for API compatibility)
            min_green: minimum green time per phase
            max_green: maximum green time per phase
            yellow_time: yellow time per phase
            num_phases: number of phases if phase_flows not given

        Returns:
            List of green durations (int, seconds)
        """
        if phase_flows is not None:
            n = len(phase_flows)
        else:
            n = num_phases

        if n == 0:
            return []

        total_yellow = n * yellow_time
        total_green = self.cycle_length - total_yellow
        total_green = max(total_green, n * min_green)

        # Start everyone at min_green, distribute the remainder randomly
        result = [min_green] * n
        remaining = total_green - sum(result)

        # Randomly distribute remaining green time
        for _ in range(int(remaining)):
            # Pick a random phase that can still accept more green
            eligible = [i for i in range(n) if result[i] < max_green]
            if not eligible:
                break
            choice = self._rng.choice(eligible)
            result[choice] += 1

        return result
