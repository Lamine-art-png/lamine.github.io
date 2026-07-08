from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.connectors import public_connection, row_to_dict, verify_connector_schema
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection
from app.services.connector_vault import (
    load_connector_credentials,
    revoke_connector_credentials,
)
from app.services.provider_oauth import revoke_provider_credentials
from app.services.provider_sync_jobs import SUPPORTED_PROVIDERS, queue_provider_sync
from app.services.task_outbox_service import drain_pending_outbox


router = APIRouter(tags=["connector-provider-sync"])


def _connection(db: Session, tenant_id: str, connection_id: str) -> ConnectorConnection:
    row = db.get(ConnectorConnection, connection_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


@router.post("/connectors/provider-sync/{connection_id}/sync")
async def queue_sync(
    connection_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict:
    verify_connector_schema(db)
    connection = _connection(db, tenant_id, connection_id)
    if connection.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "provider_sync_not_launch_ready",
                "provider": connection.provider,
            },
        )
    if connection.status not in {"connected", "synced", "syncing", "rate_limited", "degraded"} or not connection.credentials_ref:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "provider_reauthorization_required",
                "provider": connection.provider,
                "status": connection.status,
            },
        )
    job, deduplicated = queue_provider_sync(
        db,
        tenant_id=tenant_id,
        connection=connection,
    )
    publication = await asyncio.to_thread(drain_pending_outbox, limit=10)
    db.refresh(connection)
    return {
        "status": job.status,
        "deduplicated": deduplicated,
        "queue_publication": publication,
        "connection": public_connection(connection),
        "job": row_to_dict(job),
    }


@router.post("/connectors/provider-sync/{connection_id}/disconnect")
async def disconnect_provider(
    connection_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict:
    verify_connector_schema(db)
    connection = _connection(db, tenant_id, connection_id)
    remote_revoked = False
    remote_supported = connection.provider == "google_drive"
    try:
        credentials = load_connector_credentials(
            db,
            tenant_id=tenant_id,
            connection_id=connection.id,
        )
    except LookupError:
        credentials = {}

    if credentials and remote_supported:
        try:
            remote_revoked = await revoke_provider_credentials(connection.provider, credentials)
        except Exception:
            remote_revoked = False

    local_revoked = revoke_connector_credentials(
        db,
        tenant_id=tenant_id,
        connection_id=connection.id,
    )
    connection.status = "disconnected"
    connection.credentials_ref = None
    connection.last_error = None
    connection.updated_at = datetime.utcnow()
    config = dict(connection.config_json or {})
    config.update(
        {
            "authorization_status": "disconnected",
            "remote_revocation_supported": remote_supported,
            "remote_revocation_completed": remote_revoked,
            "disconnected_at": datetime.utcnow().isoformat(),
        }
    )
    connection.config_json = config
    db.commit()
    db.refresh(connection)
    return {
        "status": "disconnected",
        "local_credential_revoked": local_revoked,
        "remote_revocation_supported": remote_supported,
        "remote_revocation_completed": remote_revoked,
        "connection": public_connection(connection),
    }
