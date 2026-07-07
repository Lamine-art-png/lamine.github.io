from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.connectors import create_or_get_connection, public_connection, sanitize_config, verify_connector_schema
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.services.ag_connector_runtime import AG_PROVIDERS, AUTH_ERRORS, RATE_LIMIT_ERRORS, discover_ag_resources, load_ag_adapter, probe_ag_connection
from app.services.connector_vault import credential_reference, revoke_connector_credentials, store_connector_credentials
from app.services.ingestion_stream import read_spooled_bytes, stream_upload_to_spool
from app.services.provider_sync_jobs import queue_provider_sync
from app.services.task_outbox_service import drain_pending_outbox

router = APIRouter(tags=["ag-connector-lifecycle"])
AgProvider = Literal["wiseconn", "talgil", "openet"]


class UnifiedConnectRequest(BaseModel):
    provider: AgProvider
    workspace_id: str | None = None
    access_value: str = Field(min_length=1)
    display_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnifiedSelectionRequest(BaseModel):
    resource_ids: list[str] = Field(default_factory=list)
    scope_mode: Literal["provider_resources", "agroai_fields", "openet_field_ids", "geometry"] = "provider_resources"
    field_ids: list[str] = Field(default_factory=list)
    geometry: list[float] = Field(default_factory=list)


def _connection(db: Session, tenant_id: str, connection_id: str) -> ConnectorConnection:
    row = db.get(ConnectorConnection, connection_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    if row.provider not in AG_PROVIDERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connection is not a unified AgTech connector")
    return row


def _state(row: ConnectorConnection) -> str:
    value = str(row.status or "available")
    if value in {"ready", "test_passed"}:
        return "connected"
    if value in {"connected", "discovering", "syncing", "synced", "action_required", "reconnect_required", "rate_limited", "degraded", "failed", "disconnected"}:
        return value
    return "available" if not row.credentials_ref else value


def _job(db: Session, *, tenant_id: str, connection: ConnectorConnection, job_type: str, output_json: dict[str, Any], status_value: str = "completed") -> IngestionJob:
    row = IngestionJob(tenant_id=tenant_id, workspace_id=connection.workspace_id, connector_connection_id=connection.id, job_type=job_type, status=status_value, input_json={"provider": connection.provider, "connection_id": connection.id}, output_json=output_json, completed_at=datetime.utcnow())
    db.add(row)
    return row


@router.post("/connectors/unified/connect")
async def connect_unified_ag_provider(payload: UnifiedConnectRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode="api_credentials", display_name=payload.display_name, config=sanitize_config({**payload.metadata, "surface": "connector_unification_v3"}))
    connection.status = "authorizing"
    connection.credentials_ref = None
    connection.last_error = None
    connection.updated_at = datetime.utcnow()
    db.flush()
    vault_row = store_connector_credentials(db, tenant_id=tenant_id, connection=connection, provider=payload.provider, payload={"api_key": payload.access_value, "credential_type": "customer_api_key"})
    try:
        probe = await probe_ag_connection(db, connection=connection)
    except AUTH_ERRORS as exc:
        revoke_connector_credentials(db, tenant_id=tenant_id, connection_id=connection.id)
        connection.status = "action_required"
        connection.credentials_ref = None
        connection.last_error = str(exc)[:700]
        _job(db, tenant_id=tenant_id, connection=connection, job_type="unified_ag_connect", output_json={"authorized": False}, status_value="failed")
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": "authorization_failed", "provider": payload.provider}) from exc
    except RATE_LIMIT_ERRORS as exc:
        connection.status = "rate_limited"
        connection.credentials_ref = credential_reference(vault_row)
        connection.last_error = str(exc)[:700]
        _job(db, tenant_id=tenant_id, connection=connection, job_type="unified_ag_connect", output_json={"authorized": False, "error": "rate_limited"}, status_value="retrying")
        db.commit()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"error": "provider_rate_limited", "provider": payload.provider}) from exc
    except Exception as exc:
        revoke_connector_credentials(db, tenant_id=tenant_id, connection_id=connection.id)
        connection.status = "failed"
        connection.credentials_ref = None
        connection.last_error = str(exc)[:700]
        _job(db, tenant_id=tenant_id, connection=connection, job_type="unified_ag_connect", output_json={"authorized": False, "error": "probe_failed"}, status_value="failed")
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "provider_probe_failed", "provider": payload.provider}) from exc
    resources = list(probe.get("resources") or [])
    config = dict(connection.config_json or {})
    config.update({"authorization_status": "connected", "connector_unification_version": "v3", "identity": probe.get("identity"), "resource_preview_count": len(resources), "credential_storage": "tenant_vault"})
    connection.config_json = sanitize_config(config)
    connection.status = "connected"
    connection.credentials_ref = credential_reference(vault_row)
    connection.last_error = None
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    job = _job(db, tenant_id=tenant_id, connection=connection, job_type="unified_ag_connect", output_json={"authorized": True, "resources": len(resources), "identity": probe.get("identity")})
    db.commit()
    db.refresh(connection)
    return {"status": "connected", "state": "connected", "connection": public_connection(connection), "identity": probe.get("identity"), "resources": resources, "count": len(resources), "job": {"id": job.id, "status": job.status}}


