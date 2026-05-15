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

SYSTEM_PROMPT = """You are a traffic signal optimizer. Respond ONLY with valid JSON. No markdown, no explanation outside JSON.

Format: {"id": {"phase_durations": {"0": NS_green, "1": 3, "2": EW_green, "3": 3}, "reasoning": "<=30 words"}}
- Phase 0 = NS green, Phase 1 = NS yellow (fixed 3s), Phase 2 = EW green, Phase 3 = EW yellow (fixed 3s)
- Green range: 10-90s. Longer queues/waiting → more green for that axis.

Examples:

Input: intersection_1: N:5veh/2q/10w S:4veh/1q/8w E:30veh/12q/45w W:25veh/10q/40w
Output: {"intersection_1": {"phase_durations": {"0": 20, "1": 3, "2": 55, "3": 3}, "reasoning": "Heavy east traffic (55veh, 22q) needs extended EW green"}}

Input: intersection_2: N:40veh/15q/60w S:35veh/12q/50w E:8veh/3q/15w W:6veh/2q/10w
Output: {"intersection_2": {"phase_durations": {"0": 65, "1": 3, "2": 15, "3": 3}, "reasoning": "North queue critical (27q, 60w wait) — prioritize NS green"}}

Input: intersection_3: N:20veh/8q/25w S:18veh/7q/22w E:22veh/9q/28w W:19veh/8q/24w
Output: {"intersection_3": {"phase_durations": {"0": 30, "1": 3, "2": 30, "3": 3}, "reasoning": "Balanced traffic across all directions — equal green splits"}}"""

USER_PROMPT_TEMPLATE = """Intersection state — N:{n_count}veh/{n_queue}q/{n_wait}w S:{s_count}veh/{s_queue}q/{s_wait}w E:{e_count}veh/{e_queue}q/{e_wait}w W:{w_count}veh/{w_queue}q/{w_wait}w | Total:{total} | Time:{sim_time}s | Phase:{current_phase}
Reply JSON only."""

BATCH_PROMPT_TEMPLATE = """Traffic snapshot at t={time}s. Each line: intersection_id: N/S/E/W stats (veh/queue/wait).

{intersections}

Output one JSON object with ALL intersection IDs. Reply JSON only."""


class LLMClient:
    """Client for communicating with OpenAI-compatible LLM APIs."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize the LLM client with connection parameters.

        Args:
            base_url: API base URL. Defaults to LLM_BASE_URL from settings.
            api_key: API authentication key. Defaults to LLM_API_KEY from settings.
            model: Model identifier string. Defaults to LLM_MODEL from settings.
        """
        self.base_url = base_url or LLM_BASE_URL
        self.api_key = api_key or LLM_API_KEY
        self.model = model or LLM_MODEL

    def get_batch_recommendation(self, all_states: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        Analyze traffic states for ALL intersections in one LLM call.

        Args:
            all_states: {intersection_id: traffic_state_dict, ...}

        Returns:
            {intersection_id: {"phase_durations": {...}, "reasoning": "..."}, ...}
        """
        try:
            # Build compact prompt
            lines = []
            for iid, ts in all_states.items():
                vc = ts.get("vehicle_counts", {})
                ql = ts.get("queue_lengths", {})
                wt = ts.get("avg_waiting_times", {})
                lines.append(
                    f"{iid}: N:{vc.get('north',0)}veh/{ql.get('north',0)}q/{wt.get('north',0)}w "
                    f"S:{vc.get('south',0)}veh/{ql.get('south',0)}q/{wt.get('south',0)}w "
                    f"E:{vc.get('east',0)}veh/{ql.get('east',0)}q/{wt.get('east',0)}w "
                    f"W:{vc.get('west',0)}veh/{ql.get('west',0)}q/{wt.get('west',0)}w"
                )
            user_msg = BATCH_PROMPT_TEMPLATE.format(
                time=list(all_states.values())[0].get("time", 0),
                intersections="\n".join(lines),
            )

            response_text = self._call_llm(user_msg)
            return self._parse_batch_response(response_text, all_states)

        except Exception as e:
            logger.error(f"LLM batch recommendation error: {e}")
            return {
                iid: {"phase_durations": {0: 30, 1: 3, 2: 30, 3: 3}, "reasoning": f"Default: {e}"}
                for iid in all_states
            }

    def _parse_batch_response(self, response_text: str, all_states: Dict[str, Dict]) -> Dict[str, Dict]:
        """Parse batch LLM response for multiple intersections."""
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                result = {}
                defaults = {0: 30, 1: 3, 2: 30, 3: 3}
                for iid in all_states:
                    entry = parsed.get(iid, parsed.get(iid.lower(), parsed.get(iid.upper(), {})))
                    if isinstance(entry, dict) and "phase_durations" in entry:
                        pd = {}
                        for k, v in entry["phase_durations"].items():
                            pd[int(k)] = int(v)
                        for phase_idx in range(4):
                            if phase_idx not in pd:
                                pd[phase_idx] = defaults[phase_idx]
                            elif phase_idx in (1, 3):
                                pd[phase_idx] = max(3, min(5, pd[phase_idx]))
                            else:
                                pd[phase_idx] = max(10, min(90, pd[phase_idx]))
                        result[iid] = {"phase_durations": pd, "reasoning": entry.get("reasoning", "")}
                    else:
                        result[iid] = {"phase_durations": dict(defaults), "reasoning": "LLM did not provide data for this intersection"}
                return result
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse batch LLM JSON: {e}")

        # Fallback: try per-intersection parsing
        return {
            iid: self._parse_response(response_text)
            for iid in all_states
        }

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
        """Call the LLM API and return the response text.

        Args:
            user_message: The user-role message to send to the LLM.

        Returns:
            The LLM response content as a string.

        Raises:
            RuntimeError: If the httpx package is not installed or API key is not set.
            httpx.HTTPStatusError: If the API returns a non-2xx status.
        """
        # Check if API key is set
        if not self.api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set. Set it only when running LLM-based strategies. "
                "Non-LLM strategies (fixed, random, webster, maxpressure, rl) work without it."
            )

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
            "max_tokens": 8000,  # reasoning models need large budget
        }

        logger.info(f"Calling LLM ({self.model}) at {url}")
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        msg = data["choices"][0]["message"]
        content = msg.get("content", "")
        # Reasoning models (mimo-v2.5-pro etc.) put thinking in reasoning_content
        # and may leave content empty. Fall back to reasoning_content if needed.
        if not content.strip():
            reasoning = msg.get("reasoning_content", "")
            if reasoning:
                logger.info("Content empty, using reasoning_content")
                content = reasoning
        logger.info(f"LLM response: {content[:200]}")
        return content

    def _parse_response(self, response_text: str) -> Dict:
        """Parse the LLM response to extract phase durations and reasoning.

        Args:
            response_text: Raw text response from the LLM.

        Returns:
            Dict with 'phase_durations' (Dict[int,int]), 'reasoning' (str),
            and 'raw_response' (str). Uses 30/3/30/3 defaults on parse failure.
        """
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
