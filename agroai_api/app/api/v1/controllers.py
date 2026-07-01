"""Controller environment and execution-readiness endpoints for AGRO-AI."""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.api.v1.connectors import create_or_get_connection, ensure_schema, public_connection, safe_credential_ref, sanitize_config
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import IngestionJob

router = APIRouter(prefix="/controllers", tags=["controllers"])

ControllerStatus = Literal["live", "configured", "integration_ready"]
ProviderId = Literal["wiseconn", "talgil"]
ExecutionTier = Literal[
    "not_configured",
    "read_ready",
    "schedule_write_ready",
    "approval_gated",
    "blocked",
]


class ControllerEnvironment(BaseModel):
    source: str
    label: str
    status: ControllerStatus
    live: bool
    configured: bool
    farms: int = 0
    zones: int = 0
    notes: str
    sources: Dict[str, int] = Field(default_factory=dict)


class ControllerEnvironmentResponse(BaseModel):
    environments: List[ControllerEnvironment]
    totals: Dict[str, int]


class ControllerCustomerConnectRequest(BaseModel):
    provider: ProviderId
    workspace_id: str | None = None
    display_name: str | None = None
    connection_method: Literal["api_key", "provider_assisted", "export_upload", "demo"] = "api_key"
    account_hint: str | None = None
    api_key_present: bool = False
    enable_read_sync: bool = True
    request_write_access: bool = False
    human_approval_required: bool = True
    notes: str | None = None


class ControllerExecutionPrepareRequest(BaseModel):
    provider: ProviderId
    workspace_id: str | None = None
    controller_id: str | None = None
    zone_id: str | None = None
    command: Literal["schedule_irrigation", "cancel_schedule", "open_valve", "close_valve", "start_pump", "stop_pump"]
    start_time: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    provider_schedule_id: str | None = None
    reason: str
    requested_by: str | None = None
    approval_confirmed: bool = False
    dry_run: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


