"""
Baseline controllers for traffic signal timing.
- FixedTimeController: equal green splits for all phases
- RandomController: random green splits within constraints
- MaxPressureController: selects phase with maximum pressure
"""

import random as rng
from typing import Dict, List, Optional


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
        if phase_flows is not None:
            n = len(phase_flows)
        else:
            n = num_phases

        if n == 0:
            return []

        total_yellow = n * yellow_time
        total_green = self.cycle_length - total_yellow
        total_green = max(total_green, n * min_green)

        result = [min_green] * n
        remaining = total_green - sum(result)

        for _ in range(int(remaining)):
            eligible = [i for i in range(n) if result[i] < max_green]
            if not eligible:
                break
            choice = self._rng.choice(eligible)
            result[choice] += 1

        return result


class MaxPressureController:
    """MaxPressure signal controller.

    For each signal phase, computes pressure = sum of upstream queue lengths
    (vehicles on approaches served by that phase).  The phase with the
    highest pressure receives green; its duration is proportional to the
    pressure ratio (clamped to [min_green, max_green]).

    Two operating modes
    -------------------
    1. **Explicit queue data** (preferred for real-time control):
       Pass ``queue_data`` – a dict mapping direction names to queue lengths
       (e.g. ``{"east": 5, "west": 3, "north": 8, "south": 2}``).
       The ``phase_flows`` dict keys are used as phase names and their
       values are summed pressure contributions for that phase.
       ``phase_directions`` maps each phase key to the list of directions
       it serves.

    2. **Flow-based** (API-compatible with other controllers):
       When ``queue_data`` is *None*, the values in ``phase_flows`` are
       treated as traffic demand and the phase with the largest value wins.
    """

    def __init__(
        self,
        cycle_length: int = 60,
        yellow_time: int = 3,
        phase_directions: Optional[Dict[str, List[str]]] = None,
    ):
        self.cycle_length = cycle_length
        self.yellow_time = yellow_time
        # Default: two-phase grid intersection
        self.phase_directions = phase_directions or {
            "EW": ["east", "west"],
            "NS": ["north", "south"],
        }

    def compute_timing(
        self,
        phase_flows: Dict[str, float] = None,
        saturation_flow: float = 1800,
        min_green: int = 10,
        max_green: int = 60,
        yellow_time: int = 3,
        num_phases: int = 2,
        queue_data: Optional[Dict[str, int]] = None,
    ) -> List[int]:
        """Return green durations for each phase.

        Parameters
        ----------
        phase_flows : dict
            Phase names (used to determine number of phases and, together
            with ``phase_directions``, to map directions to phases).
        queue_data : dict, optional
            Current per-direction queue lengths.  When provided the
            pressure for each phase is computed from these values instead
            of from ``phase_flows`` values.
        """
        if phase_flows is not None:
            phases = list(phase_flows.keys())
        else:
            phases = list(self.phase_directions.keys())[: (num_phases or 2)]

        n = len(phases)
        if n == 0:
            return []

        total_yellow = n * yellow_time
        total_green = self.cycle_length - total_yellow

        # --- Compute pressure per phase ---
        pressures: List[float] = []
        for phase_name in phases:
            directions = self.phase_directions.get(phase_name, [])
            if queue_data is not None:
                # Pressure = sum of queue lengths on approaches served by this phase
                p = sum(queue_data.get(d, 0) for d in directions)
            else:
                # Fall back to flow value (API compatibility)
                p = float(phase_flows.get(phase_name, 0))
            pressures.append(p)

        total_pressure = sum(pressures)

        # --- Distribute green time proportional to pressure ---
        if total_pressure > 0:
            greens = [
                max(min_green, min(max_green, round((p / total_pressure) * total_green)))
                for p in pressures
            ]
        else:
            # No pressure detected: equal split
            per = max(min_green, total_green // n) if n else 0
            greens = [per] * n

        # Adjust for rounding to exactly fill total_green
        diff = total_green - sum(greens)
        if n > 0:
            # Add/subtract from the phase with the most pressure
            idx = pressures.index(max(pressures))
            greens[idx] = max(min_green, min(max_green, greens[idx] + diff))

        return greens
