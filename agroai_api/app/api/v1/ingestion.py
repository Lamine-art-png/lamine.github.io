"""Ingestion API endpoints for telemetry and events."""
import logging
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.base import get_db
from app.core.security import get_current_tenant_id
from app.core import metrics
from app.schemas.telemetry import (
    IngestTelemetryRequest,
    IngestTelemetryResponse,
    TelemetryType,
)
from app.schemas.event import IngestEventsRequest, IngestEventsResponse
from app.models.telemetry import Telemetry
from app.models.event import Event
from app.models.block import Block

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/blocks/{block_id}/telemetry",
    response_model=IngestTelemetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_telemetry(
    block_id: str,
    request: IngestTelemetryRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Ingest telemetry data for a block.

    Accepts batch of telemetry records. Allows late/partial data.
    Types: soil_vwc | et0 | weather | flow | valve_state
    """
    # Verify block exists and belongs to tenant
    block = db.query(Block).filter(
        and_(Block.id == block_id, Block.tenant_id == tenant_id)
    ).first()

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_id} not found"
        )

    accepted = 0
    rejected = 0
    errors = []

    for record in request.records:
        try:
            telemetry = Telemetry(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                block_id=block_id,
                type=record.type.value,
                timestamp=record.timestamp,
                value=record.value,
                unit=record.unit,
                source=record.source,
                metadata=record.meta_data,
                ingested_at=datetime.utcnow(),
            )

            db.add(telemetry)
            accepted += 1

            # Record metrics
            metrics.ingestion_total.labels(
                tenant=tenant_id,
                type=record.type.value
            ).inc()

        except Exception as e:
            logger.error(f"Failed to ingest telemetry: {e}")
            rejected += 1
            errors.append(f"Record {record.timestamp}: {str(e)}")

    db.commit()

    return IngestTelemetryResponse(
        accepted=accepted,
        rejected=rejected,
        errors=errors if errors else None,
    )


@router.post(
    "/blocks/{block_id}/events",
    response_model=IngestEventsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_events(
    block_id: str,
    request: IngestEventsRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Ingest events for a block.

    Events: irrigation_start, irrigation_stop, alarm, valve_change, etc.
    """
    # Verify block exists and belongs to tenant
    block = db.query(Block).filter(
        and_(Block.id == block_id, Block.tenant_id == tenant_id)
    ).first()

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_id} not found"
        )

    accepted = 0
    rejected = 0
    errors = []

    for record in request.records:
        try:
            event = Event(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                block_id=block_id,
                type=record.type,
                timestamp=record.timestamp,
                data=record.event_data,
                source=record.source,
                ingested_at=datetime.utcnow(),
            )

            db.add(event)
            accepted += 1

            metrics.ingestion_total.labels(
                tenant=tenant_id,
                type=record.type
            ).inc()

        except Exception as e:
            logger.error(f"Failed to ingest event: {e}")
            rejected += 1
            errors.append(f"Event {record.type} at {record.timestamp}: {str(e)}")

    db.commit()

    return IngestEventsResponse(
        accepted=accepted,
        rejected=rejected,
        errors=errors if errors else None,
    )
