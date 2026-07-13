"""Orchestration endpoints for controller management."""
from __future__ import annotations

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

WISECONN_WRITE_METADATA_GATES = (
    "customer_authorized",
    "mapping_confirmed",
    "write_scope_verified",
    "water_budget_checked",
    "safety_window_checked",
)


def _controller_write_gates(provider: str, request: ApplyControllerRequest) -> tuple[bool, list[str], dict[str, bool]]:
    """Return whether a legacy controller write is allowed.

    This route predates the newer `/v1/controllers/execution/prepare` safety
    packet. Keep it safe by default: every call becomes an auditable approval
    packet unless the WiseConn schedule-write hard gates are explicitly present.
    """
    metadata = request.meta_data or {}
    checks = {
        "provider_is_wiseconn": provider == "wiseconn",
        "dry_run_false": metadata.get("dry_run") is False,
        "approval_confirmed": metadata.get("approval_confirmed") is True,
        "zone_id_present": bool(request.zone_ids and request.zone_ids[0]),
        "duration_minutes_present": request.duration_min > 0,
        **{name: metadata.get(name) is True for name in WISECONN_WRITE_METADATA_GATES},
    }
    missing = [name for name, ok in checks.items() if not ok]
    return not missing, missing, checks


@router.post(
    "/controllers/{controller_id}:apply",
    response_model=ApplyControllerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def apply_controller(
    controller_id: str,
    request: ApplyControllerRequest,
    provider: str = "wiseconn",
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Prepare or apply an irrigation schedule to a controller.

    Industrial-control safety rule: this endpoint does not touch physical
    infrastructure unless the caller supplies all WiseConn write gates. For every
    other provider or missing gate, it records an approval-required schedule and
    audit event instead of issuing a provider command.
    """
    write_allowed, missing_gates, gate_checks = _controller_write_gates(provider, request)

    if not write_allowed:
        schedule = Schedule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            controller_id=controller_id,
            start_time=request.start_time,
            duration_min=request.duration_min,
            status="pending",
            provider=provider,
            provider_schedule_id=None,
            meta_data={
                **(request.meta_data or {}),
                "dry_run": True,
                "approval_required": True,
                "missing_hard_gates": missing_gates,
                "hard_gate_checks": gate_checks,
                "physical_execution_performed": False,
            },
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
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
                "zone_ids": request.zone_ids or [],
                "missing_hard_gates": missing_gates,
                "approval_required": True,
                "physical_execution_performed": False,
            },
        )
        return ApplyControllerResponse(
            schedule_id=schedule.id,
            status=schedule.status,
            provider=provider,
            provider_schedule_id=None,
        )

    adapter = AdapterRegistry.get_adapter(provider)

    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider: {provider}",
        )

    try:
        result = await adapter.apply_schedule(
            controller_id=controller_id,
            start_time=request.start_time,
            duration_min=request.duration_min,
            zone_ids=request.zone_ids,
            metadata={**(request.meta_data or {}), "physical_execution_performed": True},
        )

        schedule = Schedule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            controller_id=controller_id,
            start_time=request.start_time,
            duration_min=request.duration_min,
            status="pending",
            provider=provider,
            provider_schedule_id=result.get("provider_schedule_id"),
            meta_data={**(request.meta_data or {}), "physical_execution_performed": True},
        )

        db.add(schedule)
        db.commit()
        db.refresh(schedule)

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
                "physical_execution_performed": True,
            },
        )

        return ApplyControllerResponse(
            schedule_id=schedule.id,
            status=schedule.status,
            provider=provider,
            provider_schedule_id=result.get("provider_schedule_id"),
        )

    except Exception as e:
        logger.error("Failed to apply controller schedule: %s", e)

        AuditService.log(
            db=db,
            tenant_id=tenant_id,
            action="apply",
            resource_type="controller",
            resource_id=controller_id,
            status="failure",
            details={"error": str(e), "physical_execution_performed": False},
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply schedule: {str(e)}",
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
    schedule = db.query(Schedule).filter(
        and_(
            Schedule.id == schedule_id,
            Schedule.tenant_id == tenant_id,
        )
    ).first()

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found",
        )

    if schedule.status in ["completed", "cancelled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Schedule already {schedule.status}",
        )

    adapter = AdapterRegistry.get_adapter(schedule.provider)

    if adapter and schedule.provider_schedule_id:
        try:
            await adapter.cancel_schedule(
                schedule.controller_id,
                schedule.provider_schedule_id,
            )
        except Exception as e:
            logger.error("Failed to cancel via adapter: %s", e)

    schedule.status = "cancelled"
    schedule.cancelled_at = datetime.utcnow()
    db.commit()

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
