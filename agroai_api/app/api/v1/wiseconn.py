"""WiseConn integration API endpoints.

These endpoints expose the WiseConn read and write paths via AGRO-AI's API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.db.base import get_db
from app.services.wiseconn_sync import WiseConnSyncService

router = APIRouter(prefix="/wiseconn", tags=["wiseconn"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AuthCheckResponse(BaseModel):
    authenticated: bool
    api_url: str
    message: str


class DiscoveryResponse(BaseModel):
    farms: List[Dict[str, Any]]
    total_zones: int
    total_measures: int
    errors: List[str]


class IngestRequest(BaseModel):
    zone_id: str
    days: int = Field(14, ge=1, le=90)


class IngestResponse(BaseModel):
    zone_id: str
    measures_processed: int
    points_ingested: int
    points_skipped: int
    errors: List[str]


class CreateIrrigationRequest(BaseModel):
    zone_id: str
    duration_minutes: int = Field(1, ge=1, le=60)
    start_offset_hours: int = Field(24, ge=1, le=168)


class IrrigationResponse(BaseModel):
    zone_id: str
    start_time: str
    duration_minutes: int
    status: str
    provider_response: Optional[Dict[str, Any]] = None
    verification: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class FullSyncResponse(BaseModel):
    started_at: str
    completed_at: Optional[str] = None
    discovery: Optional[Dict[str, Any]] = None
    blocks_created: List[Dict[str, Any]]
    telemetry: List[Dict[str, Any]]
    irrigations: List[Dict[str, Any]]
    errors: List[str]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_sync_service(db: Session = Depends(get_db)) -> WiseConnSyncService:
    adapter = AdapterRegistry.get_wiseconn()
    return WiseConnSyncService(adapter=adapter, db=db)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/auth", response_model=AuthCheckResponse)
async def check_auth():
    """Verify WiseConn API authentication."""
    adapter = AdapterRegistry.get_wiseconn()
    try:
        ok = await adapter.check_auth()
        return AuthCheckResponse(
            authenticated=ok,
            api_url=adapter.api_url,
            message="Authentication successful" if ok else "Authentication failed",
        )
    except Exception as e:
        return AuthCheckResponse(
            authenticated=False,
            api_url=adapter.api_url,
            message=f"Auth check error: {str(e)}",
        )


@router.get("/discover", response_model=DiscoveryResponse)
async def discover(db: Session = Depends(get_db)):
    """Discover farms, zones, and measures from WiseConn."""
    svc = _get_sync_service(db)
    result = await svc.discover_all()
    return DiscoveryResponse(**result)


@router.get("/farms", response_model=List[Dict[str, Any]])
async def list_farms():
    """List farms from WiseConn API."""
    adapter = AdapterRegistry.get_wiseconn()
    return await adapter.list_farms()


@router.get("/farms/{farm_id}/zones", response_model=List[Dict[str, Any]])
async def list_zones(farm_id: str):
    """List zones for a WiseConn farm."""
    adapter = AdapterRegistry.get_wiseconn()
    return await adapter.list_zones(farm_id)


@router.get("/zones/{zone_id}/measures", response_model=List[Dict[str, Any]])
async def list_measures(zone_id: str):
    """List measures for a WiseConn zone."""
    adapter = AdapterRegistry.get_wiseconn()
    return await adapter.list_measures(zone_id)


@router.get("/measures/{measure_id}/data", response_model=List[Dict[str, Any]])
async def get_measure_data(
    measure_id: str,
    start: Optional[str] = Query(None, description="Start time ISO format"),
    end: Optional[str] = Query(None, description="End time ISO format"),
    hours: int = Query(24, description="Hours of data if start/end not provided"),
):
    """Get time-series data for a measure."""
    adapter = AdapterRegistry.get_wiseconn()
    now = datetime.utcnow()

    if start:
        start_time = datetime.fromisoformat(start)
    else:
        start_time = now - timedelta(hours=hours)

    if end:
        end_time = datetime.fromisoformat(end)
    else:
        end_time = now

    return await adapter.get_measure_data(measure_id, start_time, end_time)


@router.post("/ingest", response_model=IngestResponse)
async def ingest_telemetry(
    request: IngestRequest,
    db: Session = Depends(get_db),
):
    """Ingest historical telemetry for a zone into AGRO-AI."""
    svc = _get_sync_service(db)
    result = await svc.ingest_historical(
        zone_id=request.zone_id,
        days=request.days,
    )
    return IngestResponse(**result)


@router.get("/zones/{zone_id}/irrigations", response_model=List[Dict[str, Any]])
async def list_irrigations(
    zone_id: str,
    days: int = Query(14, ge=1, le=90),
):
    """List irrigation events for a zone."""
    adapter = AdapterRegistry.get_wiseconn()
    now = datetime.utcnow()
    return await adapter.list_irrigations(
        zone_id,
        start_time=now - timedelta(days=days),
        end_time=now,
    )


@router.post("/irrigations", response_model=IrrigationResponse)
async def create_irrigation(
    request: CreateIrrigationRequest,
    db: Session = Depends(get_db),
):
    """Create a test irrigation action in WiseConn demo environment.

    Designed for minimal impact: defaults to 1 minute, 24h from now.
    """
    svc = _get_sync_service(db)
    result = await svc.create_test_irrigation(
        zone_id=request.zone_id,
        duration_minutes=request.duration_minutes,
        start_offset_hours=request.start_offset_hours,
    )
    return IrrigationResponse(**result)


@router.post("/sync", response_model=FullSyncResponse)
async def full_sync(
    days: int = Query(14, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Run a full WiseConn sync: discover → ingest telemetry → ingest irrigations."""
    svc = _get_sync_service(db)
    result = await svc.full_sync(days=days)
    return FullSyncResponse(**result)
