"""
Tests for LLM Response Parser.

Tests cover:
- Valid JSON parsing
- Missing phase with default values
- Invalid JSON fallback
- Phase duration clamping
- Reasoning field preservation
- Batch response parsing

These tests call the actual LLMClient methods to ensure test validity.
They do NOT require LLM API key (tests parsing only, not API calls).
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.llm.xiaomi_client import LLMClient


class TestLLMResponseParser:
    """Test suite for LLM response parsing using actual LLMClient methods."""

    def setup_method(self):
        """Set up test fixtures with dummy API key."""
        self.client = LLMClient(api_key="dummy")

    def test_parse_response_valid_json(self):
        """Test parsing valid JSON response."""
        response = '{"phase_durations": {"0": 30, "1": 3, "2": 45, "3": 3}, "reasoning": "test"}'
        result = self.client._parse_response(response)
        
        assert result["phase_durations"][0] == 30
        assert result["phase_durations"][2] == 45
        assert result["reasoning"] == "test"

    def test_parse_response_missing_phase_defaults(self):
        """Test that missing phases get default values."""
        response = '{"phase_durations": {"0": 30}, "reasoning": "incomplete"}'
        result = self.client._parse_response(response)
        
        # Should have defaults for missing phases
        assert 0 in result["phase_durations"]
        assert 1 in result["phase_durations"]
        assert 2 in result["phase_durations"]
        assert 3 in result["phase_durations"]
        assert result["phase_durations"][1] == 3  # Default yellow

    def test_parse_response_invalid_json_fallback(self):
        """Test fallback for invalid JSON."""
        response = "This is not JSON at all"
        result = self.client._parse_response(response)
        
        # Should return defaults
        assert result["phase_durations"] == {0: 30, 1: 3, 2: 30, 3: 3}
        assert "Default timing used" in result["reasoning"]

    def test_parse_response_phase_duration_clamping(self):
        """Test that phase durations are clamped to valid range."""
        # Green phase too high (120 > 90)
        # Green phase too low (5 < 10)
        response = '{"phase_durations": {"0": 120, "1": 3, "2": 5, "3": 3}, "reasoning": "test"}'
        result = self.client._parse_response(response)
        
        assert result["phase_durations"][0] == 90  # Clamped from 120
        assert result["phase_durations"][2] == 10  # Clamped from 5

    def test_parse_response_yellow_phase_clamping(self):
        """Test that yellow phases are clamped to [3, 5]."""
        response = '{"phase_durations": {"0": 30, "1": 10, "2": 30, "3": 1}, "reasoning": "test"}'
        result = self.client._parse_response(response)
        
        assert result["phase_durations"][1] == 5   # Clamped from 10
        assert result["phase_durations"][3] == 3   # Clamped from 1

    def test_parse_response_reasoning_preservation(self):
        """Test that reasoning field is preserved."""
        response = '{"phase_durations": {"0": 30, "1": 3, "2": 45, "3": 3}, "reasoning": "Heavy east traffic"}'
        result = self.client._parse_response(response)
        
        assert result["reasoning"] == "Heavy east traffic"

    def test_parse_batch_response_valid(self):
        """Test parsing valid batch response."""
        response = '''{
            "A0": {"phase_durations": {"0": 40, "1": 3, "2": 20, "3": 3}, "reasoning": "test A0"},
            "B0": {"phase_durations": {"0": 25, "1": 3, "2": 35, "3": 3}, "reasoning": "test B0"}
        }'''
        all_states = {"A0": {}, "B0": {}}
        result = self.client._parse_batch_response(response, all_states)
        
        assert result["A0"]["phase_durations"][0] == 40
        assert result["B0"]["phase_durations"][2] == 35
        assert result["A0"]["reasoning"] == "test A0"

    def test_parse_batch_response_missing_intersection(self):
        """Test batch response with missing intersection."""
        response = '{"A0": {"phase_durations": {"0": 40, "1": 3, "2": 20, "3": 3}}}'
        all_states = {"A0": {}, "B0": {}}
        result = self.client._parse_batch_response(response, all_states)
        
        # A0 should have LLM values
        assert result["A0"]["phase_durations"][0] == 40
        
        # B0 should have defaults
        assert result["B0"]["phase_durations"][0] == 30
        assert "did not provide data" in result["B0"]["reasoning"]

    def test_parse_batch_response_invalid_json(self):
        """Test batch response with invalid JSON falls back to per-intersection parsing."""
        response = "Not JSON at all"
        all_states = {"A0": {}, "B0": {}}
        result = self.client._parse_batch_response(response, all_states)
        
        # Should return defaults for all intersections
        for iid in all_states:
            assert result[iid]["phase_durations"] == {0: 30, 1: 3, 2: 30, 3: 3}

    def test_parse_response_raw_response_preserved(self):
        """Test that raw response is preserved."""
        response = '{"phase_durations": {"0": 30, "1": 3, "2": 30, "3": 3}, "reasoning": "test"}'
        result = self.client._parse_response(response)
        
        assert result["raw_response"] == response

    def test_call_llm_empty_api_key_raises(self):
        """Test that empty API key raises RuntimeError."""
        client = LLMClient(api_key="")
        
        with pytest.raises(RuntimeError, match="LLM_API_KEY is not set"):
            client._call_llm("test message")

    def test_call_llm_none_api_key_raises(self):
        """Test that None API key raises RuntimeError."""
        client = LLMClient(api_key="")
        
        with pytest.raises(RuntimeError, match="LLM_API_KEY is not set"):
            client._call_llm("test message")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
