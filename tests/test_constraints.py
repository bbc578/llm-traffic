"""
Tests for SignalConstraintEngine.

Tests cover:
- min_green correction
- max_green correction
- cycle length correction
- empty phase input
- normal valid input

These tests do not require SUMO and test pure Python modules only.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.algorithms.constraints import SignalConstraintEngine


class TestSignalConstraintEngine:
    """Test suite for SignalConstraintEngine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = SignalConstraintEngine()

    def test_min_green_correction(self):
        """Test that phases below min_green are corrected."""
        # Phase 0 is 5s (below min 10s)
        valid, violations, corrected = self.engine.validate([5, 30], 68)
        
        assert not valid
        assert len(violations) > 0
        # Should have min_green violation
        assert any("below minimum" in v for v in violations)
        # Corrected value should be >= min_green
        assert corrected[0] >= 10

    def test_max_green_correction(self):
        """Test that phases above max_green are corrected."""
        # Phase 0 is 120s (above max 60s)
        valid, violations, corrected = self.engine.validate([120, 30], 153)
        
        assert not valid
        assert len(violations) > 0
        # Should have max_green violation
        assert any("exceeds maximum" in v for v in violations)
        # Corrected value should be <= max_green
        assert corrected[0] <= 60

    def test_cycle_length_correction(self):
        """Test that invalid cycle lengths are corrected."""
        # Cycle length 200s (above max 180s)
        valid, violations, corrected = self.engine.validate([30, 30], 200)
        
        assert not valid
        assert len(violations) > 0
        # Should have cycle length violation
        assert any("Cycle length" in v for v in violations)

    def test_empty_phases(self):
        """Test that empty phase input is handled."""
        valid, violations, corrected = self.engine.validate([], 60)
        
        assert not valid
        assert len(violations) > 0
        assert "No phases" in violations[0]
        assert corrected == []

    def test_normal_valid_input(self):
        """Test that valid input passes without correction."""
        # Valid: 30s + 3s + 30s + 3s = 66s cycle
        valid, violations, corrected = self.engine.validate([30, 30], 66)
        
        assert valid
        assert len(violations) == 0
        assert corrected == [30, 30]

    def test_boundary_values(self):
        """Test boundary values (min_green, max_green)."""
        # Valid: 10s + 3s + 10s + 3s = 26s cycle (but min_cycle is 30s)
        # So this should be invalid due to cycle length
        valid, violations, corrected = self.engine.validate([10, 10], 26)
        assert not valid  # Cycle too short
        
        # Valid cycle with min_green
        valid, violations, corrected = self.engine.validate([10, 10], 26)
        # Corrected should respect min_green
        assert all(g >= 10 for g in corrected)

    def test_correction_preserves_ratio(self):
        """Test that correction preserves relative ratios when possible."""
        # 40s and 20s (2:1 ratio)
        valid, violations, corrected = self.engine.validate([40, 20], 66)
        
        assert valid
        assert corrected == [40, 20]

    def test_custom_rules(self):
        """Test with custom constraint rules."""
        engine = SignalConstraintEngine({
            "min_green": 15,
            "max_green": 45,
        })
        
        # Phase 0 is 10s (below custom min 15s)
        valid, violations, corrected = engine.validate([10, 30], 46)
        
        assert not valid
        # Corrected value should be >= custom min_green
        assert corrected[0] >= 15

    def test_multiple_violations(self):
        """Test multiple violations in single validation."""
        # Phase 0 too short, Phase 1 too long
        valid, violations, corrected = self.engine.validate([5, 120], 128)
        
        assert not valid
        assert len(violations) >= 2
        # Should have both min and max violations
        assert any("below minimum" in v for v in violations)
        assert any("exceeds maximum" in v for v in violations)

    def test_correction_within_bounds(self):
        """Test that all corrected values are within bounds."""
        # Various invalid inputs
        test_cases = [
            ([5, 30], 68),
            ([120, 30], 153),
            ([10, 10], 26),
            ([5, 120], 128),
        ]
        
        for phases, cycle in test_cases:
            valid, violations, corrected = self.engine.validate(phases, cycle)
            
            # All corrected values should be within [min_green, max_green]
            for g in corrected:
                assert g >= 10, f"Corrected value {g} below min_green"
                assert g <= 60, f"Corrected value {g} above max_green"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