@router.get("/connectors/unified/{connection_id}/status")
async def unified_status(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = _connection(db, tenant_id, connection_id)
    return {"status": "ok", "state": _state(connection), "connection": public_connection(connection)}


@router.get("/connectors/unified/{connection_id}/discovery")
async def discover_unified_resources(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = _connection(db, tenant_id, connection_id)
    if not connection.credentials_ref:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "provider_reauthorization_required", "provider": connection.provider})
    connection.status = "discovering"
    connection.updated_at = datetime.utcnow()
    db.commit()
    try:
        discovery = await discover_ag_resources(db, connection=connection)
    except AUTH_ERRORS as exc:
        connection.status = "reconnect_required"
        connection.last_error = str(exc)[:700]
        connection.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": "provider_reauthorization_required", "provider": connection.provider}) from exc
    except RATE_LIMIT_ERRORS as exc:
        connection.status = "rate_limited"
        connection.last_error = str(exc)[:700]
        connection.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"error": "provider_rate_limited", "provider": connection.provider}) from exc
    connection.status = "connected"
    config = dict(connection.config_json or {})
    config.update({"last_discovery_count": discovery.get("count", 0), "last_discovery_at": datetime.utcnow().isoformat() + "Z"})
    connection.config_json = sanitize_config(config)
    connection.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(connection)
    return {"status": "ok", "state": "connected", "connection": public_connection(connection), **discovery}


@router.post("/connectors/unified/{connection_id}/selection")
async def save_unified_selection(payload: UnifiedSelectionRequest, connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = _connection(db, tenant_id, connection_id)
    selected = list(dict.fromkeys([str(value) for value in (payload.resource_ids or payload.field_ids) if str(value).strip()]))
    config = dict(connection.config_json or {})
    config.update({"scope_mode": payload.scope_mode, "selected_resource_ids": selected, "selection_saved_at": datetime.utcnow().isoformat() + "Z"})
    if payload.field_ids:
        config["field_ids"] = list(dict.fromkeys([str(value) for value in payload.field_ids if str(value).strip()]))[:100]
    if payload.geometry:
        config["geometry"] = [float(value) for value in payload.geometry]
    connection.config_json = sanitize_config(config)
    connection.status = "connected"
    connection.updated_at = datetime.utcnow()
    _job(db, tenant_id=tenant_id, connection=connection, job_type="unified_ag_selection", output_json={"scope_mode": payload.scope_mode, "selected_count": len(selected), "has_geometry": bool(payload.geometry)})
    db.commit()
    db.refresh(connection)
    return {"status": "ok", "state": "connected", "connection": public_connection(connection), "selected_resource_ids": selected}


@router.post("/connectors/unified/{connection_id}/sync")
async def sync_unified_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = _connection(db, tenant_id, connection_id)
    if connection.status not in {"connected", "synced", "syncing", "rate_limited", "degraded"} or not connection.credentials_ref:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "provider_reauthorization_required", "provider": connection.provider, "status": connection.status})
    queued, deduplicated = queue_provider_sync(db, tenant_id=tenant_id, connection=connection)
    connection.status = "syncing"
    connection.updated_at = datetime.utcnow()
    db.commit()
    publication = await drain_pending_outbox(limit=10)
    db.refresh(connection)
    return {"status": queued.status, "state": "syncing", "deduplicated": deduplicated, "queue_publication": publication, "connection": public_connection(connection), "job": {"id": queued.id, "status": queued.status}}


@router.post("/connectors/unified/{connection_id}/openet-boundary")
async def upload_openet_boundary(connection_id: str, file: UploadFile = File(...), tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = _connection(db, tenant_id, connection_id)
    if connection.provider != "openet":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Boundary upload is only supported for OpenET")
    if not connection.credentials_ref:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "provider_reauthorization_required", "provider": "openet"})
    receipt = await stream_upload_to_spool(file, tenant_id=tenant_id, connection_id=connection.id)
    try:
        data = read_spooled_bytes(receipt)
        adapter = load_ag_adapter(db, connection=connection)
        try:
            uploaded = await adapter.upload_geojson(file.filename or "openet-boundary.geojson", data)
        finally:
            await adapter.close()
        config = dict(connection.config_json or {})
        config.update({"scope_mode": "geometry_asset", "openet_asset_id": uploaded.get("asset_id") or uploaded.get("id") or uploaded.get("asset"), "boundary_upload": sanitize_config(uploaded), "boundary_uploaded_at": datetime.utcnow().isoformat() + "Z"})
        connection.config_json = sanitize_config(config)
        connection.status = "connected"
        connection.updated_at = datetime.utcnow()
        _job(db, tenant_id=tenant_id, connection=connection, job_type="openet_boundary_upload", output_json={"uploaded": sanitize_config(uploaded)})
        db.commit()
        db.refresh(connection)
        return {"status": "ok", "state": "connected", "connection": public_connection(connection), "upload": sanitize_config(uploaded)}
    finally:
        Path(receipt.path).unlink(missing_ok=True)


@router.post("/connectors/unified/{connection_id}/disconnect")
async def disconnect_unified_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = _connection(db, tenant_id, connection_id)
    revoked = revoke_connector_credentials(db, tenant_id=tenant_id, connection_id=connection.id)
    config = dict(connection.config_json or {})
    config.update({"authorization_status": "disconnected", "disconnected_at": datetime.utcnow().isoformat() + "Z"})
    connection.config_json = sanitize_config(config)
    connection.status = "disconnected"
    connection.credentials_ref = None
    connection.last_error = None
    connection.updated_at = datetime.utcnow()
    _job(db, tenant_id=tenant_id, connection=connection, job_type="unified_ag_disconnect", output_json={"local_credential_revoked": revoked})
    db.commit()
    db.refresh(connection)
    return {"status": "disconnected", "state": "available", "local_credential_revoked": revoked, "connection": public_connection(connection)}
