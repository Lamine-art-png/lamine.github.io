"""Telemetry schemas."""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TelemetryType(str, Enum):
    """Allowed telemetry types."""
    SOIL_VWC = "soil_vwc"
    ET0 = "et0"
    WEATHER = "weather"
    FLOW = "flow"
    VALVE_STATE = "valve_state"


class TelemetryRecord(BaseModel):
    """Single telemetry record."""
    type: TelemetryType
    timestamp: datetime
    value: float
    unit: Optional[str] = None
    source: Optional[str] = None
    meta_data: Optional[dict] = None


class IngestTelemetryRequest(BaseModel):
    """Batch telemetry ingestion request."""
    records: List[TelemetryRecord] = Field(..., min_length=1, max_length=1000)


class IngestTelemetryResponse(BaseModel):
    """Telemetry ingestion response."""
    accepted: int
    rejected: int = 0
    errors: Optional[List[str]] = None
