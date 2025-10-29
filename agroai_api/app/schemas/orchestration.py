"""Orchestration schemas."""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ApplyControllerRequest(BaseModel):
    """Apply irrigation command to controller."""
    start_time: datetime
    duration_min: float = Field(..., gt=0)
    zone_ids: Optional[list] = None
    meta_data: Optional[dict] = None


class ApplyControllerResponse(BaseModel):
    """Controller apply response."""
    schedule_id: str
    status: str = "pending"
    provider: str
    provider_schedule_id: Optional[str] = None


class CancelScheduleResponse(BaseModel):
    """Cancel schedule response."""
    schedule_id: str
    status: str
    cancelled_at: datetime
