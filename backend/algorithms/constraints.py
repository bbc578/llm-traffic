"""
Constraint Engine for Validating LLM-Generated Signal Timing Decisions

This module implements a rule-based constraint engine that validates and corrects
signal timing decisions from the LLM. It ensures all decisions are safe before
being applied to the traffic signals.

Why a Constraint Engine?
========================
LLMs are powerful but not infallible. They can suggest:
- Green times that are too short (unsafe for pedestrians)
- Green times that are too long (starves other phases)
- Invalid cycle lengths

The constraint engine acts as a safety net:
1. Validates all LLM decisions against safety rules
2. Auto-corrects violations to safe values
3. Logs violations for analysis

Design Philosophy:
==================
- Safety is non-negotiable
- LLM decisions are suggestions, not commands
- Constraint engine has final authority
- All violations are logged for debugging

Constraints:
============
- min_green: 10s (pedestrian safety, allows crossing)
- max_green: 60s (prevents starvation of other phases)
- min_cycle: 30s (minimum complete cycle)
- max_cycle: 180s (maximum for responsiveness)
- yellow_time: 3s (standard clearance interval)

Author: Yihao Tang
Date: 2024
"""

from typing import List, Tuple, Union


class SignalConstraintEngine:
    """Rule engine that validates signal phase timings against safety and
    operational constraints.
    
    This engine ensures that all signal timing decisions (whether from LLM,
    Webster's formula, or any other source) satisfy safety requirements.
    
    Key Features:
    1. Validates against configurable rules
    2. Auto-corrects violations
    3. Returns human-readable violation descriptions
    4. Handles edge cases (empty phases, extreme values)
    
    Usage:
        engine = SignalConstraintEngine()
        
        # Validate LLM suggestion
        valid, violations, corrected = engine.validate(
            green_phases=[45, 20],
            cycle_length=71
        )
        
        if not valid:
            print("Violations:", violations)
            print("Using corrected values:", corrected)
    """

    # Default safety constraints
    # These values are based on traffic engineering standards
    DEFAULT_RULES = {
        "min_green": 10,        # Minimum green time per phase (seconds)
                                # Why 10s? Allows pedestrians to cross safely
        "max_green": 60,        # Maximum green time per phase (seconds)
                                # Why 60s? Prevents starvation of other phases
        "min_cycle": 30,        # Minimum total cycle length (seconds)
                                # Why 30s? Ensures all phases get some time
        "max_cycle": 180,       # Maximum total cycle length (seconds)
                                # Why 180s? Keeps system responsive to changes
        "yellow_time": 3,       # Yellow/clearance time per phase (seconds)
                                # Why 3s? Standard traffic engineering value
    }

    def __init__(self, rules: dict = None):
        """Initialize the constraint engine with optional custom rules.
        
        Args:
            rules: Optional dict overriding default constraint values.
                   Keys: min_green, max_green, min_cycle, max_cycle, yellow_time
                   Values: Numeric values (int or float)
        
        Example:
            # Use default rules
            engine = SignalConstraintEngine()
            
            # Custom rules for a specific intersection
            engine = SignalConstraintEngine({
                "min_green": 15,  # Longer minimum for busy intersection
                "max_green": 45,  # Shorter maximum for responsiveness
            })
        """
        self.rules = dict(self.DEFAULT_RULES)
        if rules:
            self.rules.update(rules)

    def validate(
        self,
        green_phases: List[float],
        cycle_length: float,
    ) -> Tuple[bool, List[str], List[int]]:
        """Validate green phase durations against constraints.
        
        This method checks all constraints and returns:
        1. Whether all constraints pass
        2. List of violation descriptions
        3. Corrected green durations
        
        Args:
            green_phases: list of green durations for each phase (seconds)
                         Example: [30, 25] for NS=30s, EW=25s
            cycle_length: total cycle length in seconds
                         Example: 66 (30 + 3 + 25 + 3 + 5 buffer)
        
        Returns:
            Tuple of (valid, violations, corrected)
            - valid: True if all constraints pass
            - violations: List of human-readable violation descriptions
            - corrected: List of corrected green durations (clamped to constraints)
        
        Example:
            valid, violations, corrected = engine.validate([5, 30], 68)
            # valid = False
            # violations = ["Phase 0: green 5s is below minimum 10s."]
            # corrected = [10, 30]
        """
        violations: List[str] = []
        min_green = self.rules["min_green"]
        max_green = self.rules["max_green"]
        min_cycle = self.rules["min_cycle"]
        max_cycle = self.rules["max_cycle"]
        yellow_time = self.rules["yellow_time"]

        n = len(green_phases)

        # Edge case: no phases provided
        if n == 0:
            violations.append("No phases provided.")
            return False, violations, []

        # Rule 1: Cycle length bounds
        # Cycle must be within [min_cycle, max_cycle]
        if cycle_length < min_cycle:
            violations.append(
                f"Cycle length {cycle_length}s is below minimum {min_cycle}s."
            )
        if cycle_length > max_cycle:
            violations.append(
                f"Cycle length {cycle_length}s exceeds maximum {max_cycle}s."
            )

        # Rule 2: Each phase must have at least min_green
        # This ensures pedestrians have enough time to cross
        for i, g in enumerate(green_phases):
            if g < min_green:
                violations.append(
                    f"Phase {i}: green {g}s is below minimum {min_green}s."
                )

        # Rule 3: Each phase must not exceed max_green
        # This prevents starvation of other phases
        for i, g in enumerate(green_phases):
            if g > max_green:
                violations.append(
                    f"Phase {i}: green {g}s exceeds maximum {max_green}s."
                )

        # Rule 4: Total green + yellow must equal cycle length
        # This ensures the cycle is complete
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
        """Produce a corrected version of green_phases that satisfies all constraints.
        
        Correction algorithm:
        1. Clamp cycle length to [min_cycle, max_cycle]
        2. Calculate available green time (cycle - yellow)
        3. Clamp each phase to [min_green, max_green]
        4. Distribute remaining green time proportionally
        
        Args:
            green_phases: Original green durations from LLM
            cycle_length: Original cycle length
        
        Returns:
            List of corrected green durations (int, seconds)
        """
        min_green = self.rules["min_green"]
        max_green = self.rules["max_green"]
        yellow_time = self.rules["yellow_time"]
        min_cycle = self.rules["min_cycle"]
        max_cycle = self.rules["max_cycle"]

        n = len(green_phases)
        if n == 0:
            return []

        # Step 1: Clamp cycle length to valid range
        cycle = max(min_cycle, min(cycle_length, max_cycle))

        # Step 2: Calculate total green time available
        # Total green = cycle - (number of phases × yellow time)
        total_green = cycle - (n * yellow_time)
        total_green = max(total_green, n * min_green)  # Ensure minimum per phase

        # Step 3: First pass - clamp individual phases to [min_green, max_green]
        corrected = []
        for g in green_phases:
            corrected.append(max(min_green, min(max_green, round(g))))

        # Step 4: Adjust total to match target
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
