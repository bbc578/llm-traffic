"""
Tests for CoordinationEngine.

Tests cover:
- Upstream queue above threshold triggers boost
- Critical queue triggers force_phase
- No congestion returns "no coordination needed"
- apply_adjustments correctly increases NS or EW green
- Boost doesn't exceed max_boost

These tests do not require SUMO and test pure Python modules only.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.algorithms.coordination import CoordinationEngine


class TestCoordinationEngine:
    """Test suite for CoordinationEngine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = CoordinationEngine()

    def test_upstream_queue_triggers_boost(self):
        """Test that upstream queue above threshold triggers boost."""
        # A0 has 10 vehicles eastbound (above threshold=5)
        all_queues = {
            "A0": {"east": 10, "west": 3, "north": 2, "south": 1},
            "B0": {"east": 2, "west": 3, "north": 1, "south": 1},
        }
        
        adjustments = self.engine.compute_adjustments(all_queues, {})
        
        # B0 should get EW boost (A0 eastbound → B0 westbound)
        assert adjustments["B0"]["boost_ew"] > 0
        assert "A0.east=10" in adjustments["B0"]["reason"]

    def test_critical_queue_triggers_force_phase(self):
        """Test that critical queue triggers force_phase."""
        # A0 has 15 vehicles eastbound (above critical_threshold=12)
        all_queues = {
            "A0": {"east": 15, "west": 3, "north": 2, "south": 1},
            "B0": {"east": 2, "west": 3, "north": 1, "south": 1},
        }
        
        adjustments = self.engine.compute_adjustments(all_queues, {})
        
        # B0 should force EW phase
        assert adjustments["B0"]["force_phase"] == 2
        assert "CRITICAL" in adjustments["B0"]["reason"]

    def test_no_congestion_no_coordination(self):
        """Test that no congestion returns no coordination needed."""
        # All queues are low
        all_queues = {
            "A0": {"east": 2, "west": 1, "north": 1, "south": 1},
            "B0": {"east": 1, "west": 2, "north": 1, "south": 1},
        }
        
        adjustments = self.engine.compute_adjustments(all_queues, {})
        
        # No boost or force
        assert adjustments["B0"]["boost_ew"] == 0
        assert adjustments["B0"]["boost_ns"] == 0
        assert adjustments["B0"]["force_phase"] is None
        assert "no coordination needed" in adjustments["B0"]["reason"]

    def test_apply_adjustments_increases_green(self):
        """Test that apply_adjustments correctly increases green time."""
        base_timings = {
            "B0": {0: 30, 1: 3, 2: 25, 3: 3}
        }
        adjustments = {
            "B0": {"boost_ew": 10, "boost_ns": 0, "force_phase": None}
        }
        
        result = self.engine.apply_adjustments(base_timings, adjustments)
        
        # EW green should increase by 10s
        assert result["B0"][2] == 35  # 25 + 10
        # NS green should stay the same
        assert result["B0"][0] == 30

    def test_boost_doesnt_exceed_max(self):
        """Test that boost doesn't exceed max_boost."""
        base_timings = {
            "B0": {0: 30, 1: 3, 2: 50, 3: 3}
        }
        adjustments = {
            "B0": {"boost_ew": 30, "boost_ns": 0, "force_phase": None}
        }
        
        result = self.engine.apply_adjustments(base_timings, adjustments)
        
        # EW green should be clamped to 90s max
        assert result["B0"][2] <= 90

    def test_force_phase_sets_minimum(self):
        """Test that force_phase sets minimum green time."""
        base_timings = {
            "B0": {0: 20, 1: 3, 2: 25, 3: 3}
        }
        adjustments = {
            "B0": {"boost_ew": 0, "boost_ns": 0, "force_phase": 0}
        }
        
        result = self.engine.apply_adjustments(base_timings, adjustments)
        
        # NS green should be at least 45s (force_phase minimum)
        assert result["B0"][0] >= 45

    def test_multiple_upstream_intersections(self):
        """Test coordination with multiple upstream intersections."""
        # B0 receives from A0 (west) and B1 (north)
        all_queues = {
            "A0": {"east": 8, "west": 2, "north": 1, "south": 1},
            "B1": {"south": 7, "north": 2, "east": 1, "west": 1},
            "B0": {"east": 2, "west": 3, "north": 1, "south": 1},
        }
        
        adjustments = self.engine.compute_adjustments(all_queues, {})
        
        # B0 should get both EW boost (from A0) and NS boost (from B1)
        assert adjustments["B0"]["boost_ew"] > 0
        assert adjustments["B0"]["boost_ns"] > 0

    def test_reverse_direction_mapping(self):
        """Test that direction reversal works correctly."""
        assert self.engine._reverse_dir("east") == "west"
        assert self.engine._reverse_dir("west") == "east"
        assert self.engine._reverse_dir("north") == "south"
        assert self.engine._reverse_dir("south") == "north"
        assert self.engine._reverse_dir("unknown") == "unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
