"""Platform-admin operational surface for Field Intelligence.

Deliberately mounted on its own router WITHOUT the release gate: operators
must be able to inspect state and flip the kill switch precisely when the
feature is disabled. Every route requires the server-side platform-admin
allowlist; organization owners never see other organizations' data through
these endpoints.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform_admin
from app.core.config import settings
from app.db.base import get_db
from app.models.field_intelligence import (
    FieldObservation,
    FieldObservationAsset,
    FieldObservationAuditEvent,
    FieldStorageReservation,
)
from app.models.operational_records import IngestionJob
from app.models.saas import Organization, SecurityAuditEvent
from app.services import field_intelligence_rollout as rollout
from app.services.field_intelligence_worker import worker_status

router = APIRouter(prefix="/field-intelligence/admin", tags=["field-intelligence-admin"])


class KillSwitchRequest(BaseModel):
    active: bool
    reason: str | None = Field(default=None, max_length=500)


class ReleaseOverrideRequest(BaseModel):
    state: str | None = Field(default=None, max_length=20)
    reason: str | None = Field(default=None, max_length=500)


@router.get("/rollout")
def get_rollout(
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    return {"status": "ok", "rollout": rollout.rollout_status(db)}


@router.post("/kill-switch")
def post_kill_switch(
    payload: KillSwitchRequest,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    result = rollout.set_kill_switch(
        db, active=payload.active, actor_user_id=ctx.user.id, reason=payload.reason
    )
    return {"status": "ok", **result, "rollout": rollout.rollout_status(db)}


@router.post("/release-override")
def post_release_override(
    payload: ReleaseOverrideRequest,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = rollout.set_release_override(
            db, state=payload.state, actor_user_id=ctx.user.id, reason=payload.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return {"status": "ok", **result, "rollout": rollout.rollout_status(db)}


@router.get("/workers")
def get_workers(
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    return {"status": "ok", "workers": worker_status(db)}


@router.get("/audit")
def get_observation_audit(
    observation_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(default=100, ge=1, le=200),
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Return bounded, metadata-only append-only audit events for one observation."""
    rows = (
        db.query(FieldObservationAuditEvent)
        .filter(FieldObservationAuditEvent.observation_id == observation_id)
        .order_by(FieldObservationAuditEvent.created_at.asc())
        .limit(limit)
        .all()
    )
    return {
        "status": "ok",
        "observation_id": observation_id,
        "count": len(rows),
        "events": [
            {
                "id": row.id,
                "action": row.action,
                "actor_type": row.actor_type,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.get("/operations")
def get_operations(
    limit: int = 50,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Cross-organization operational overview (platform admins only)."""
    limit = max(1, min(int(limit), 200))
    live_asset_states = ["stored", "pending_deletion"]

    storage_rows = (
        db.query(
            FieldObservationAsset.tenant_id.label("tenant_id"),
            func.count(func.distinct(FieldObservationAsset.object_ref)).label("objects"),
            func.coalesce(func.sum(FieldObservationAsset.size_bytes), 0).label("bytes"),
        )
        .filter(FieldObservationAsset.status.in_(live_asset_states))
        .group_by(FieldObservationAsset.tenant_id)
        .order_by(func.coalesce(func.sum(FieldObservationAsset.size_bytes), 0).desc())
        .limit(limit)
        .all()
    )
    observation_counts = dict(
        db.query(FieldObservation.tenant_id, func.count(FieldObservation.id))
        .group_by(FieldObservation.tenant_id)
        .all()
    )
    failed_jobs = dict(
        db.query(IngestionJob.tenant_id, func.count(IngestionJob.id))
        .filter(IngestionJob.job_type.like("field_intelligence%"))
        .filter(IngestionJob.status == "failed")
        .group_by(IngestionJob.tenant_id)
        .all()
    )
    org_ids = [row.tenant_id for row in storage_rows]
    organizations = {
        org.id: org for org in db.query(Organization).filter(Organization.id.in_(org_ids)).all()
    } if org_ids else {}

    tenants = []
    for row in storage_rows:
        org = organizations.get(row.tenant_id)
        tenants.append({
            "organization_id": row.tenant_id,
            "organization_name": getattr(org, "name", None),
            "plan": getattr(org, "plan", None),
            "rollout_cohort": rollout.organization_cohort(db, org),
            "storage_objects": int(row.objects or 0),
            "storage_bytes": int(row.bytes or 0),
            "observations": int(observation_counts.get(row.tenant_id, 0)),
            "failed_jobs": int(failed_jobs.get(row.tenant_id, 0)),
        })

    stale_cutoff = datetime.utcnow() - timedelta(
        seconds=int(getattr(settings, "FIELD_STALE_JOB_ALERT_SECONDS", 900))
    )
    job_totals = {
        job_status: count
        for job_status, count in db.query(IngestionJob.status, func.count(IngestionJob.id))
        .filter(IngestionJob.job_type.like("field_intelligence%"))
        .group_by(IngestionJob.status)
        .all()
    }
    deletion_queue = (
        db.query(IngestionJob)
        .filter(IngestionJob.job_type == "field_intelligence_asset_delete")
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .count()
    )
    stale = (
        db.query(IngestionJob)
        .filter(IngestionJob.job_type.like("field_intelligence%"))
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .filter(IngestionJob.created_at <= stale_cutoff)
        .count()
    )
    reservations = db.query(func.count(FieldStorageReservation.id)).scalar() or 0
    audit = [
        {
            "event_type": event.event_type,
            "outcome": event.outcome,
            "user_id": event.user_id,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "metadata": event.metadata_json,
        }
        for event in db.query(SecurityAuditEvent)
        .filter(SecurityAuditEvent.event_type == "field_intelligence_rollout_change")
        .order_by(SecurityAuditEvent.created_at.desc())
        .limit(20)
        .all()
    ]
    return {
        "status": "ok",
        "rollout": rollout.rollout_status(db),
        "tenants": tenants,
        "jobs": {"totals": job_totals, "deletion_queue": deletion_queue, "stale": stale},
        "active_reservations": int(reservations),
        "recent_rollout_audit": audit,
        "workers": worker_status(db),
    }
