"""Controller environment and execution-readiness endpoints for AGRO-AI.

This is the controller-agnostic control plane. Native adapters such as WiseConn
and Talgil feed into the same readiness model as customer-supplied controller
systems connected through Universal Controller Gateway.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.api.v1.connectors import create_or_get_connection, public_connection, safe_credential_ref, sanitize_config, verify_connector_schema
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, IngestionJob

router = APIRouter(prefix="/controllers", tags=["controllers"])

ControllerStatus = Literal["live", "configured", "integration_ready"]
ProviderId = Literal["wiseconn", "talgil", "universal_controller"]
ExecutionTier = Literal["not_configured", "read_ready", "schedule_write_ready", "approval_gated", "blocked"]

NORMALIZED_CONTROLLER_OBJECTS = [
    "farm",
    "field",
    "block",
    "zone",
    "valve",
    "pump",
    "meter",
    "sensor",
    "schedule",
    "irrigation_event",
    "operator_note",
]

NORMALIZED_CONTROLLER_FIELDS = {
    "farm_id": "Provider farm/account identifier",
    "field_id": "AGRO-AI or customer field identifier",
    "block_id": "Block/sector/station identifier",
    "zone_id": "Controller zone/station identifier",
    "valve_id": "Valve identifier when available",
    "pump_id": "Pump identifier when available",
    "timestamp": "Event timestamp with timezone where possible",
    "flow_rate": "Flow rate with units, for example gpm or lps",
    "water_volume": "Applied or measured water volume with units",
    "duration_minutes": "Runtime duration in minutes",
    "pressure": "Pressure reading with units",
    "state": "Valve/pump/program state",
    "program_id": "Controller program or schedule identifier",
    "source_record_id": "Provider source record identifier for audit trail",
}


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
    provider: ProviderId = "universal_controller"
    workspace_id: str | None = None
    display_name: str | None = None
    connection_method: Literal["api_key", "provider_assisted", "export_upload", "demo", "custom_api"] = "export_upload"
    account_hint: str | None = None
    system_name: str | None = None
    api_key_present: bool = False
    enable_read_sync: bool = True
    request_write_access: bool = False
    human_approval_required: bool = True
    notes: str | None = None
    normalized_mapping: dict[str, str] = Field(default_factory=dict)


class ControllerExecutionPrepareRequest(BaseModel):
    provider: ProviderId
    workspace_id: str | None = None
    connection_id: str | None = None
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


def _safe_job(db: Session, *, tenant_id: str, workspace_id: str | None, job_type: str, input_json: dict[str, Any], output_json: dict[str, Any], status_value: str = "completed") -> IngestionJob:
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
        "verified provider/customer authentication",
        "customer-authorized connection record",
        "farm/field/block/zone mapping confirmed",
        "write scope verified on provider account",
        "water budget checked",
        "safe operating window checked",
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
        "connection_id": None,
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
        status_payload = await adapter.get_runtime_status(use_cache=True)
        configured = bool(status_payload.configured)
        live = bool(status_payload.live)
        targets = int(status_payload.targets)
        notes = status_payload.notes
        diagnostic = getattr(adapter, "last_diagnostic", None).__dict__ if getattr(adapter, "last_diagnostic", None) else {}
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
        "connection_id": None,
    }


def _universal_snapshots(db: Session, tenant_id: str, workspace_id: str | None = None) -> list[dict[str, Any]]:
    verify_connector_schema(db)
    query = db.query(ConnectorConnection).filter(
        ConnectorConnection.tenant_id == tenant_id,
        ConnectorConnection.provider == "universal_controller",
    )
    if workspace_id:
        query = query.filter(ConnectorConnection.workspace_id == workspace_id)
    rows = query.order_by(ConnectorConnection.created_at.desc()).all()
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        config = row.config_json or {}
        mapping = config.get("field_mapping") or config.get("normalized_mapping") or {}
        configured = row.status not in {"credentials_required", "not_configured"}
        read_ready = configured and (row.mode in {"export_upload", "provider_assisted", "custom_api", "api_credentials"})
        write_requested = "schedule_write" in (config.get("capabilities_requested") or []) or bool(config.get("request_write_access"))
        snapshots.append({
            "provider": "universal_controller",
            "configured": configured,
            "live": False,
            "farms": int(config.get("farms", 0) or 0),
            "zones": int(config.get("zones", 0) or 0),
            "notes": config.get("notes") or "Universal controller connection. Data can be normalized into AGRO-AI; physical execution requires a provider-specific write adapter.",
            "diagnostic": {"mode": row.mode, "status": row.status, "system_name": config.get("system_name"), "mapping_keys": list(mapping.keys())},
            "read_capability": read_ready,
            "write_capability_declared": write_requested,
            "write_capability_ready": False,
            "write_method": None,
            "connection_id": row.id,
            "display_name": row.display_name,
        })
    return snapshots


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
    return {
        "provider": provider,
        "connection_id": snapshot.get("connection_id"),
        "display_name": snapshot.get("display_name"),
        "configured": bool(snapshot.get("configured")),
        "live_read": bool(snapshot.get("read_capability")),
        "live_write": bool(snapshot.get("write_capability_ready")),
        "execution_tier": tier,
        "farms_or_targets": len(snapshot.get("farms", [])) if isinstance(snapshot.get("farms"), list) else int(snapshot.get("farms") or 0),
        "zones": len(snapshot.get("zones", [])) if isinstance(snapshot.get("zones"), list) else int(snapshot.get("zones") or 0),
        "write_method": snapshot.get("write_method"),
        "normalized_objects": NORMALIZED_CONTROLLER_OBJECTS,
        "safe_default": "dry_run_and_approval_required",
        "approval_required_for_physical_execution": True,
        "safeguards": _base_safeguards(provider),
        "blocking_items": [
            item for item in [
                None if snapshot.get("configured") else "provider credentials/customer authorization missing",
                None if snapshot.get("read_capability") else "live read/export/API readiness not verified",
                None if snapshot.get("write_capability_ready") else "provider write path not verified in this runtime",
                "Talgil write path not implemented in FastAPI runtime" if provider == "talgil" else None,
                "Universal controller requires provider-specific write adapter before physical execution" if provider == "universal_controller" else None,
            ] if item
        ],
        "operator_message": _operator_message(provider, tier, snapshot),
        "raw_status": {k: v for k, v in snapshot.items() if k not in {"farms", "zones"}},
    }


def _operator_message(provider: str, tier: str, snapshot: dict[str, Any]) -> str:
    if provider == "universal_controller":
        return "This controller is onboarded through the universal gateway. AGRO-AI can normalize evidence and drive decisions/tasks/reports now. Physical execution requires a provider-specific write adapter, confirmed mapping, approval, and audit controls."
    if tier == "schedule_write_ready":
        return f"{provider} has live read/auth and a declared schedule-write path. Keep dry-run + approval enabled until a customer-specific write test is verified."
    if tier == "read_ready":
        return f"{provider} is live for read/discovery. Physical execution is not ready yet; use reports, tasks, and approval requests."
    if tier == "not_configured":
        return f"{provider} is not configured for this runtime. Customer can connect through API credentials or export upload first."
    return f"{provider} is configured but blocked for live execution. Resolve auth/read checks before any physical command path."


def _execution_controls_missing(payload: ControllerExecutionPrepareRequest) -> list[str]:
    metadata = payload.metadata or {}
    required = [
        ("customer_authorized", "customer_authorized=true"),
        ("mapping_confirmed", "mapping_confirmed=true"),
        ("write_scope_verified", "write_scope_verified=true"),
        ("water_budget_checked", "water_budget_checked=true"),
        ("safety_window_checked", "safety_window_checked=true"),
    ]
    return [label for key, label in required if not bool(metadata.get(key))]


@router.get("/universal/data-contract")
def universal_data_contract() -> dict[str, Any]:
    return {
        "status": "ok",
        "gateway": "Universal Controller Gateway",
        "normalized_objects": NORMALIZED_CONTROLLER_OBJECTS,
        "canonical_fields": NORMALIZED_CONTROLLER_FIELDS,
        "connection_methods": ["export_upload", "api_credentials", "provider_assisted", "custom_api"],
        "outputs": ["evidence records", "field tasks", "reports", "readiness checks", "approval packets", "agentic actions"],
        "physical_execution_policy": "Provider-agnostic ingestion is available now. Physical execution requires provider-specific write adapter, verified credentials, mapping, write scope, water budget, safe window, human approval, audit log, and provider readback.",
    }


@router.get("/environments", response_model=ControllerEnvironmentResponse)
async def get_controller_environments() -> ControllerEnvironmentResponse:
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
        notes="Live read path available via /v1/wiseconn endpoints. Schedule-write primitive exists but must remain approval-gated." if wiseconn_snapshot["live"] else "WiseConn adapter exists but live runtime auth/read checks are not verified.",
        sources=wiseconn_snapshot["zone_sources"],
    )
    talgil_env = ControllerEnvironment(
        source="talgil",
        label="Talgil",
        status="live" if talgil_snapshot["live"] else "configured" if talgil_snapshot["configured"] else "integration_ready",
        live=bool(talgil_snapshot["live"]),
        configured=bool(talgil_snapshot["configured"]),
        farms=int(talgil_snapshot["farms"]),
        zones=int(talgil_snapshot["zones"]),
        notes=talgil_snapshot["notes"],
        sources={"talgil": int(talgil_snapshot["zones"])} if talgil_snapshot["zones"] else {},
    )
    universal_env = ControllerEnvironment(
        source="universal_controller",
        label="Universal Controller Gateway",
        status="integration_ready",
        live=False,
        configured=True,
        farms=0,
        zones=0,
        notes="Controller-agnostic onboarding is available through export upload, API credentials, provider-assisted mode, or custom API contracts.",
        sources={"universal_gateway": 1},
    )
    environments = [wiseconn_env, talgil_env, universal_env]
    totals = {
        "farms": sum(item.farms for item in environments),
        "zones": sum(item.zones for item in environments),
        "live_environments": sum(1 for item in environments if item.live),
        "configured_environments": sum(1 for item in environments if item.configured),
    }
    return ControllerEnvironmentResponse(environments=environments, totals=totals)


@router.get("/execution-readiness")
async def get_execution_readiness(workspace_id: str | None = Query(default=None), tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    wiseconn = _readiness_card(await _wiseconn_snapshot())
    talgil = _readiness_card(await _talgil_snapshot())
    universal = [_readiness_card(item) for item in _universal_snapshots(db, tenant_id, workspace_id)]
    cards = [wiseconn, talgil, *universal]
    ready_for_any_live_write = any(card["live_write"] for card in cards)
    job = _safe_job(db, tenant_id=tenant_id, workspace_id=workspace_id, job_type="controller_execution_readiness_check", input_json={"workspace_id": workspace_id}, output_json={"providers": cards, "ready_for_any_live_write": ready_for_any_live_write})
    return {
        "status": "ok",
        "workspace_id": workspace_id,
        "controller_agnostic_gateway": True,
        "ready_for_any_live_write": ready_for_any_live_write,
        "default_execution_mode": "dry_run_and_approval_required",
        "providers": cards,
        "required_before_physical_execution": [
            "customer authorization on provider account",
            "provider credentials validated in AGRO-AI runtime",
            "farm/field/block/zone mapping reviewed by user",
            "provider-specific write adapter verified",
            "write scope verified on provider account",
            "water budget checked",
            "safe operating window checked",
            "dry-run execution packet reviewed",
            "human approval captured",
            "provider readback verification after write",
        ],
        "readiness_job": _job_public(job),
    }


@router.post("/customer-connect")
async def customer_connect_controller(payload: ControllerCustomerConnectRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    mode = "api_credentials" if payload.connection_method == "api_key" else payload.connection_method
    config = sanitize_config({
        "account_hint": payload.account_hint,
        "system_name": payload.system_name,
        "api_key_present": payload.api_key_present,
        "enable_read_sync": payload.enable_read_sync,
        "request_write_access": payload.request_write_access,
        "human_approval_required": payload.human_approval_required,
        "notes": payload.notes,
        "normalized_mapping": payload.normalized_mapping,
        "connection_method": payload.connection_method,
        "controller_connection_version": "universal-gateway-v1",
        "execution_default": "dry_run_and_approval_required",
    })
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode=mode,
        display_name=payload.display_name or payload.system_name or f"{payload.provider.replace('_', ' ').title()} controller connection",
        config=config,
    )
    connection.status = "connected" if payload.api_key_present or payload.connection_method in {"export_upload", "demo", "provider_assisted", "custom_api"} else "credentials_required"
    connection.credentials_ref = safe_credential_ref(f"{payload.provider}:{payload.account_hint or payload.connection_method}:{payload.api_key_present}")
    merged = dict(connection.config_json or {})
    merged.update(config)
    merged.update({
        "capabilities_requested": ["read_sync"] + (["schedule_write"] if payload.request_write_access else []),
        "capabilities_enabled": ["export_upload", "normalization"] + (["read_sync_candidate"] if payload.enable_read_sync else []),
        "normalized_objects": NORMALIZED_CONTROLLER_OBJECTS,
        "physical_execution_enabled": False,
        "physical_execution_reason": "Requires provider-specific write adapter, live provider validation, field mapping, write-scope verification, water-budget check, safe-window check, and human approval.",
    })
    connection.config_json = merged
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    job = _safe_job(db, tenant_id=tenant_id, workspace_id=payload.workspace_id, job_type="controller_customer_connect", input_json={"provider": payload.provider, "mode": mode, "workspace_id": payload.workspace_id}, output_json={"connection_status": connection.status, "physical_execution_enabled": False, "next_steps": _connection_next_steps(payload)})
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return {
        "status": connection.status,
        "connection": public_connection(connection),
        "controller_agnostic_gateway": payload.provider == "universal_controller",
        "normalized_data_contract": NORMALIZED_CONTROLLER_FIELDS,
        "frictionless_setup": _connection_next_steps(payload),
        "physical_execution_enabled": False,
        "execution_default": "dry_run_and_approval_required",
        "job": _job_public(job),
    }


def _connection_next_steps(payload: ControllerCustomerConnectRequest) -> list[str]:
    steps = ["Connect or upload controller evidence from the Connector Hub.", "Map provider columns into AGRO-AI's normalized controller model.", "Run controller execution readiness check.", "Review detected farms/fields/blocks/zones/valves/pumps."]
    if payload.provider == "wiseconn":
        steps.append("Verify WiseConn API key has read scope; only then test schedule-write in dry-run/approval mode.")
    elif payload.provider == "talgil":
        steps.append("Verify Talgil target read access; schedule-write remains unavailable until the provider write API contract is wired.")
    else:
        steps.append("For physical execution, implement or approve a provider-specific write adapter after data normalization is proven.")
    if payload.request_write_access:
        steps.append("Request write access only after a named customer approves physical-controller management.")
    return steps


@router.post("/execution/prepare")
async def prepare_controller_execution(payload: ControllerExecutionPrepareRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.provider == "wiseconn":
        readiness = _readiness_card(await _wiseconn_snapshot())
    elif payload.provider == "talgil":
        readiness = _readiness_card(await _talgil_snapshot())
    else:
        snapshots = _universal_snapshots(db, tenant_id, payload.workspace_id)
        selected = next((item for item in snapshots if item.get("connection_id") == payload.connection_id), snapshots[0] if snapshots else {"provider": "universal_controller", "configured": False, "read_capability": False, "write_capability_ready": False, "farms": 0, "zones": 0})
        readiness = _readiness_card(selected)
    missing_controls = _execution_controls_missing(payload)
    execution_packet = {
        "provider": payload.provider,
        "connection_id": payload.connection_id,
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
        "hard_gate_checks": {"passed": not missing_controls, "missing": missing_controls},
        "readiness": readiness,
    }
    can_execute_live = payload.provider == "wiseconn" and payload.command == "schedule_irrigation" and readiness["live_write"] and payload.approval_confirmed and not payload.dry_run and not missing_controls and payload.zone_id and payload.start_time and payload.duration_minutes
    if not can_execute_live:
        job = _safe_job(db, tenant_id=tenant_id, workspace_id=payload.workspace_id, job_type="controller_execution_prepared", input_json=execution_packet, output_json={"executed": False, "approval_required": True, "reason": _not_executed_reason(payload, readiness), "next_step": "Create/approve the operation packet, verify mapping/provider scopes/water budget/safety window, and only execute through a supported provider-specific write adapter."}, status_value="approval_required")
        return {"status": "approval_required", "executed": False, "physical_action_executed": False, "reason": _not_executed_reason(payload, readiness), "execution_packet": execution_packet, "job": _job_public(job)}
    adapter = AdapterRegistry.get_wiseconn()
    try:
        provider_response = await adapter.create_irrigation(zone_id=str(payload.zone_id), start_time=payload.start_time, duration_minutes=int(payload.duration_minutes or 0), metadata={"source": "agro-ai-approved-execution", **payload.metadata})
        job = _safe_job(db, tenant_id=tenant_id, workspace_id=payload.workspace_id, job_type="controller_execution_provider_write", input_json=execution_packet, output_json={"executed": True, "provider_response": provider_response, "readback_required": True}, status_value="executed")
        return {"status": "executed", "executed": True, "physical_action_executed": True, "provider_response": provider_response, "readback_required": True, "job": _job_public(job)}
    except Exception as exc:
        job = _safe_job(db, tenant_id=tenant_id, workspace_id=payload.workspace_id, job_type="controller_execution_failed", input_json=execution_packet, output_json={"executed": False, "error": exc.__class__.__name__}, status_value="failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"message": "Provider execution failed", "error": exc.__class__.__name__, "job": _job_public(job)}) from exc


def _not_executed_reason(payload: ControllerExecutionPrepareRequest, readiness: dict[str, Any]) -> str:
    reasons = []
    if payload.dry_run:
        reasons.append("dry_run is enabled")
    if not payload.approval_confirmed:
        reasons.append("human approval has not been confirmed")
    missing_controls = _execution_controls_missing(payload)
    if missing_controls:
        reasons.append("missing hard gates: " + ", ".join(missing_controls))
    if payload.provider != "wiseconn":
        reasons.append("provider-specific physical write adapter is not wired for this controller yet")
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
