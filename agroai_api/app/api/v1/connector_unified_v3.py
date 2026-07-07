"""Connector Unification v3: self-service WiseConn, Talgil, and OpenET.

The public lifecycle is intentionally provider-neutral:
available -> authorizing -> connected -> discovering -> syncing -> synced
with action_required / reconnect_required / rate_limited / degraded / failed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from app.adapters.openet import OpenETAuthError
from app.adapters.talgil import TalgilAuthError
from app.adapters.wiseconn import WiseConnAuthError
from app.api.v1.connectors import create_or_get_connection, public_connection, sanitize_config, verify_connector_schema
from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection
from app.services.ag_connector_runtime import (
    AG_PROVIDERS,
    AUTH_ERRORS,
    RATE_LIMIT_ERRORS,
    _redact_mapping,
    _resource_preview,
    build_ag_adapter,
    discover_ag_resources,
    load_ag_adapter,
)
from app.services.connector_vault import credential_reference, revoke_connector_credentials, store_connector_credentials
from app.services.provider_sync_jobs import queue_provider_sync
from app.services.task_outbox_service import drain_pending_outbox


router = APIRouter(tags=["connector-unification-v3"])
AgProvider = Literal["wiseconn", "talgil", "openet"]


class UnifiedConnectRequest(BaseModel):
    provider: AgProvider
    workspace_id: str | None = None
    api_key: SecretStr
    display_name: str | None = None


class UnifiedSelectionRequest(BaseModel):
    resource_ids: list[str] = Field(default_factory=list)
    scope_mode: Literal["provider_resources", "agroai_fields", "openet_field_ids", "geometry"] = "provider_resources"
    geometry: list[float] = Field(default_factory=list)
    field_ids: list[str] = Field(default_factory=list)


LIFECYCLE_STATES = {
    "available", "authorizing", "connected", "discovering", "syncing", "synced",
    "action_required", "reconnect_required", "rate_limited", "degraded", "failed",
}


def _connection(db: Session, tenant_id: str, connection_id: str) -> ConnectorConnection:
    row = db.get(ConnectorConnection, connection_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    if row.provider not in AG_PROVIDERS:
        raise HTTPException(status_code=409, detail="Connection is not managed by Connector Unification v3")
    return row


def _status_payload(connection: ConnectorConnection) -> dict[str, Any]:
    state = connection.status if connection.status in LIFECYCLE_STATES else "degraded"
    config = dict(connection.config_json or {})
    return {
        "state": state,
        "provider": connection.provider,
        "connection": public_connection(connection),
        "selection": {
            "scope_mode": config.get("scope_mode"),
            "resource_ids": config.get("selected_resource_ids", []),
            "field_ids": config.get("field_ids", []),
            "has_geometry": bool(config.get("geometry")),
            "openet_asset_id": config.get("openet_asset_id"),
        },
        "identity": config.get("provider_identity", {}),
    }


async def _probe_candidate(provider: str, api_key: str) -> dict[str, Any]:
    adapter = build_ag_adapter(provider, {"api_key": api_key})
    try:
        if provider == "wiseconn":
            if not await adapter.check_auth():
                raise WiseConnAuthError("WiseConn authorization failed")
            farms = await adapter.list_farms()
            return {"identity": {"provider": "wiseconn", "resource_count": len(farms)}, "resources": _resource_preview(farms, "farm")}
        if provider == "talgil":
            if not await adapter.check_auth():
                raise TalgilAuthError("Talgil authorization failed")
            targets = await adapter.list_targets()
            return {"identity": {"provider": "talgil", "resource_count": len(targets)}, "resources": _resource_preview(targets, "controller")}
        if provider == "openet":
            if not await adapter.check_auth():
                raise OpenETAuthError("OpenET authorization failed")
            account = await adapter.account_status()
            return {"identity": {"provider": "openet", "account": _redact_mapping(account)}, "resources": []}
        raise ValueError("unsupported agricultural provider")
    finally:
        await adapter.close()


def _preserve_or_fail_connection(
    db: Session,
    *,
    tenant_id: str,
    connection_id: str,
    prior_status: str,
    prior_ref: str | None,
    failure_status: str,
    message: str,
) -> ConnectorConnection:
    db.rollback()
    connection = _connection(db, tenant_id, connection_id)
    if prior_ref:
        connection.status = prior_status if prior_status in LIFECYCLE_STATES else "connected"
        connection.credentials_ref = prior_ref
        connection.last_error = message + " Existing connection preserved."
    else:
        connection.status = failure_status
        connection.credentials_ref = None
        connection.last_error = message
    connection.updated_at = datetime.utcnow()
    db.commit()
    return connection


@router.post("/connectors/unified/connect")
async def unified_connect(
    payload: UnifiedConnectRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode="api_key",
        display_name=payload.display_name,
    )
    prior_status = str(connection.status or "available")
    prior_ref = connection.credentials_ref
    connection.status = "authorizing"
    connection.updated_at = datetime.utcnow()

    candidate = payload.api_key.get_secret_value()
    try:
        probe = await _probe_candidate(payload.provider, candidate)
    except AUTH_ERRORS as exc:
        _preserve_or_fail_connection(
            db,
            tenant_id=tenant_id,
            connection_id=connection.id,
            prior_status=prior_status,
            prior_ref=prior_ref,
            failure_status="action_required",
            message="Provider authorization failed. Check the access credential and try again.",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "provider_authorization_failed", "provider": payload.provider}) from exc
    except RATE_LIMIT_ERRORS as exc:
        _preserve_or_fail_connection(
            db,
            tenant_id=tenant_id,
            connection_id=connection.id,
            prior_status=prior_status,
            prior_ref=prior_ref,
            failure_status="rate_limited",
            message="Provider rate limit reached during authorization probe.",
        )
        raise HTTPException(status_code=429, detail={"code": "provider_rate_limited", "provider": payload.provider}) from exc
    except Exception as exc:
        _preserve_or_fail_connection(
            db,
            tenant_id=tenant_id,
            connection_id=connection.id,
            prior_status=prior_status,
            prior_ref=prior_ref,
            failure_status="degraded",
            message=f"Provider probe failed: {exc.__class__.__name__}",
        )
        raise HTTPException(status_code=502, detail={"code": "provider_probe_failed", "provider": payload.provider}) from exc

    connection = _connection(db, tenant_id, connection.id)
    vault_row = store_connector_credentials(
        db,
        tenant_id=tenant_id,
        connection=connection,
        provider=payload.provider,
        payload={"api_key": candidate},
        scopes=["read", "discover", "sync"],
    )
    connection.credentials_ref = credential_reference(vault_row)
    config = dict(connection.config_json or {})
    config.update(sanitize_config({
        "connector_unification_version": "v3",
        "lifecycle_state": "connected",
        "authorization_status": "connected",
        "provider_identity": probe.get("identity", {}),
        "discovered_resource_count": len(probe.get("resources", [])),
    }))
    connection.config_json = config
    connection.status = "connected"
    connection.last_error = None
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(connection)
    return {"status": "connected", "state": "connected", "connection": public_connection(connection), "identity": probe.get("identity", {}), "resources": probe.get("resources", [])}


@router.get("/connectors/unified/{connection_id}/discovery")
async def unified_discovery(
    connection_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    connection = _connection(db, tenant_id, connection_id)
    if not connection.credentials_ref:
        raise HTTPException(status_code=409, detail={"code": "authorization_required"})
    prior = connection.status
    connection.status = "discovering"
    connection.updated_at = datetime.utcnow()
    db.commit()
    try:
        result = await discover_ag_resources(db, connection=connection)
    except AUTH_ERRORS as exc:
        connection = _connection(db, tenant_id, connection_id)
        connection.status = "reconnect_required"
        connection.last_error = "Provider authorization is no longer valid."
        connection.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=401, detail={"code": "reconnect_required"}) from exc
    except RATE_LIMIT_ERRORS as exc:
        connection = _connection(db, tenant_id, connection_id)
        connection.status = "rate_limited"
        connection.last_error = "Provider rate limit reached during discovery."
        connection.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=429, detail={"code": "provider_rate_limited"}) from exc
    except Exception as exc:
        connection = _connection(db, tenant_id, connection_id)
        connection.status = "degraded"
        connection.last_error = f"Discovery failed: {exc.__class__.__name__}"
        connection.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail={"code": "provider_discovery_failed"}) from exc

    connection = _connection(db, tenant_id, connection_id)
    connection.status = prior if prior in {"connected", "synced"} else "connected"
    connection.last_error = None
    connection.updated_at = datetime.utcnow()
    config = dict(connection.config_json or {})
    config["discovered_resource_count"] = int(result.get("count", 0))
    if result.get("field_ids"):
        config["field_ids"] = list(result["field_ids"])
    connection.config_json = config
    db.commit()
    db.refresh(connection)
    return {"status": "ok", "state": connection.status, "connection": public_connection(connection), **result}


@router.post("/connectors/unified/{connection_id}/selection")
async def unified_selection(
    connection_id: str,
    payload: UnifiedSelectionRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    connection = _connection(db, tenant_id, connection_id)
    if connection.provider != "openet" and payload.scope_mode != "provider_resources":
        raise HTTPException(status_code=409, detail={"code": "invalid_scope_mode_for_provider"})
    if connection.provider == "openet" and payload.scope_mode == "openet_field_ids" and not payload.field_ids:
        raise HTTPException(status_code=422, detail={"code": "openet_field_ids_required"})
    if connection.provider == "openet" and payload.scope_mode == "geometry" and len(payload.geometry) < 6:
        raise HTTPException(status_code=422, detail={"code": "openet_geometry_required"})

    config = dict(connection.config_json or {})
    resource_ids = payload.resource_ids or payload.field_ids
    config.update({
        "scope_mode": payload.scope_mode,
        "selected_resource_ids": [str(value) for value in resource_ids],
        "field_ids": [str(value) for value in payload.field_ids] if payload.field_ids else config.get("field_ids", []),
        "geometry": [float(value) for value in payload.geometry] if payload.geometry else config.get("geometry", []),
        "selection_confirmed": True,
        "selection_updated_at": datetime.utcnow().isoformat() + "Z",
    })
    connection.config_json = sanitize_config(config)
    connection.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(connection)
    return {"status": "ok", "state": connection.status, "connection": public_connection(connection), "selection": _status_payload(connection)["selection"]}


@router.post("/connectors/unified/{connection_id}/openet-boundary")
async def upload_openet_boundary(
    connection_id: str,
    file: UploadFile = File(...),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    connection = _connection(db, tenant_id, connection_id)
    if connection.provider != "openet":
        raise HTTPException(status_code=409, detail="Boundary upload is only available for OpenET")
    filename = file.filename or "fields.geojson"
    if not filename.lower().endswith((".geojson", ".json")):
        raise HTTPException(status_code=415, detail={"code": "openet_geojson_required"})
    data = await file.read(int(getattr(settings, "CONNECTOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)) + 1)
    max_bytes = min(int(getattr(settings, "CONNECTOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)), 25 * 1024 * 1024)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="OpenET GeoJSON boundary file exceeds 25 MB")
    adapter = load_ag_adapter(db, connection=connection)
    try:
        result = await adapter.upload_geojson(filename, data)
    except AUTH_ERRORS as exc:
        raise HTTPException(status_code=401, detail={"code": "reconnect_required"}) from exc
    finally:
        await adapter.close()
    asset_id = result.get("asset_id") or result.get("assetId") or result.get("id") or result.get("path")
    if not asset_id:
        raise HTTPException(status_code=502, detail={"code": "openet_asset_id_missing"})
    config = dict(connection.config_json or {})
    config.update({"scope_mode": "agroai_fields", "openet_asset_id": str(asset_id), "boundary_filename": filename, "selection_confirmed": True})
    connection.config_json = sanitize_config(config)
    connection.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(connection)
    return {"status": "ok", "state": connection.status, "asset_id": str(asset_id), "connection": public_connection(connection)}


@router.post("/connectors/unified/{connection_id}/sync")
async def unified_sync(
    connection_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    connection = _connection(db, tenant_id, connection_id)
    if connection.status not in {"connected", "synced", "syncing", "rate_limited", "degraded"} or not connection.credentials_ref:
        raise HTTPException(status_code=409, detail={"code": "authorization_required", "state": connection.status})
    config = dict(connection.config_json or {})
    if connection.provider == "openet" and not config.get("selection_confirmed"):
        raise HTTPException(status_code=409, detail={"code": "openet_field_scope_required"})
    connection.status = "syncing"
    connection.updated_at = datetime.utcnow()
    db.commit()
    job, deduplicated = queue_provider_sync(db, tenant_id=tenant_id, connection=connection)
    publication = await asyncio.to_thread(drain_pending_outbox, limit=10)
    db.refresh(connection)
    return {"status": job.status, "state": "syncing", "deduplicated": deduplicated, "queue_publication": publication, "connection": public_connection(connection), "job_id": job.id}


@router.get("/connectors/unified/{connection_id}/status")
def unified_status(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _status_payload(_connection(db, tenant_id, connection_id))


@router.post("/connectors/unified/{connection_id}/disconnect")
def unified_disconnect(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    connection = _connection(db, tenant_id, connection_id)
    revoked = revoke_connector_credentials(db, tenant_id=tenant_id, connection_id=connection.id)
    connection.status = "available"
    connection.credentials_ref = None
    connection.last_error = None
    connection.updated_at = datetime.utcnow()
    config = dict(connection.config_json or {})
    config.update({"lifecycle_state": "available", "authorization_status": "disconnected", "disconnected_at": datetime.utcnow().isoformat() + "Z"})
    connection.config_json = sanitize_config(config)
    db.commit()
    db.refresh(connection)
    return {"status": "disconnected", "state": "available", "credential_revoked": revoked, "connection": public_connection(connection)}
