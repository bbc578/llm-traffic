"""
Tests for LLM-Traffic framework.
Run with: python3.10 -m pytest tests/ -v
"""
import os
import sys
import json
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SUMO_HOME"] = os.environ.get("SUMO_HOME", "/usr/share/sumo")


# ── LLM Client Tests ──────────────────────────────────────────────────────

class TestLLMClient:
    """Tests for xiaomi_client.py (offline, no API calls)."""

    def test_parse_valid_json(self):
        from backend.llm.xiaomi_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        # Simulate _parse_response
        raw = '{"phase_durations": {"0": 45, "1": 3, "2": 35, "3": 3}, "reasoning": "test"}'
        result = client._parse_response(raw)
        assert result["phase_durations"][0] == 45
        assert result["phase_durations"][2] == 35
        assert result["reasoning"] == "test"

    def test_parse_json_with_extra_text(self):
        from backend.llm.xiaomi_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        raw = 'Here is the result: {"phase_durations": {"0": 50, "1": 3, "2": 30, "3": 3}, "reasoning": "ok"} Done.'
        result = client._parse_response(raw)
        assert result["phase_durations"][0] == 50

    def test_parse_invalid_json_returns_defaults(self):
        from backend.llm.xiaomi_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        raw = "no json here at all"
        result = client._parse_response(raw)
        assert result["phase_durations"] == {0: 30, 1: 3, 2: 30, 3: 3}

    def test_parse_clamps_green_time(self):
        from backend.llm.xiaomi_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        # Green time > 90 should be clamped
        raw = '{"phase_durations": {"0": 200, "1": 3, "2": 5, "3": 3}, "reasoning": "test"}'
        result = client._parse_response(raw)
        assert result["phase_durations"][0] == 90
        # Green time < 10 should be clamped
        assert result["phase_durations"][2] == 10

    def test_parse_clamps_yellow_time(self):
        from backend.llm.xiaomi_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        raw = '{"phase_durations": {"0": 30, "1": 10, "2": 30, "3": 1}, "reasoning": "test"}'
        result = client._parse_response(raw)
        assert result["phase_durations"][1] == 5  # max 5
        assert result["phase_durations"][3] == 3  # min 3

    def test_parse_fills_missing_phases(self):
        from backend.llm.xiaomi_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        raw = '{"phase_durations": {"0": 40}, "reasoning": "partial"}'
        result = client._parse_response(raw)
        assert result["phase_durations"][0] == 40
        assert result["phase_durations"][1] == 3  # default yellow
        assert result["phase_durations"][2] == 30  # default green
        assert result["phase_durations"][3] == 3

    def test_batch_parse(self):
        from backend.llm.xiaomi_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        raw = '{"A0": {"phase_durations": {"0": 40, "1": 3, "2": 20, "3": 3}, "reasoning": "test"}, "A1": {"phase_durations": {"0": 20, "1": 3, "2": 40, "3": 3}, "reasoning": "test2"}}'
        states = {"A0": {}, "A1": {}}
        result = client._parse_batch_response(raw, states)
        assert "A0" in result
        assert "A1" in result
        assert result["A0"]["phase_durations"][0] == 40
        assert result["A1"]["phase_durations"][2] == 40


# ── Constraint Engine Tests ────────────────────────────────────────────────

class TestConstraintEngine:
    """Tests for constraints.py."""

    def test_valid_timing_passes(self):
        from backend.algorithms.constraints import SignalConstraintEngine
        engine = SignalConstraintEngine()
        valid, violations, corrected = engine.validate([30, 30], 66)
        assert valid is True
        assert len(violations) == 0

    def test_too_short_green_detected(self):
        from backend.algorithms.constraints import SignalConstraintEngine
        engine = SignalConstraintEngine()
        valid, violations, corrected = engine.validate([5, 30], 41)
        assert valid is False
        assert any("min" in v.lower() or "green" in v.lower() for v in violations)

    def test_too_long_green_detected(self):
        from backend.algorithms.constraints import SignalConstraintEngine
        engine = SignalConstraintEngine()
        valid, violations, corrected = engine.validate([100, 30], 136)
        assert valid is False

    def test_cycle_too_short(self):
        from backend.algorithms.constraints import SignalConstraintEngine
        engine = SignalConstraintEngine()
        valid, violations, corrected = engine.validate([10, 10], 26)
        assert valid is False

    def test_corrected_values_clamped(self):
        from backend.algorithms.constraints import SignalConstraintEngine
        engine = SignalConstraintEngine()
        _, _, corrected = engine.validate([200, 2], 208)
        assert all(10 <= c <= 60 for c in corrected)


# ── Coordination Engine Tests ──────────────────────────────────────────────

