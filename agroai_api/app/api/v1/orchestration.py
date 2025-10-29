"""Orchestration endpoints for controller management."""
import logging
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.base import get_db
from app.core.security import get_current_tenant_id
from app.schemas.orchestration import (
    ApplyControllerRequest,
    ApplyControllerResponse,
    CancelScheduleResponse,
)
from app.models.schedule import Schedule
from app.adapters.registry import AdapterRegistry
from app.services.audit import AuditService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/controllers/{controller_id}:apply",
    response_model=ApplyControllerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def apply_controller(
    controller_id: str,
    request: ApplyControllerRequest,
    provider: str = "wiseconn",  # Query param or from controller config
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Apply irrigation schedule to controller.

    Routes to appropriate adapter (WiseConn, Rain Bird, etc.) based on provider.
    """
    # Get adapter
    adapter = AdapterRegistry.get_adapter(provider)

    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider: {provider}"
        )

    try:
        # Apply via adapter
        result = await adapter.apply_schedule(
            controller_id=controller_id,
            start_time=request.start_time,
            duration_min=request.duration_min,
            zone_ids=request.zone_ids,
            metadata=request.meta_data,
        )

        # Save schedule
        schedule = Schedule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            controller_id=controller_id,
            start_time=request.start_time,
            duration_min=request.duration_min,
            status="pending",
            provider=provider,
            provider_schedule_id=result.get("provider_schedule_id"),
            metadata=request.meta_data,
        )

        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        # Audit log
        AuditService.log(
            db=db,
            tenant_id=tenant_id,
            action="apply",
            resource_type="controller",
            resource_id=controller_id,
            status="success",
            details={
                "schedule_id": schedule.id,
                "provider": provider,
                "duration_min": request.duration_min,
            }
        )

        return ApplyControllerResponse(
            schedule_id=schedule.id,
            status=schedule.status,
            provider=provider,
            provider_schedule_id=result.get("provider_schedule_id"),
        )

    except Exception as e:
        logger.error(f"Failed to apply controller schedule: {e}")

        # Audit log failure
        AuditService.log(
            db=db,
            tenant_id=tenant_id,
            action="apply",
            resource_type="controller",
            resource_id=controller_id,
            status="failure",
            details={"error": str(e)}
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply schedule: {str(e)}"
        )


@router.post(
    "/schedules/{schedule_id}:cancel",
    response_model=CancelScheduleResponse,
)
async def cancel_schedule(
    schedule_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Cancel an irrigation schedule.
    """
    # Get schedule
    schedule = db.query(Schedule).filter(
        and_(
            Schedule.id == schedule_id,
            Schedule.tenant_id == tenant_id,
        )
    ).first()

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )

    if schedule.status in ["completed", "cancelled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Schedule already {schedule.status}"
        )

    # Get adapter and cancel
    adapter = AdapterRegistry.get_adapter(schedule.provider)

    if adapter and schedule.provider_schedule_id:
        try:
            await adapter.cancel_schedule(
                schedule.controller_id,
                schedule.provider_schedule_id
            )
        except Exception as e:
            logger.error(f"Failed to cancel via adapter: {e}")

    # Update schedule
    schedule.status = "cancelled"
    schedule.cancelled_at = datetime.utcnow()
    db.commit()

    # Audit log
    AuditService.log(
        db=db,
        tenant_id=tenant_id,
        action="cancel",
        resource_type="schedule",
        resource_id=schedule_id,
        status="success",
    )

    return CancelScheduleResponse(
        schedule_id=schedule_id,
        status="cancelled",
        cancelled_at=schedule.cancelled_at,
    )
