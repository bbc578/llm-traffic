"""
Configuration settings for the LLM-Traffic project.
"""
import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path("/root/llm-traffic")
DATA_DIR = PROJECT_ROOT / "data"

# SUMO configuration
SUMO_BINARY = "/usr/bin/sumo"
SUMO_HOME = os.environ.get("SUMO_HOME", "/usr/share/sumo")
SUMO_CONFIG = str(DATA_DIR / "cross_intersection.sumocfg")

# Traffic light ID in the network
TLS_ID = "center"

# Edge names for incoming lanes
EDGES = {
    "north": "E_N_in",
    "south": "E_S_in",
    "east": "E_E_in",
    "west": "E_W_in",
}

# Default simulation parameters
DEFAULT_SIM_DURATION = 3600  # seconds
DEFAULT_STEP_LENGTH = 1     # seconds
LLM_CALL_INTERVAL = 30      # Call LLM every N simulation seconds

# LLM configuration (OpenAI-compatible API)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "your-api-key-here")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4")

# Default phase definitions (typical 4-phase intersection)
DEFAULT_PHASES = [
    {"phase": 0, "description": "North-South Green", "duration": 30},
    {"phase": 1, "description": "North-South Yellow", "duration": 3},
    {"phase": 2, "description": "East-West Green", "duration": 30},
    {"phase": 3, "description": "East-West Yellow", "duration": 3},
]
