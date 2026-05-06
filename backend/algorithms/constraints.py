"""
Constraint engine for validating and correcting LLM-generated signal timing decisions.
"""

from typing import List, Tuple, Union


class SignalConstraintEngine:
    """
    Rule engine that validates signal phase timings against safety and
    operational constraints. Can also auto-correct violations.
    """

    DEFAULT_RULES = {
        "min_green": 10,        # Minimum green time per phase (seconds)
        "max_green": 60,        # Maximum green time per phase (seconds)
        "min_cycle": 30,        # Minimum total cycle length (seconds)
        "max_cycle": 180,       # Maximum total cycle length (seconds)
        "yellow_time": 3,       # Yellow/clearance time per phase (seconds)
    }

    def __init__(self, rules: dict = None):
        """Initialize the constraint engine with optional custom rules.

        Args:
            rules: Optional dict overriding default constraint values
                   (min_green, max_green, min_cycle, max_cycle, yellow_time).
        """
        self.rules = dict(self.DEFAULT_RULES)
        if rules:
            self.rules.update(rules)

    def validate(
        self,
        green_phases: List[float],
        cycle_length: float,
    ) -> Tuple[bool, List[str], List[int]]:
        """
        Validate green phase durations against constraints.

        Args:
            green_phases: list of green durations for each phase (seconds)
            cycle_length: total cycle length in seconds

        Returns:
            (valid, violations, corrected)
            - valid: True if all constraints pass
            - violations: list of human-readable violation descriptions
            - corrected: list of corrected green durations (clamped to constraints)
        """
        violations: List[str] = []
        min_green = self.rules["min_green"]
        max_green = self.rules["max_green"]
        min_cycle = self.rules["min_cycle"]
        max_cycle = self.rules["max_cycle"]
        yellow_time = self.rules["yellow_time"]

        n = len(green_phases)

        if n == 0:
            violations.append("No phases provided.")
            return False, violations, []

        # Rule 1: Cycle length bounds
        if cycle_length < min_cycle:
            violations.append(
                f"Cycle length {cycle_length}s is below minimum {min_cycle}s."
            )
        if cycle_length > max_cycle:
            violations.append(
                f"Cycle length {cycle_length}s exceeds maximum {max_cycle}s."
            )

        # Rule 2: Each phase must have at least min_green
        for i, g in enumerate(green_phases):
            if g < min_green:
                violations.append(
                    f"Phase {i}: green {g}s is below minimum {min_green}s."
                )

        # Rule 3: Each phase must not exceed max_green
        for i, g in enumerate(green_phases):
            if g > max_green:
                violations.append(
                    f"Phase {i}: green {g}s exceeds maximum {max_green}s."
                )

        # Rule 4: Total green + yellow must equal cycle length
        total_yellow = n * yellow_time
        total_green = sum(green_phases)
        expected_cycle = total_green + total_yellow
        tolerance = n * 0.5  # Allow small rounding tolerance
        if abs(expected_cycle - cycle_length) > tolerance:
            violations.append(
                f"Total green ({total_green}s) + yellow ({total_yellow}s) = "
                f"{expected_cycle}s does not equal cycle length {cycle_length}s "
                f"(difference: {abs(expected_cycle - cycle_length):.1f}s)."
            )

        # Build corrected durations
        corrected = self._correct(green_phases, cycle_length)

        valid = len(violations) == 0
        return valid, violations, corrected

    def _correct(self, green_phases: List[float], cycle_length: float) -> List[int]:
        """
        Produce a corrected version of green_phases that satisfies all constraints.
        """
        min_green = self.rules["min_green"]
        max_green = self.rules["max_green"]
        yellow_time = self.rules["yellow_time"]
        min_cycle = self.rules["min_cycle"]
        max_cycle = self.rules["max_cycle"]

        n = len(green_phases)
        if n == 0:
            return []

        # Clamp cycle length
        cycle = max(min_cycle, min(cycle_length, max_cycle))

        # Total green available = cycle - yellow
        total_green = cycle - (n * yellow_time)
        total_green = max(total_green, n * min_green)

        # First pass: clamp individual phases
        corrected = []
        for g in green_phases:
            corrected.append(max(min_green, min(max_green, round(g))))

        # Adjust total to match target
        current_total = sum(corrected)
        diff = total_green - current_total

        if diff != 0:
            # Distribute difference proportionally
            for i in range(n):
                if diff > 0:
                    # Need to add green time
                    room = max_green - corrected[i]
                    add = min(room, diff)
                    corrected[i] += add
                    diff -= add
                elif diff < 0:
                    # Need to remove green time
                    room = corrected[i] - min_green
                    remove = min(room, -diff)
                    corrected[i] -= remove
                    diff += remove

                if diff == 0:
                    break

            # If still have remaining diff, distribute equally
            if diff > 0:
                for i in range(n):
                    add = min(max_green - corrected[i], diff)
                    corrected[i] += add
                    diff -= add
                    if diff == 0:
                        break
            elif diff < 0:
                for i in range(n):
                    remove = min(corrected[i] - min_green, -diff)
                    corrected[i] -= remove
                    diff += remove
                    if diff == 0:
                        break

        return corrected
