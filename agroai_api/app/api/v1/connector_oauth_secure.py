from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import _save_job, capabilities, connector_mode
from app.api.v1.connectors import create_or_get_connection, public_connection, row_to_dict, sanitize_config, verify_connector_schema
from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.services.connector_vault import credential_reference, store_connector_credentials, vault_configured
from app.services.oauth_state_store import issue_oauth_state
from app.services.oauth_urls import oauth_url


router = APIRouter(tags=["connector-security"])
ACCOUNT_PROVIDERS = {"gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce"}
SECRET_HINTS = ("secret", "token", "password", "api_key", "apikey", "credential", "private_key")


class SecureOAuthStartRequest(BaseModel):
    provider: Literal["gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce"]
    workspace_id: str | None = None
    redirect_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SecureConnectRequest(BaseModel):
    provider: Literal["wiseconn", "talgil", "universal_controller", "weather", "openet", "manual_csv", "chat_upload", "gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce", "google_earth_engine", "custom_api"]
    workspace_id: str | None = None
    mode: str | None = None
    display_name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    scopes: list[str] = Field(default_factory=list)
    send_reports_enabled: bool = False
    read_context_enabled: bool = True


def _secret_payload(config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in config.items():
        if any(hint in key.lower() for hint in SECRET_HINTS) and value not in (None, ""):
            result[key] = value
    return result


@router.post("/connectors/connect")
async def connect_secure(
    payload: SecureConnectRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    verify_connector_schema(db)
    mode = connector_mode(payload.provider, payload.mode)
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode=mode,
        display_name=payload.display_name,
        config=payload.config,
    )
    caps = capabilities(payload.provider)
    merged = dict(connection.config_json or {})
    merged.update(sanitize_config(payload.config))
    merged.update({
        "connector_hub_version": "secure-v3",
        "connection_pattern": mode,
        "read_context_enabled": payload.read_context_enabled,
        "send_reports_enabled": payload.send_reports_enabled,
        "scopes": payload.scopes,
        "capabilities": caps,
    })

    secrets = _secret_payload(payload.config)
    if payload.provider in ACCOUNT_PROVIDERS:
        connection.status = "authorization_required"
        connection.credentials_ref = None
        merged["authorization_status"] = "authorization_required"
    elif secrets:
        if not vault_configured():
            raise HTTPException(status_code=503, detail={"error": "connector_vault_not_configured"})
        vault_row = store_connector_credentials(
            db,
            tenant_id=tenant_id,
            connection=connection,
            provider=payload.provider,
            payload=secrets,
            scopes=payload.scopes,
        )
        connection.status = "connected"
        connection.credentials_ref = credential_reference(vault_row)
        merged["authorization_status"] = "connected"
    elif mode in {"manual_upload", "export_upload", "provider_assisted"}:
        connection.status = "ready"
        connection.credentials_ref = None
        merged["authorization_status"] = "ready"
    else:
        connection.status = "configuration_required"
        connection.credentials_ref = None
        merged["authorization_status"] = "configuration_required"

    connection.mode = mode
    connection.config_json = merged
    connection.last_error = None
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    job = _save_job(
        db,
        tenant_id=tenant_id,
        connection=connection,
        job_type="connector_connect",
        output_json={"status": connection.status, "capabilities": caps},
    )
    db.commit()
    db.refresh(connection)
    return {
        "status": connection.status,
        "message": f"{payload.provider} connection state updated.",
        "connection": public_connection(connection),
        "job": row_to_dict(job),
        "capabilities": caps,
    }


@router.post("/connectors/oauth/start")
async def start_oauth_secure(
    payload: SecureOAuthStartRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode="oauth",
        config=payload.metadata,
    )
    redirect_url = settings.API_URL.rstrip("/") + "/v1/connectors/oauth/callback"
    state = issue_oauth_state(
        db,
        connection=connection,
        tenant_id=tenant_id,
        provider=payload.provider,
        redirect_url=redirect_url,
    )
    authorization_url, oauth_error = oauth_url(payload.provider, state, redirect_url)
    caps = capabilities(payload.provider)
    merged = dict(connection.config_json or {})
    merged.update(sanitize_config({
        **payload.metadata,
        "oauth_error": oauth_error,
        "authorization_status": "oauth_ready" if authorization_url else "platform_setup_required",
        "capabilities": caps,
    }))
    connection.mode = "oauth"
    connection.status = "oauth_pending" if authorization_url else "platform_setup_required"
    connection.credentials_ref = None
    connection.config_json = merged
    connection.last_error = oauth_error
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    job = _save_job(
        db,
        tenant_id=tenant_id,
        connection=connection,
        job_type="oauth_start",
        status_value="completed_with_warnings" if oauth_error else "completed",
        output_json={"authorization_url_available": bool(authorization_url), "oauth_error": oauth_error},
    )
    db.commit()
    db.refresh(connection)
    return {
        "status": connection.status,
        "message": "OAuth authorization URL created." if authorization_url else "Provider OAuth platform configuration is incomplete.",
        "auth_url": authorization_url,
        "authorization_url": authorization_url,
        "oauth_error": oauth_error,
        "connection": public_connection(connection),
        "job": row_to_dict(job),
        "capabilities": caps,
    }
