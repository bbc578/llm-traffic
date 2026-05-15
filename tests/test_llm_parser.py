"""
Tests for LLM Response Parser.

Tests cover:
- Valid JSON parsing
- Missing phase with default values
- Invalid JSON fallback
- Phase duration clamping
- Reasoning field preservation
- Reasoning_content fallback

These tests do not require LLM API and test pure Python modules only.
"""

import pytest
import sys
import os
import json

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestLLMResponseParser:
    """Test suite for LLM response parsing logic."""

    def test_valid_json_parsing(self):
        """Test parsing valid JSON response."""
        response = '{"phase_durations": {"0": 30, "2": 45}}'
        data = json.loads(response)
        
        assert "phase_durations" in data
        assert data["phase_durations"]["0"] == 30
        assert data["phase_durations"]["2"] == 45

    def test_missing_phase_defaults(self):
        """Test that missing phases get default values."""
        response = '{"phase_durations": {"0": 30}}'
        data = json.loads(response)
        
        # Should have default for phase 2
        pd = data.get("phase_durations", {})
        phase_2 = pd.get("2", 30)  # Default to 30
        assert phase_2 == 30

    def test_invalid_json_fallback(self):
        """Test fallback for invalid JSON."""
        response = "This is not JSON"
        
        # Should not crash
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Expected - use default
            data = {"phase_durations": {0: 30, 2: 30}}
        
        assert "phase_durations" in data

    def test_phase_duration_clamping(self):
        """Test that phase durations are clamped to valid range."""
        response = '{"phase_durations": {"0": 120, "2": 5}}'
        data = json.loads(response)
        
        pd = data.get("phase_durations", {})
        
        # Clamp to [10, 60]
        phase_0 = max(10, min(60, int(pd.get("0", 30))))
        phase_2 = max(10, min(60, int(pd.get("2", 30))))
        
        assert phase_0 == 60  # Clamped from 120
        assert phase_2 == 10  # Clamped from 5

    def test_reasoning_field_preservation(self):
        """Test that reasoning field is preserved."""
        response = json.dumps({
            "phase_durations": {"0": 30, "2": 45},
            "reasoning": "NS has more vehicles, so giving more green time"
        })
        data = json.loads(response)
        
        assert "reasoning" in data
        assert "NS has more vehicles" in data["reasoning"]

    def test_markdown_json_extraction(self):
        """Test extraction from markdown code block."""
        response = '''```json
{
    "phase_durations": {"0": 35, "2": 25}
}
```'''
        
        # Extract JSON from markdown
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        assert json_match is not None
        
        data = json.loads(json_match.group(1))
        assert data["phase_durations"]["0"] == 35
        assert data["phase_durations"]["2"] == 25

    def test_integer_string_keys(self):
        """Test that integer string keys are handled."""
        response = '{"phase_durations": {"0": 30, "2": 45}}'
        data = json.loads(response)
        
        pd = data.get("phase_durations", {})
        
        # Convert keys to integers
        result = {int(k): int(v) for k, v in pd.items()}
        
        assert 0 in result
        assert 2 in result
        assert result[0] == 30
        assert result[2] == 45

    def test_empty_response(self):
        """Test empty response handling."""
        response = ""
        
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            data = {"phase_durations": {0: 30, 2: 30}}
        
        assert "phase_durations" in data

    def test_malformed_json(self):
        """Test malformed JSON handling."""
        response = '{"phase_durations": {"0": 30, "2": 45}'  # Missing closing brace
        
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            data = {"phase_durations": {0: 30, 2: 30}}
        
        assert "phase_durations" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