def _safe_job(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str | None,
    job_type: str,
    input_json: dict[str, Any],
    output_json: dict[str, Any],
    status_value: str = "completed",
) -> IngestionJob:
    job = IngestionJob(
        id=f"ctrl_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        job_type=job_type,
        status=status_value,
        input_json=input_json,
        output_json=output_json,
        completed_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _job_public(job: IngestionJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "input": job.input_json or {},
        "output": job.output_json or {},
    }


def _base_safeguards(provider: str) -> list[str]:
    return [
        "verified provider authentication",
        "customer-authorized connection record",
        "field/farm/zone mapping confirmed",
        "readback verification after provider write",
        "human approval before physical execution",
        "audit job persisted before execution",
        "dry-run default for all physical commands",
        f"{provider} provider-specific permissions checked",
    ]


async def _wiseconn_snapshot() -> dict[str, Any]:
    adapter = AdapterRegistry.get_wiseconn()
    live = False
    farms: list[dict[str, Any]] = []
    zones_by_farm: dict[str, list[dict[str, Any]]] = {}
    auth_error = None
    try:
        live = await adapter.check_auth()
        if live:
            farms = await adapter.list_farms()
            for farm in farms[:25]:
                farm_id = str(farm.get("id", ""))
                if farm_id:
                    zones_by_farm[farm_id] = await adapter.list_zones(farm_id)
    except Exception as exc:
        live = False
        auth_error = exc.__class__.__name__

    zones = [zone for rows in zones_by_farm.values() for zone in rows]
    return {
        "provider": "wiseconn",
        "configured": bool(getattr(adapter, "_api_key", None)),
        "live": live,
        "farms": farms,
        "zones": zones,
        "zone_sources": dict(Counter(str(zone.get("provider") or zone.get("source") or "unknown").lower() for zone in zones)),
        "auth_error": auth_error,
        "read_capability": live,
        "write_capability_declared": True,
        "write_capability_ready": live,
        "write_method": "POST /irrigations via WiseConn adapter" if live else None,
    }


async def _talgil_snapshot() -> dict[str, Any]:
    adapter = AdapterRegistry.get_talgil()
    configured = bool(adapter.configured)
    live = False
    targets = 0
    zones = 0
    notes = "TALGIL_API_KEY is not configured in this runtime."
    diagnostic = {}
    try:
        status_payload = await adapter.get_runtime_status(use_cache=False)
        configured = bool(status_payload.configured)
        live = bool(status_payload.live)
        targets = int(status_payload.targets)
        notes = status_payload.notes
        diagnostic = getattr(adapter, "last_diagnostic", None).__dict__ if getattr(adapter, "last_diagnostic", None) else {}
        if live:
            rows = await adapter.list_targets()
            for target in rows[:25]:
                try:
                    zones += len(await adapter.list_zones(str(target.get("id"))))
                except Exception:
                    continue
    except Exception as exc:
        notes = f"Talgil runtime status failed: {exc.__class__.__name__}"

    return {
        "provider": "talgil",
        "configured": configured,
        "live": live,
        "farms": targets,
        "zones": zones,
        "notes": notes,
        "diagnostic": diagnostic,
        "read_capability": live,
        "write_capability_declared": False,
        "write_capability_ready": False,
        "write_method": None,
    }


def _tier(snapshot: dict[str, Any]) -> ExecutionTier:
    if not snapshot.get("configured"):
        return "not_configured"
    if snapshot.get("write_capability_ready"):
        return "schedule_write_ready"
    if snapshot.get("read_capability"):
        return "read_ready"
    return "blocked"


def _readiness_card(snapshot: dict[str, Any]) -> dict[str, Any]:
    provider = snapshot["provider"]
    tier = _tier(snapshot)
    if provider == "talgil" and snapshot.get("read_capability") and not snapshot.get("write_capability_ready"):
        tier = "read_ready"
    return {
        "provider": provider,
        "configured": bool(snapshot.get("configured")),
        "live_read": bool(snapshot.get("read_capability")),
        "live_write": bool(snapshot.get("write_capability_ready")),
        "execution_tier": tier,
        "farms_or_targets": len(snapshot.get("farms", [])) if isinstance(snapshot.get("farms"), list) else int(snapshot.get("farms") or 0),
        "zones": len(snapshot.get("zones", [])) if isinstance(snapshot.get("zones"), list) else int(snapshot.get("zones") or 0),
        "write_method": snapshot.get("write_method"),
        "safe_default": "dry_run_and_approval_required",
        "approval_required_for_physical_execution": True,
        "safeguards": _base_safeguards(provider),
        "blocking_items": [
            item for item in [
                None if snapshot.get("configured") else "provider credentials/customer authorization missing",
                None if snapshot.get("read_capability") else "live read/auth check not verified",
                None if snapshot.get("write_capability_ready") else "provider write path not verified in this runtime",
                "Talgil write path not implemented in FastAPI runtime" if provider == "talgil" else None,
            ] if item
        ],
        "operator_message": _operator_message(provider, tier, snapshot),
        "raw_status": {k: v for k, v in snapshot.items() if k not in {"farms", "zones"}},
    }


def _operator_message(provider: str, tier: str, snapshot: dict[str, Any]) -> str:
    if tier == "schedule_write_ready":
        return f"{provider} has live read/auth and a declared schedule-write path. Keep dry-run + approval enabled until a customer-specific write test is verified."
    if tier == "read_ready":
        return f"{provider} is live for read/discovery. Physical execution is not ready yet; use reports, tasks, and approval requests."
    if tier == "not_configured":
        return f"{provider} is not configured for this runtime. Customer can connect through API credentials or export upload first."
    return f"{provider} is configured but blocked for live execution. Resolve auth/read checks before any physical command path."


@router.get("/environments", response_model=ControllerEnvironmentResponse)
async def get_controller_environments() -> ControllerEnvironmentResponse:
    """Return source-aware controller environment summary for portal UI."""
    wiseconn_snapshot = await _wiseconn_snapshot()
    talgil_snapshot = await _talgil_snapshot()

    wiseconn_env = ControllerEnvironment(
        source="wiseconn",
        label="WiseConn",
        status="live" if wiseconn_snapshot["live"] else "configured" if wiseconn_snapshot["configured"] else "integration_ready",
        live=bool(wiseconn_snapshot["live"]),
        configured=bool(wiseconn_snapshot["configured"]),
        farms=len(wiseconn_snapshot["farms"]),
        zones=len(wiseconn_snapshot["zones"]),
        notes=(
            "Live read path available via /v1/wiseconn endpoints. Schedule-write primitive exists but must remain approval-gated."
            if wiseconn_snapshot["live"]
            else "WiseConn adapter exists but live runtime auth/read checks are not verified."
        ),
        sources=wiseconn_snapshot["zone_sources"],
    )

    talgil_status: ControllerStatus = "live" if talgil_snapshot["live"] else "configured" if talgil_snapshot["configured"] else "integration_ready"
    talgil_env = ControllerEnvironment(
        source="talgil",
        label="Talgil",
        status=talgil_status,
        live=bool(talgil_snapshot["live"]),
        configured=bool(talgil_snapshot["configured"]),
        farms=int(talgil_snapshot["farms"]),
        zones=int(talgil_snapshot["zones"]),
        notes=talgil_snapshot["notes"],
        sources={"talgil": int(talgil_snapshot["zones"])} if talgil_snapshot["zones"] else {},
    )

    environments = [wiseconn_env, talgil_env]
    totals = {
        "farms": sum(item.farms for item in environments),
        "zones": sum(item.zones for item in environments),
        "live_environments": sum(1 for item in environments if item.live),
        "configured_environments": sum(1 for item in environments if item.configured),
    }

    return ControllerEnvironmentResponse(environments=environments, totals=totals)


@router.get("/execution-readiness")
async def get_execution_readiness(
    workspace_id: str | None = Query(default=None),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return physical-control readiness for WiseConn/Talgil.

    This endpoint is intentionally conservative. It distinguishes read readiness
    from schedule-write readiness and never marks valve/pump execution safe unless
    provider auth, mapping, write method, approval, and audit controls exist.
    """
    wiseconn = _readiness_card(await _wiseconn_snapshot())
    talgil = _readiness_card(await _talgil_snapshot())
    cards = [wiseconn, talgil]
    ready_for_any_live_write = any(card["live_write"] for card in cards)
    job = _safe_job(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        job_type="controller_execution_readiness_check",
        input_json={"workspace_id": workspace_id},
        output_json={"providers": cards, "ready_for_any_live_write": ready_for_any_live_write},
    )
    return {
        "status": "ok",
        "workspace_id": workspace_id,
        "ready_for_any_live_write": ready_for_any_live_write,
        "default_execution_mode": "dry_run_and_approval_required",
        "providers": cards,
        "required_before_physical_execution": [
            "customer authorization on provider account",
            "provider credentials validated in AGRO-AI runtime",
            "farm/field/zone mapping reviewed by user",
            "write scope verified on provider account",
            "dry-run execution packet reviewed",
            "human approval captured",
            "provider readback verification after write",
        ],
        "readiness_job": _job_public(job),
    }


@router.post("/customer-connect")
async def customer_connect_controller(
    payload: ControllerCustomerConnectRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a customer controller connection record with frictionless setup rails."""
    ensure_schema(db)
    mode = "api_credentials" if payload.connection_method == "api_key" else payload.connection_method
    config = sanitize_config({
        "account_hint": payload.account_hint,
        "api_key_present": payload.api_key_present,
        "enable_read_sync": payload.enable_read_sync,
        "request_write_access": payload.request_write_access,
        "human_approval_required": payload.human_approval_required,
        "notes": payload.notes,
        "connection_method": payload.connection_method,
        "controller_connection_version": "physical-readiness-v1",
        "execution_default": "dry_run_and_approval_required",
    })
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode=mode,
        display_name=payload.display_name or f"{payload.provider.title()} controller connection",
        config=config,
    )
    connection.status = "connected" if payload.api_key_present or payload.connection_method in {"export_upload", "demo"} else "credentials_required"
    connection.credentials_ref = safe_credential_ref(f"{payload.provider}:{payload.account_hint or payload.connection_method}:{payload.api_key_present}")
    merged = dict(connection.config_json or {})
    merged.update(config)
    merged.update({
        "capabilities_requested": ["read_sync"] + (["schedule_write"] if payload.request_write_access else []),
        "capabilities_enabled": ["export_upload"] + (["read_sync_candidate"] if payload.enable_read_sync else []),
        "physical_execution_enabled": False,
        "physical_execution_reason": "Requires live provider validation, field mapping, write-scope verification, and human approval.",
    })
    connection.config_json = merged
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    job = _safe_job(
        db,
        tenant_id=tenant_id,
        workspace_id=payload.workspace_id,
        job_type="controller_customer_connect",
        input_json={"provider": payload.provider, "mode": mode, "workspace_id": payload.workspace_id},
        output_json={"connection_status": connection.status, "physical_execution_enabled": False, "next_steps": _connection_next_steps(payload)},
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return {
        "status": connection.status,
        "connection": public_connection(connection),
        "frictionless_setup": _connection_next_steps(payload),
        "physical_execution_enabled": False,
        "execution_default": "dry_run_and_approval_required",
        "job": _job_public(job),
    }


def _connection_next_steps(payload: ControllerCustomerConnectRequest) -> list[str]:
    steps = [
        "Connect or upload controller evidence from the Connector Hub.",
        "Run controller execution readiness check.",
        "Review detected farms/targets, zones, and field mappings.",
    ]
    if payload.provider == "wiseconn":
        steps.append("Verify WiseConn API key has read scope; only then test schedule-write in dry-run/approval mode.")
    if payload.provider == "talgil":
        steps.append("Verify Talgil target read access; schedule-write remains unavailable until the provider write API contract is wired.")
    if payload.request_write_access:
        steps.append("Request write access only after a named customer approves physical-controller management.")
    return steps


@router.post("/execution/prepare")
async def prepare_controller_execution(
    payload: ControllerExecutionPrepareRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Prepare or dry-run a controller execution packet.

    Only WiseConn schedule_irrigation can be promoted to a real provider write
    in this runtime, and only when approval_confirmed=True and dry_run=False.
    Talgil and direct valve/pump commands stay as approval packets until their
    provider-specific write contracts are implemented and verified.
    """
    readiness = _readiness_card(await (_wiseconn_snapshot() if payload.provider == "wiseconn" else _talgil_snapshot()))
    execution_packet = {
        "provider": payload.provider,
        "command": payload.command,
        "controller_id": payload.controller_id,
        "zone_id": payload.zone_id,
        "start_time": payload.start_time.isoformat() if payload.start_time else None,
        "duration_minutes": payload.duration_minutes,
        "provider_schedule_id": payload.provider_schedule_id,
        "reason": payload.reason,
        "requested_by": payload.requested_by,
        "dry_run": payload.dry_run,
        "approval_confirmed": payload.approval_confirmed,
        "metadata": payload.metadata,
        "readiness": readiness,
    }

    can_execute_live = (
        payload.provider == "wiseconn"
        and payload.command == "schedule_irrigation"
        and readiness["live_write"]
        and payload.approval_confirmed
        and not payload.dry_run
        and payload.zone_id
        and payload.start_time
        and payload.duration_minutes
    )

    if not can_execute_live:
        job = _safe_job(
            db,
            tenant_id=tenant_id,
            workspace_id=payload.workspace_id,
            job_type="controller_execution_prepared",
            input_json=execution_packet,
            output_json={
                "executed": False,
                "approval_required": True,
                "reason": _not_executed_reason(payload, readiness),
                "next_step": "Create/approve the operation packet, verify mapping and provider scopes, then rerun with dry_run=false only for supported WiseConn schedule writes.",
            },
            status_value="approval_required",
        )
        return {
            "status": "approval_required",
            "executed": False,
            "physical_action_executed": False,
            "reason": _not_executed_reason(payload, readiness),
            "execution_packet": execution_packet,
            "job": _job_public(job),
        }

    adapter = AdapterRegistry.get_wiseconn()
    try:
        provider_response = await adapter.create_irrigation(
            zone_id=str(payload.zone_id),
            start_time=payload.start_time,
            duration_minutes=int(payload.duration_minutes or 0),
            metadata={"source": "agro-ai-approved-execution", **payload.metadata},
        )
        job = _safe_job(
            db,
            tenant_id=tenant_id,
            workspace_id=payload.workspace_id,
            job_type="controller_execution_provider_write",
            input_json=execution_packet,
            output_json={"executed": True, "provider_response": provider_response, "readback_required": True},
            status_value="executed",
        )
        return {
            "status": "executed",
            "executed": True,
            "physical_action_executed": True,
            "provider_response": provider_response,
            "readback_required": True,
            "job": _job_public(job),
        }
    except Exception as exc:
        job = _safe_job(
            db,
            tenant_id=tenant_id,
            workspace_id=payload.workspace_id,
            job_type="controller_execution_failed",
            input_json=execution_packet,
            output_json={"executed": False, "error": exc.__class__.__name__},
            status_value="failed",
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"message": "Provider execution failed", "error": exc.__class__.__name__, "job": _job_public(job)}) from exc


def _not_executed_reason(payload: ControllerExecutionPrepareRequest, readiness: dict[str, Any]) -> str:
    reasons = []
    if payload.dry_run:
        reasons.append("dry_run is enabled")
    if not payload.approval_confirmed:
        reasons.append("human approval has not been confirmed")
    if payload.provider != "wiseconn":
        reasons.append("only WiseConn schedule-write is wired in this runtime")
    if payload.command != "schedule_irrigation":
        reasons.append("direct valve/pump commands are not wired for live execution")
    if not readiness.get("live_write"):
        reasons.append("provider live write readiness is not verified")
    if not payload.zone_id:
        reasons.append("zone_id is required")
    if not payload.start_time:
        reasons.append("start_time is required")
    if not payload.duration_minutes:
        reasons.append("duration_minutes is required")
    return "; ".join(reasons) or "execution is approval-gated by default"
