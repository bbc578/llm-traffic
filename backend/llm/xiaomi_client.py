"""
LLM client for traffic signal optimization using OpenAI-compatible API.
"""
import json
import logging
import re
from typing import Dict, Optional

try:
    from backend.config.settings import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
except ImportError:
    from config.settings import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert traffic engineer optimizing signal timing at a 4-way intersection.
The intersection has 4 phases:
- Phase 0: North-South Green (vehicles from north and south can pass)
- Phase 1: North-South Yellow (transition)
- Phase 2: East-West Green (vehicles from east and west can pass)
- Phase 3: East-West Yellow (transition)

You must respond with a JSON object containing:
1. "phase_durations": an object mapping phase number to recommended duration in seconds (integers, yellow phases should be 3-5 seconds, green phases 10-90 seconds)
2. "reasoning": a brief explanation of your recommendation

Example response:
{"phase_durations": {"0": 30, "1": 3, "2": 25, "3": 3}, "reasoning": "North-south has heavier traffic, so longer green phase allocated."}
"""

USER_PROMPT_TEMPLATE = """Current traffic state at the intersection:

Direction    | Vehicle Count | Queue Length | Avg Speed (m/s) | Waiting Time (s)
-------------|---------------|-------------|-----------------|------------------
North        | {n_count}     | {n_queue}   | {n_speed}       | {n_wait}
South        | {s_count}     | {s_queue}   | {s_speed}       | {s_wait}
East         | {e_count}     | {e_queue}   | {e_speed}       | {e_wait}
West         | {w_count}     | {w_queue}   | {w_speed}       | {w_wait}

Total vehicles in simulation: {total}
Current simulation time: {sim_time}s
Current phase: {current_phase}

Analyze the traffic congestion and recommend optimal signal timing.
Respond ONLY with a JSON object containing "phase_durations" and "reasoning"."""


class LLMClient:
    """Client for communicating with OpenAI-compatible LLM APIs."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        self.base_url = base_url or LLM_BASE_URL
        self.api_key = api_key or LLM_API_KEY
        self.model = model or LLM_MODEL

    def get_recommendation(self, traffic_state: Dict) -> Dict:
        """
        Analyze traffic state and return signal timing recommendation.
        
        Args:
            traffic_state: Dict with keys matching get_traffic_state() output
            
        Returns:
            Dict with 'phase_durations' (Dict[int,int]) and 'reasoning' (str)
        """
        try:
            # Build the prompt from traffic state
            vc = traffic_state.get("vehicle_counts", {})
            ql = traffic_state.get("queue_lengths", {})
            sp = traffic_state.get("avg_speeds", {})
            wt = traffic_state.get("avg_waiting_times", {})

            user_msg = USER_PROMPT_TEMPLATE.format(
                n_count=vc.get("north", 0), n_queue=ql.get("north", 0),
                n_speed=sp.get("north", 0), n_wait=wt.get("north", 0),
                s_count=vc.get("south", 0), s_queue=ql.get("south", 0),
                s_speed=sp.get("south", 0), s_wait=wt.get("south", 0),
                e_count=vc.get("east", 0), e_queue=ql.get("east", 0),
                e_speed=sp.get("east", 0), e_wait=wt.get("east", 0),
                w_count=vc.get("west", 0), w_queue=ql.get("west", 0),
                w_speed=sp.get("west", 0), w_wait=wt.get("west", 0),
                total=traffic_state.get("total_vehicles", 0),
                sim_time=traffic_state.get("time", 0),
                current_phase=traffic_state.get("current_phase", 0),
            )

            response_text = self._call_llm(user_msg)
            return self._parse_response(response_text)

        except Exception as e:
            logger.error(f"LLM recommendation error: {e}")
            # Return default recommendation on failure
            return {
                "phase_durations": {0: 30, 1: 3, 2: 30, 3: 3},
                "reasoning": f"Default timing used due to LLM error: {e}",
                "raw_response": "",
            }

    def _call_llm(self, user_message: str) -> str:
        """Call the LLM API and return the response text."""
        try:
            import httpx
        except ImportError:
            raise RuntimeError("httpx package required. Install with: pip install httpx")

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
            "max_tokens": 500,
        }

        logger.info(f"Calling LLM ({self.model}) at {url}")
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        logger.info(f"LLM response: {content[:200]}")
        return content

    def _parse_response(self, response_text: str) -> Dict:
        """Parse the LLM response to extract phase durations and reasoning."""
        # Try to extract JSON from the response
        json_match = re.search(r'\{[^{}]*"phase_durations"[^{}]*\{[^}]*\}[^{}]*\}', response_text, re.DOTALL)
        
        if not json_match:
            # Try a broader match
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)

        if json_match:
            try:
                parsed = json.loads(json_match.group())
                phase_durations = {}
                raw_pd = parsed.get("phase_durations", {})
                for k, v in raw_pd.items():
                    phase_durations[int(k)] = int(v)
                
                # Validate: ensure all 4 phases present, clamped
                defaults = {0: 30, 1: 3, 2: 30, 3: 3}
                for phase_idx in range(4):
                    if phase_idx not in phase_durations:
                        phase_durations[phase_idx] = defaults[phase_idx]
                    else:
                        if phase_idx in (1, 3):  # yellow phases
                            phase_durations[phase_idx] = max(3, min(5, phase_durations[phase_idx]))
                        else:  # green phases
                            phase_durations[phase_idx] = max(10, min(90, phase_durations[phase_idx]))

                return {
                    "phase_durations": phase_durations,
                    "reasoning": parsed.get("reasoning", ""),
                    "raw_response": response_text,
                }
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse LLM JSON: {e}")

        logger.warning("Could not extract valid JSON from LLM response, using defaults.")
        return {
            "phase_durations": {0: 30, 1: 3, 2: 30, 3: 3},
            "reasoning": f"Default timing used. Raw response: {response_text[:200]}",
            "raw_response": response_text,
        }
