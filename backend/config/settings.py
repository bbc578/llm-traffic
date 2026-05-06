"""
Configuration settings for the LLM-Traffic project.
"""
import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
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
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
if not LLM_API_KEY:
    raise EnvironmentError("LLM_API_KEY environment variable is not set. Please set it before running the application.")
LLM_MODEL = os.environ.get("LLM_MODEL", "mimo-v2.5-pro")

# Default phase definitions (typical 4-phase intersection)
DEFAULT_PHASES = [
    {"phase": 0, "description": "North-South Green", "duration": 30},
    {"phase": 1, "description": "North-South Yellow", "duration": 3},
    {"phase": 2, "description": "East-West Green", "duration": 30},
    {"phase": 3, "description": "East-West Yellow", "duration": 3},
]

# ── GRID6 configuration ──────────────────────────────────────────────────────
GRID6_CONFIG = str(DATA_DIR / "grid6.net.xml")
GRID6_ROUTES = str(DATA_DIR / "grid6.rou.xml")
GRID6_TLS = str(DATA_DIR / "grid6.tll.xml")

# Intersection IDs in the 6-intersection grid (3x2 layout)
GRID6_INTERSECTION_IDS = [
    "center00", "center01",
    "center10", "center11",
    "center20", "center21",
]

# Phase definitions per intersection (4-phase: NS-green, NS-yellow, EW-green, EW-yellow)
GRID6_PHASES_PER_INTERSECTION = [
    {"phase": 0, "description": "N-S Green",  "duration": 30},
    {"phase": 1, "description": "N-S Yellow", "duration": 3},
    {"phase": 2, "description": "E-W Green",  "duration": 30},
    {"phase": 3, "description": "E-W Yellow", "duration": 3},
]

# Default traffic volumes for GRID6 (vehicles/hour per direction per intersection)
GRID6_DEFAULT_VOLUMES = {
    "north": 500,
    "south": 500,
    "east":  500,
    "west":  500,
}

# Signal timing constraints for GRID6
GRID6_MIN_GREEN = 10   # seconds
GRID6_MAX_GREEN = 60   # seconds
GRID6_YELLOW_TIME = 3  # seconds
GRID6_MIN_CYCLE = 30   # seconds
GRID6_MAX_CYCLE = 180  # seconds

# Algorithm defaults
ALGORITHM_SATURATION_FLOW = 1800  # veh/hr per lane
ALGORITHM_DEFAULT_CYCLE = 60      # seconds
