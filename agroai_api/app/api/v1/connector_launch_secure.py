from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.connector_launch import (
    AccessRequest,
    LaunchStartRequest,
    callback_url_for,
    manifest_for,
    save_launch_job,
)
from app.api.v1.connectors import (
    create_or_get_connection,
    public_connection,
    row_to_dict,
    sanitize_config,
    verify_connector_schema,
)
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.services.oauth_state_store import issue_oauth_state
from app.services.oauth_urls import oauth_url


router = APIRouter(tags=["connector-launch-security"])


@router.post("/connectors/launch/start")
async def start_launch_authorization_secure(
    payload: LaunchStartRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict:
    verify_connector_schema(db)
    manifest = manifest_for(payload.provider)
    auth_pattern = manifest["auth_pattern"]
    mode = "oauth" if auth_pattern == "oauth" else auth_pattern
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode=mode,
        display_name=manifest["label"],
        config={
            "surface": "launch_connector_flow",
            "account_hint": payload.account_hint,
            "field_scope": payload.field_scope,
            "access_note": payload.access_note,
            "launch_manifest": manifest,
            **payload.metadata,
        },
    )

    authorization_url = None
    auth_error = None
    if auth_pattern == "oauth":
        redirect_uri = callback_url_for(payload.provider)
        state = issue_oauth_state(
            db,
            connection=connection,
            tenant_id=tenant_id,
            provider=payload.provider,
            redirect_url=redirect_uri,
        )
        authorization_url, auth_error = oauth_url(payload.provider, state, redirect_uri)
        status_value = "oauth_pending" if authorization_url else "platform_setup_required"
    elif auth_pattern == "service_account":
        status_value = "service_account_ready" if manifest["configured"] else "service_account_missing"
    else:
        status_value = "provider_access_ready" if manifest["configured"] else "provider_access_requested"

    merged = dict(connection.config_json or {})
    merged.update(
        sanitize_config(
            {
                "surface": "launch_connector_flow",
                "launch_manifest": manifest,
                "authorization_status": status_value,
                "account_hint": payload.account_hint,
                "field_scope": payload.field_scope,
                "access_note": payload.access_note,
                "oauth_error": auth_error,
                "auth_url_available": bool(authorization_url),
            }
        )
    )
    connection.config_json = merged
    connection.status = status_value
    connection.credentials_ref = None
    connection.updated_at = datetime.utcnow()
    connection.last_error = auth_error
    job = save_launch_job(
        db,
        tenant_id,
        connection,
        "launch_authorization_start",
        {
            "provider": payload.provider,
            "auth_pattern": auth_pattern,
            "status": status_value,
            "auth_url_available": bool(authorization_url),
            "permissions": manifest["permissions"],
            "data_objects": manifest["data_objects"],
            "next_step": manifest["production_next"],
        },
        "completed_with_warnings" if auth_error else "completed",
    )
    db.commit()
    db.refresh(connection)
    return {
        "status": status_value,
        "connection": public_connection(connection),
        "manifest": manifest,
        "auth_url": authorization_url,
        "authorization_url": authorization_url,
        "url": authorization_url,
        "redirect_url": authorization_url,
        "oauth_error": auth_error,
        "job": row_to_dict(job),
        "message": "Provider authorization URL created." if authorization_url else manifest["production_next"],
    }


@router.post("/connectors/launch/access-request")
async def create_access_request_secure(
    payload: AccessRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict:
    verify_connector_schema(db)
    manifest = manifest_for(payload.provider)
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode=manifest["auth_pattern"],
        display_name=payload.display_name or manifest["label"],
        config={
            "surface": "access_request",
            "environment_url": payload.environment_url,
            "field_scope": payload.field_scope,
            "account_hint": payload.account_hint,
            "launch_manifest": manifest,
            **payload.metadata,
        },
    )
    merged = dict(connection.config_json or {})
    merged.update(
        sanitize_config(
            {
                "authorization_status": "access_requested",
                "environment_url": payload.environment_url,
                "field_scope": payload.field_scope,
                "account_hint": payload.account_hint,
                "launch_manifest": manifest,
            }
        )
    )
    connection.config_json = merged
    connection.status = "access_requested"
    connection.credentials_ref = None
    connection.updated_at = datetime.utcnow()
    job = save_launch_job(
        db,
        tenant_id,
        connection,
        "access_request",
        {"provider": payload.provider, "status": "access_requested"},
    )
    db.commit()
    db.refresh(connection)
    return {
        "status": "access_requested",
        "connection": public_connection(connection),
        "manifest": manifest,
        "job": row_to_dict(job),
    }
