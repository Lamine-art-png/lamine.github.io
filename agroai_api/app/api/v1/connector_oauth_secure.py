from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import capabilities, _save_job
from app.api.v1.connectors import create_or_get_connection, public_connection, row_to_dict, sanitize_config, verify_connector_schema
from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.services.oauth_state_store import issue_oauth_state
from app.services.oauth_urls import oauth_url


router = APIRouter(tags=["connector-oauth-security"])


class SecureOAuthStartRequest(BaseModel):
    provider: Literal["gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce"]
    workspace_id: str | None = None
    redirect_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    merged.update(
        sanitize_config(
            {
                **payload.metadata,
                "oauth_error": oauth_error,
                "authorization_status": "oauth_ready" if authorization_url else "platform_setup_required",
                "capabilities": caps,
            }
        )
    )
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