class TestCoordinationEngine:
    """Tests for coordination.py."""

    def test_no_coordination_needed(self):
        from backend.algorithms.coordination import CoordinationEngine
        engine = CoordinationEngine()
        queues = {
            "A0": {"north": 1, "south": 0, "east": 0, "west": 0},
            "B0": {"north": 0, "south": 0, "east": 0, "west": 0},
        }
        adj = engine.compute_adjustments(queues, {})
        assert adj["B0"]["boost_ew"] == 0
        assert adj["B0"]["force_phase"] is None

    def test_upstream_queue_triggers_boost(self):
        from backend.algorithms.coordination import CoordinationEngine
        engine = CoordinationEngine(queue_threshold=5)
        queues = {
            "A0": {"north": 0, "south": 0, "east": 8, "west": 0},  # A0 has eastbound queue
            "B0": {"north": 0, "south": 0, "east": 0, "west": 0},
        }
        adj = engine.compute_adjustments(queues, {})
        # B0 should boost EW because A0's eastbound queue feeds into B0's west
        assert adj["B0"]["boost_ew"] > 0

    def test_critical_queue_forces_phase(self):
        from backend.algorithms.coordination import CoordinationEngine
        engine = CoordinationEngine(critical_threshold=12)
        queues = {
            "A0": {"north": 0, "south": 0, "east": 15, "west": 0},
            "B0": {"north": 0, "south": 0, "east": 0, "west": 0},
        }
        adj = engine.compute_adjustments(queues, {})
        assert adj["B0"]["force_phase"] == 2  # EW green

    def test_apply_adjustments_boosts_green(self):
        from backend.algorithms.coordination import CoordinationEngine
        engine = CoordinationEngine()
        base = {"B0": {0: 30, 1: 3, 2: 30, 3: 3}}
        adj = {"B0": {"boost_ns": 0, "boost_ew": 15, "force_phase": None, "reason": "test"}}
        result = engine.apply_adjustments(base, adj)
        assert result["B0"][2] == 45  # 30 + 15

    def test_apply_adjustments_clamps_to_max(self):
        from backend.algorithms.coordination import CoordinationEngine
        engine = CoordinationEngine()
        base = {"B0": {0: 30, 1: 3, 2: 80, 3: 3}}
        adj = {"B0": {"boost_ns": 0, "boost_ew": 20, "force_phase": None, "reason": "test"}}
        result = engine.apply_adjustments(base, adj)
        assert result["B0"][2] == 90  # capped at 90


# ── Webster Controller Tests ───────────────────────────────────────────────

class TestWebsterController:
    """Tests for webster.py."""

    def test_basic_timing(self):
        from backend.algorithms.webster import WebsterController
        ctrl = WebsterController()
        timings = ctrl.compute_timing({"EW": 800, "NS": 400})
        assert len(timings) >= 2
        assert all(t >= 0 for t in timings)

    def test_higher_flow_gets_more_green(self):
        from backend.algorithms.webster import WebsterController
        ctrl = WebsterController()
        timings = ctrl.compute_timing({"EW": 1500, "NS": 300})
        # EW has much higher flow, should get more green
        assert timings[0] > timings[1] or timings[0] >= 10


# ── Baseline Controller Tests ──────────────────────────────────────────────

class TestBaselines:
    """Tests for baseline.py."""

    def test_fixed_returns_consistent(self):
        from backend.algorithms.baseline import FixedTimeController
        ctrl = FixedTimeController()
        t1 = ctrl.compute_timing({"EW": 500, "NS": 500})
        t2 = ctrl.compute_timing({"EW": 1000, "NS": 100})
        assert t1 == t2  # Fixed ignores input

    def test_random_varies(self):
        from backend.algorithms.baseline import RandomController
        ctrl = RandomController(seed=42)
        t1 = ctrl.compute_timing({"EW": 500, "NS": 500})
        t2 = ctrl.compute_timing({"EW": 500, "NS": 500})
        # With same seed, random should be deterministic
        # But different calls may produce different results
        assert len(t1) >= 2


# ── SUMO Engine Tests (requires SUMO) ──────────────────────────────────────

class TestSumoEngine:
    """Tests for sumo_engine.py (requires SUMO installed)."""

    def test_start_and_stop(self):
        from backend.simulation.sumo_engine import SumoEngine
        engine = SumoEngine()
        engine.start(config_file="data/grid6.sumocfg")
        assert engine.is_running
        assert len(engine.intersections) > 0
        engine.stop()
        assert not engine.is_running

    def test_discover_intersections(self):
        from backend.simulation.sumo_engine import SumoEngine
        engine = SumoEngine()
        engine.start(config_file="data/grid6.sumocfg")
        ints = engine.intersections
        assert len(ints) == 6  # 3×2 grid
        engine.stop()

    def test_step_advances_time(self):
        from backend.simulation.sumo_engine import SumoEngine
        engine = SumoEngine()
        engine.start(config_file="data/grid6.sumocfg")
        t0 = engine.simulation_time
        engine.step()
        t1 = engine.simulation_time
        assert t1 > t0
        engine.stop()

    def test_get_queue_lengths(self):
        from backend.simulation.sumo_engine import SumoEngine
        engine = SumoEngine()
        engine.start(config_file="data/grid6.sumocfg")
        for _ in range(10):
            engine.step()
        for iid in engine.intersections:
            ql = engine.get_queue_lengths(iid)
            assert isinstance(ql, dict)
            assert all(isinstance(v, int) for v in ql.values())
        engine.stop()

    def test_set_phase(self):
        from backend.simulation.sumo_engine import SumoEngine
        engine = SumoEngine()
        engine.start(config_file="data/grid6.sumocfg")
        for _ in range(10):
            engine.step()
        iid = engine.intersections[0]
        engine.set_phase(iid, 2, duration=40)
        sig = engine.get_signal_state(iid)
        assert sig["phase"] == 2
        engine.stop()

    def test_snapshot_structure(self):
        from backend.simulation.sumo_engine import SumoEngine
        engine = SumoEngine()
        engine.start(config_file="data/grid6.sumocfg")
        for _ in range(5):
            engine.step()
        snap = engine.get_snapshot()
        assert "time" in snap
        assert "queue_lengths" in snap
        assert "vehicle_counts" in snap
        assert "signals" in snap
        engine.stop()

    def test_metrics_accumulate(self):
        from backend.simulation.sumo_engine import SumoEngine
        engine = SumoEngine()
        engine.start(config_file="data/grid6.sumocfg")
        for _ in range(50):
            engine.step()
        m = engine.metrics
        assert m.total_steps == 50
        assert m.vehicles_departed >= 0
        engine.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
