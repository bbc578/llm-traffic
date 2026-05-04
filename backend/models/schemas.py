"""
Pydantic models for request/response schemas.
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DirectionStats(BaseModel):
    """Traffic statistics for a single direction."""
    vehicle_count: int = 0
    queue_length: int = 0
    avg_speed: float = 0.0
    avg_waiting_time: float = 0.0


class SimulationState(BaseModel):
    """Current state of the traffic simulation."""
    time: float = 0.0
    vehicle_counts: Dict[str, int] = Field(
        default_factory=lambda: {"north": 0, "south": 0, "east": 0, "west": 0}
    )
    queue_lengths: Dict[str, int] = Field(
        default_factory=lambda: {"north": 0, "south": 0, "east": 0, "west": 0}
    )
    avg_speeds: Dict[str, float] = Field(
        default_factory=lambda: {"north": 0.0, "south": 0.0, "east": 0.0, "west": 0.0}
    )
    avg_waiting_times: Dict[str, float] = Field(
        default_factory=lambda: {"north": 0.0, "south": 0.0, "east": 0.0, "west": 0.0}
    )
    current_phase: int = 0
    current_phase_duration: float = 0.0
    total_vehicles: int = 0
    is_running: bool = False


class LLMRecommendation(BaseModel):
    """LLM traffic signal recommendation."""
    phase_durations: Dict[int, int] = Field(
        default_factory=dict,
        description="Mapping of phase index to recommended duration in seconds"
    )
    reasoning: str = ""
    raw_response: str = ""


class SimulationConfig(BaseModel):
    """Configuration for starting a simulation."""
    duration: int = Field(default=3600, ge=1, le=86400, description="Simulation duration in seconds")
    traffic_volumes: Dict[str, int] = Field(
        default_factory=lambda: {"north": 500, "south": 500, "east": 500, "west": 500},
        description="Traffic volume per direction (vehicles/hour)"
    )
    llm_enabled: bool = Field(default=False, description="Enable LLM-based signal control")
    llm_call_interval: int = Field(default=30, ge=5, le=300, description="Seconds between LLM calls")
    step_length: int = Field(default=1, ge=1, le=10, description="Simulation step length in seconds")
    speed_factor: float = Field(default=5.0, ge=0.1, le=100.0, description="Simulation speed multiplier (1.0 = real-time, 10.0 = 10x faster)")


class PhaseRequest(BaseModel):
    """Request to manually set traffic light phase."""
    phase_index: int = Field(ge=0, description="Phase index to activate")
    duration: int = Field(default=30, ge=1, le=120, description="Duration of the phase in seconds")
