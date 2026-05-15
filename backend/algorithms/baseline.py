"""
Baseline Controllers for Traffic Signal Timing

This module implements baseline signal controllers for comparison:
1. FixedTimeController: Equal green splits for all phases
2. RandomController: Random green splits within constraints
3. MaxPressureController: Selects phase with maximum pressure

Why Baselines?
==============
To evaluate our LLM-based approach, we need reference points:
- FixedTime: The simplest approach (no adaptation)
- Random: Shows what random decisions look like
- MaxPressure: A classical adaptive approach
- Webster: A well-known formula-based approach (in webster.py)

These baselines help us understand:
1. How much improvement does LLM provide?
2. Is the improvement statistically significant?
3. What's the performance floor?

Author: Yihao Tang
Date: 2024
"""

import random as rng
from typing import Dict, List, Optional


class FixedTimeController:
    """Distributes green time equally among all phases.
    
    This is the simplest possible controller:
    - Splits green time equally among all phases
    - No adaptation to traffic conditions
    - Used as a baseline to show the value of adaptation
    
    Example:
        controller = FixedTimeController(cycle_length=60)
        timings = controller.compute_timing(num_phases=2)
        # Returns: [27, 27] (equal split with yellow time subtracted)
    """

    def __init__(self, cycle_length: int = 60, yellow_time: int = 3):
        """Initialize the fixed-time controller.
        
        Args:
            cycle_length: Total signal cycle length in seconds.
                         Default 60s (typical urban intersection)
            yellow_time: Yellow/clearance time per phase in seconds.
                        Default 3s (standard value)
        """
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
        """Compute equal green durations for all phases.
        
        Args:
            phase_flows: Optional dict of phase flows; used only to determine
                the number of phases.
            saturation_flow: Unused; kept for API compatibility.
            min_green: Minimum green time per phase (seconds).
            max_green: Maximum green time per phase (seconds).
            yellow_time: Yellow/clearance time per phase (seconds).
            num_phases: Number of phases if phase_flows is None.
        
        Returns:
            List of green durations (int, seconds), one per phase.
        
        Example:
            # Two phases, 60s cycle, 3s yellow each
            timings = controller.compute_timing(num_phases=2)
            # Returns: [27, 27] (60 - 2*3 = 54, 54/2 = 27)
        """
        if phase_flows is not None:
            n = len(phase_flows)
        else:
            n = num_phases

        if n == 0:
            return []

        # Calculate total green time (cycle - yellow per phase)
        total_yellow = n * yellow_time
        total_green = self.cycle_length - total_yellow
        
        # Distribute equally among phases
        green_per_phase = max(min_green, total_green // n)
        green_per_phase = min(max_green, green_per_phase)

        result = [green_per_phase] * n

        # Handle remainder (distribute to last phase)
        remainder = total_green - sum(result)
        if n > 0:
            result[-1] += remainder
            result[-1] = max(min_green, min(max_green, result[-1]))

        return result


class RandomController:
    """Generates random green splits within constraint bounds.
    
    This controller randomizes signal timing to show:
    1. The value of intelligent control
    2. A lower bound on performance
    3. How much worse random decisions are compared to LLM
    
    The randomization is reproducible (seeded) for fair comparison.
    
    Example:
        controller = RandomController(seed=42)
        timings = controller.compute_timing(num_phases=2)
        # Returns: [15, 39] (random but within bounds)
    """

    def __init__(self, cycle_length: int = 60, yellow_time: int = 3, seed: int = None):
        """Initialize the random controller.
        
        Args:
            cycle_length: Total signal cycle length in seconds.
                         Default 60s
            yellow_time: Yellow/clearance time per phase in seconds.
                        Default 3s
            seed: Random seed for reproducibility, or None for random.
                  Using a seed ensures fair comparison across trials.
        """
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
        """Compute random green durations within constraint bounds.
        
        Algorithm:
        1. Start with minimum green for each phase
        2. Distribute remaining green time randomly
        3. Respect min/max constraints
        
        Args:
            phase_flows: Optional dict of phase flows; used only to determine
                the number of phases.
            saturation_flow: Unused; kept for API compatibility.
            min_green: Minimum green time per phase (seconds).
            max_green: Maximum green time per phase (seconds).
            yellow_time: Yellow/clearance time per phase (seconds).
            num_phases: Number of phases if phase_flows is None.
        
        Returns:
            List of green durations (int, seconds), one per phase.
        
        Example:
            timings = controller.compute_timing(num_phases=2)
            # Returns: [15, 39] or similar random split
        """
        if phase_flows is not None:
            n = len(phase_flows)
        else:
            n = num_phases

        if n == 0:
            return []

        # Calculate total green time
        total_yellow = n * yellow_time
        total_green = self.cycle_length - total_yellow
        total_green = max(total_green, n * min_green)

        # Start with minimum green for each phase
        result = [min_green] * n
        remaining = total_green - sum(result)

        # Distribute remaining green time randomly
        # Add 1 second at a time to a random phase
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
    
    Two operating modes:
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
    
    Example:
        controller = MaxPressureController()
        timings = controller.compute_timing(
            phase_flows={"EW": 10, "NS": 20},
            queue_data={"east": 5, "west": 5, "north": 10, "south": 10}
        )
        # NS gets more green because it has higher pressure (20 vs 10)
    """

    def __init__(
        self,
        cycle_length: int = 60,
        yellow_time: int = 3,
        phase_directions: Optional[Dict[str, List[str]]] = None,
    ):
        """Initialize the max-pressure controller.
        
        Args:
            cycle_length: Total signal cycle length in seconds.
                         Default 60s
            yellow_time: Yellow/clearance time per phase in seconds.
                        Default 3s
            phase_directions: Maps phase names to the list of approach
                directions they serve (e.g. {"EW": ["east", "west"]}).
                Default: two-phase grid intersection
        """
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
        """Compute green durations proportional to per-phase queue pressure.
        
        Algorithm:
        1. For each phase, compute pressure = sum of queue lengths
        2. Distribute green time proportional to pressure
        3. Apply min/max constraints
        
        Args:
            phase_flows: Phase name -> flow value. Keys determine phase count
                and, with phase_directions, map directions to phases.
            saturation_flow: Unused; kept for API compatibility.
            min_green: Minimum green time per phase (seconds).
            max_green: Maximum green time per phase (seconds).
            yellow_time: Yellow/clearance time per phase (seconds).
            num_phases: Number of phases if phase_flows is None.
            queue_data: Optional per-direction queue lengths for pressure
                calculation. Falls back to phase_flows values if None.
        
        Returns:
            List of green durations (int, seconds), one per phase.
        
        Example:
            timings = controller.compute_timing(
                phase_flows={"EW": 10, "NS": 20},
                queue_data={"east": 5, "west": 5, "north": 10, "south": 10}
            )
            # NS gets more green because it has higher pressure (20 vs 10)
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
        # Pressure = sum of queue lengths on approaches served by this phase
        pressures: List[float] = []
        for phase_name in phases:
            directions = self.phase_directions.get(phase_name, [])
            if queue_data is not None:
                # Use actual queue data
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
