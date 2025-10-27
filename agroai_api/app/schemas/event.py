"""Event schemas."""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class EventRecord(BaseModel):
    """Single event record."""
    type: str = Field(..., min_length=1)
    timestamp: datetime
    event_data: Optional[dict] = None
    source: Optional[str] = None


class IngestEventsRequest(BaseModel):
    """Batch event ingestion request."""
    records: List[EventRecord] = Field(..., min_length=1, max_length=1000)


class IngestEventsResponse(BaseModel):
    """Event ingestion response."""
    accepted: int
    rejected: int = 0
    errors: Optional[List[str]] = None
