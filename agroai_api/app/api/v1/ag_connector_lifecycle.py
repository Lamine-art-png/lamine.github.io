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
