"""Recommendation schemas."""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class IrrigationConstraints(BaseModel):
    """Irrigation constraints."""
    min_duration_min: Optional[float] = Field(None, ge=0)
    max_duration_min: Optional[float] = Field(None, ge=0)
    preferred_time_start: Optional[str] = None  # HH:MM format
    preferred_time_end: Optional[str] = None
    min_interval_hours: Optional[float] = Field(None, ge=0)


class IrrigationTargets(BaseModel):
    """Irrigation targets."""
    target_soil_vwc: Optional[float] = Field(None, ge=0, le=1)
    target_deficit_mm: Optional[float] = Field(None, ge=0)
    efficiency: Optional[float] = Field(0.85, ge=0, le=1)


class ComputeRecommendationRequest(BaseModel):
    """Request to compute irrigation recommendation."""
    constraints: Optional[IrrigationConstraints] = None
    targets: Optional[IrrigationTargets] = None
    horizon_hours: float = Field(72, ge=1, le=168)


class RecommendationResponse(BaseModel):
    """Irrigation recommendation response."""
    when: datetime
    duration_min: float
    volume_m3: float
    confidence: float = Field(..., ge=0, le=1)
    explanations: List[str]
    version: str

    class Config:
        from_attributes = True


class SimulateScenarioRequest(BaseModel):
    """Multi-block scenario simulation request."""
    block_ids: List[str]
    horizon_hours: float = Field(72, ge=1, le=168)
    constraints: Optional[IrrigationConstraints] = None
    targets: Optional[IrrigationTargets] = None
    overrides: Optional[dict] = None  # Per-block overrides


class SimulateScenarioResponse(BaseModel):
    """Scenario simulation response."""
    scenario_id: str
    recommendations: dict  # block_id -> RecommendationResponse
    total_volume_m3: float
    total_cost_estimate: Optional[float] = None
