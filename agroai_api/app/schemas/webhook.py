"""Webhook schemas."""
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
from datetime import datetime


class RegisterWebhookRequest(BaseModel):
    """Register webhook request."""
    url: HttpUrl
    event_types: List[str] = Field(..., min_length=1)
    secret: Optional[str] = None


class RegisterWebhookResponse(BaseModel):
    """Register webhook response."""
    id: str
    url: str
    event_types: List[str]
    active: bool = True
    created_at: datetime


class TestWebhookResponse(BaseModel):
    """Test webhook response."""
    event_id: str
    event_type: str = "test.event"
    payload: dict
    signature: str
    timestamp: datetime


class WebhookEvent(BaseModel):
    """Webhook event payload."""
    id: str
    type: str
    timestamp: datetime
    data: dict
    tenant_id: str
