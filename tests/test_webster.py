"""
Tests for WebsterController.

Tests cover:
- Empty input returns empty list
- Balanced flows produce near-equal output
- Oversaturated flows don't crash
- Output respects min_green
- Output respects max_green

These tests do not require SUMO and test pure Python modules only.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.algorithms.webster import WebsterController


class TestWebsterController:
    """Test suite for WebsterController."""

    def setup_method(self):
        """Set up test fixtures."""
        self.controller = WebsterController()

    def test_empty_input(self):
        """Test that empty input returns empty list."""
        result = self.controller.compute_timing({})
        assert result == []

    def test_balanced_flows(self):
        """Test that balanced flows produce near-equal output."""
        # Equal flows for EW and NS
        result = self.controller.compute_timing({"EW": 900, "NS": 900})
        
        assert len(result) == 2
        # Should be approximately equal (within 5s)
        assert abs(result[0] - result[1]) <= 5

    def test_oversaturated_flows(self):
        """Test that oversaturated flows don't crash."""
        # Very high flows (oversaturated)
        result = self.controller.compute_timing({"EW": 5000, "NS": 5000})
        
        assert len(result) == 2
        # Should still return valid values
        assert all(10 <= g <= 60 for g in result)

    def test_min_green_respected(self):
        """Test that output respects min_green."""
        # Very low flows
        result = self.controller.compute_timing(
            {"EW": 10, "NS": 10},
            min_green=15
        )
        
        assert len(result) == 2
        assert all(g >= 15 for g in result)

    def test_max_green_respected(self):
        """Test that output respects max_green."""
        # High flows for one direction
        result = self.controller.compute_timing(
            {"EW": 2000, "NS": 100},
            max_green=45
        )
        
        assert len(result) == 2
        assert all(g <= 45 for g in result)

    def test_single_phase(self):
        """Test with single phase."""
        result = self.controller.compute_timing({"EW": 800})
        
        assert len(result) == 1
        assert 10 <= result[0] <= 60

    def test_multiple_phases(self):
        """Test with multiple phases."""
        result = self.controller.compute_timing({
            "EW": 800,
            "NS": 600,
            "NE": 400
        })
        
        assert len(result) == 3
        assert all(10 <= g <= 60 for g in result)

    def test_zero_flow(self):
        """Test with zero flow."""
        result = self.controller.compute_timing({"EW": 0, "NS": 0})
        
        assert len(result) == 2
        # Should still return valid values (equal split)
        assert all(10 <= g <= 60 for g in result)

    def test_asymmetric_flows(self):
        """Test that asymmetric flows produce proportional output."""
        # EW has 3x more flow than NS
        result = self.controller.compute_timing({"EW": 900, "NS": 300})
        
        assert len(result) == 2
        # EW should get more green time
        assert result[0] > result[1]

    def test_custom_saturation_flow(self):
        """Test with custom saturation flow."""
        result = self.controller.compute_timing(
            {"EW": 800, "NS": 600},
            saturation_flow=1200  # Lower saturation flow
        )
        
        assert len(result) == 2
        assert all(10 <= g <= 60 for g in result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
