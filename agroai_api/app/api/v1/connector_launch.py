from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.connectors import (
    create_or_get_connection,
    ensure_schema,
    oauth_url,
    public_connection,
    row_to_dict,
    safe_credential_ref,
    sanitize_config,
)
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, IngestionJob

router = APIRouter(tags=["connector-launch"])

ProviderId = Literal[
    "wiseconn",
    "talgil",
    "weather",
    "openet",
    "manual_csv",
    "gmail",
    "outlook",
    "google_drive",
    "dropbox",
    "box",
    "slack",
    "salesforce",
    "google_earth_engine",
    "custom_api",
]

APP_CONNECTOR_RETURN_URL = "https://app.agroai-pilot.com/connectors"
API_OAUTH_CALLBACK_URL = "https://api.agroai-pilot.com/v1/connectors/oauth/callback"

CONNECTOR_MANIFESTS: dict[str, dict[str, Any]] = {
    "gmail": {
        "provider": "gmail",
        "auth_pattern": "oauth",
        "label": "Gmail",
        "headline": "Authorize Gmail context",
        "authorization_cta": "Continue with Google",
        "permissions": [
            "View approved operational email context",
            "Read relevant attachments and reports",
            "Prepare report drafts when requested",
        ],
        "data_objects": ["messages", "threads", "attachments", "sender context", "timestamps"],
        "required_env": ["GOOGLE_OAUTH_CLIENT_ID"],
        "production_next": "Create Google OAuth client and set the callback URL to /v1/connectors/oauth/callback.",
    },
    "google_drive": {
        "provider": "google_drive",
        "auth_pattern": "oauth",
        "label": "Google Drive",
        "headline": "Authorize Drive folders",
        "authorization_cta": "Continue with Google",
        "permissions": [
            "View approved folders and files",
            "Read PDFs, spreadsheets, maps, and reports",
            "Turn selected documents into citation-ready evidence",
        ],
        "data_objects": ["folders", "documents", "spreadsheets", "PDFs", "file metadata"],
        "required_env": ["GOOGLE_OAUTH_CLIENT_ID"],
        "production_next": "Create Google OAuth client and enable a folder-picker flow after authorization.",
    },
    "dropbox": {
        "provider": "dropbox",
        "auth_pattern": "oauth",
        "label": "Dropbox",
        "headline": "Authorize Dropbox folders",
        "authorization_cta": "Continue with Dropbox",
        "permissions": ["View approved folders and files", "Read PDFs, spreadsheets, and field evidence", "Create citation-ready file evidence"],
        "data_objects": ["folders", "files", "PDFs", "spreadsheets", "file metadata"],
        "required_env": ["DROPBOX_OAUTH_CLIENT_ID"],
        "production_next": "Set DROPBOX_OAUTH_CLIENT_ID and exchange the callback code server-side for a token reference.",
    },
    "box": {
        "provider": "box",
        "auth_pattern": "oauth",
        "label": "Box",
        "headline": "Authorize Box folders",
        "authorization_cta": "Continue with Box",
        "permissions": ["View approved enterprise folders", "Read PDFs, spreadsheets, and evidence packets", "Create citation-ready file evidence"],
        "data_objects": ["folders", "files", "PDFs", "spreadsheets", "enterprise file metadata"],
        "required_env": ["BOX_OAUTH_CLIENT_ID"],
        "production_next": "Set BOX_OAUTH_CLIENT_ID and exchange the callback code server-side for a token reference.",
    },
    "slack": {
        "provider": "slack",
        "auth_pattern": "oauth",
        "label": "Slack",
        "headline": "Authorize Slack operational context",
        "authorization_cta": "Continue with Slack",
        "permissions": ["View approved channel metadata", "Read approved files and operational messages", "Create cited handoff context"],
        "data_objects": ["channels", "messages", "files", "operator handoffs"],
        "required_env": ["SLACK_OAUTH_CLIENT_ID"],
        "production_next": "Set SLACK_OAUTH_CLIENT_ID and exchange the callback code server-side for a token reference.",
    },
    "salesforce": {
        "provider": "salesforce",
        "auth_pattern": "oauth",
        "label": "Salesforce",
        "headline": "Authorize Salesforce customer context",
        "authorization_cta": "Continue with Salesforce",
        "permissions": ["Read approved customer account context", "Read cases and customer-success notes", "Use context in reports and assurance workflows"],
        "data_objects": ["accounts", "contacts", "cases", "opportunities", "customer notes"],
        "required_env": ["SALESFORCE_OAUTH_CLIENT_ID"],
        "production_next": "Set SALESFORCE_OAUTH_CLIENT_ID and exchange the callback code server-side for a token reference.",
    },
    "outlook": {
        "provider": "outlook",
        "auth_pattern": "oauth",
        "label": "Outlook",
        "headline": "Authorize Microsoft email context",
        "authorization_cta": "Continue with Microsoft",
        "permissions": [
            "View approved operational email context",
            "Read attachments and reports",
            "Prepare report drafts when requested",
        ],
        "data_objects": ["messages", "attachments", "mail folders", "sender context"],
        "required_env": ["MICROSOFT_OAUTH_CLIENT_ID"],
        "production_next": "Register Microsoft app and set the redirect URL to /v1/connectors/oauth/callback.",
    },
    "wiseconn": {
        "provider": "wiseconn",
        "auth_pattern": "provider_api",
        "label": "WiseConn",
        "headline": "Connect controller environment",
        "authorization_cta": "Request WiseConn access package",
        "permissions": [
            "Read zones and controller events",
            "Read flow, runtime, and valve history",
            "Normalize irrigation logs into AGRO-AI evidence",
        ],
        "data_objects": ["zones", "controller events", "flow readings", "irrigation history", "valve state"],
        "required_env": ["WISECONN_API_KEY"],
        "production_next": "Store customer WiseConn credential reference, then enable scheduled live sync.",
    },
    "talgil": {
        "provider": "talgil",
        "auth_pattern": "provider_api",
        "label": "Talgil",
        "headline": "Connect Talgil controller environment",
        "authorization_cta": "Request Talgil access package",
        "permissions": [
            "Read programs, valves, zones, and flow events",
            "Read controller state and irrigation history",
            "Normalize controller records into AGRO-AI evidence",
        ],
        "data_objects": ["programs", "zones", "valve state", "flow readings", "irrigation events"],
        "required_env": ["TALGIL_API_KEY"],
        "production_next": "Store customer Talgil credential reference, then enable scheduled live sync.",
    },
    "openet": {
        "provider": "openet",
        "auth_pattern": "provider_api",
        "label": "OpenET",
        "headline": "Connect ET and water-use context",
        "authorization_cta": "Connect OpenET data access",
        "permissions": [
            "Read ET and ET0 context for approved fields",
            "Use field boundary references for water accounting",
            "Bring ET context into decisions and assurance reports",
        ],
        "data_objects": ["ET", "ET0", "field boundary references", "water-use estimates"],
        "required_env": ["OPENET_API_KEY"],
        "production_next": "Set provider API credentials or connect customer-approved ET export source.",
    },
    "google_earth_engine": {
        "provider": "google_earth_engine",
        "auth_pattern": "service_account",
        "label": "Google Earth Engine",
        "headline": "Verify Earth Engine project access",
        "authorization_cta": "Verify service account",
        "permissions": ["Use configured Earth Engine project", "Read approved geospatial assets", "Bring remote-sensing context into reports"],
        "data_objects": ["project assets", "imagery layers", "ET/geospatial context", "field boundary references"],
        "required_env": ["GOOGLE_EARTH_ENGINE_PROJECT_ID", "GOOGLE_EARTH_ENGINE_SERVICE_ACCOUNT_JSON"],
        "production_next": "Set Earth Engine project ID and service-account JSON env vars. No OAuth consent screen is used.",
    },
    "weather": {
        "provider": "weather",
        "auth_pattern": "provider_api",
        "label": "Weather",
        "headline": "Connect weather and forecast context",
        "authorization_cta": "Connect weather provider",
        "permissions": [
            "Read approved weather stations and forecast sources",
            "Use rainfall, temperature, humidity, and forecast context",
            "Bring weather risk into irrigation decisions",
        ],
        "data_objects": ["forecast", "station data", "rainfall", "temperature", "humidity"],
        "required_env": [],
        "production_next": "Set customer provider credentials or use upload/station feed.",
    },
    "custom_api": {
        "provider": "custom_api",
        "auth_pattern": "enterprise_api",
        "label": "Data Provider API",
        "headline": "Connect existing customer system",
        "authorization_cta": "Create data access request",
        "permissions": [
            "Read approved provider endpoints or exports",
            "Normalize vendor data into AGRO-AI evidence",
            "Keep every import auditable and source-cited",
        ],
        "data_objects": ["vendor API records", "SFTP drops", "district records", "ERP exports", "telemetry"],
        "required_env": [],
        "production_next": "Create provider-specific contract, endpoint map, and credential reference.",
    },
}


class LaunchStartRequest(BaseModel):
    provider: ProviderId
    workspace_id: str | None = None
    redirect_url: str | None = None
    account_hint: str | None = None
    field_scope: str | None = None
    access_note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccessRequest(BaseModel):
    provider: ProviderId
    workspace_id: str | None = None
    display_name: str | None = None
    account_hint: str | None = None
    environment_url: str | None = None
    field_scope: str | None = None
    credential_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def manifest_for(provider: str) -> dict[str, Any]:
    item = CONNECTOR_MANIFESTS.get(provider)
    if not item:
        raise HTTPException(status_code=404, detail="Unknown connector provider")
    configured = all(os.getenv(name, "").strip() for name in item.get("required_env", []))
    readiness = "ready_to_authorize" if configured else "needs_platform_setup"
    if item["auth_pattern"] == "service_account":
        readiness = "service_account_ready" if configured else "needs_service_account"
    if not item.get("required_env"):
        readiness = "ready_to_configure"
    return {
        **item,
        "configured": configured,
        "readiness": readiness,
        "callback_url": API_OAUTH_CALLBACK_URL if item["auth_pattern"] == "oauth" else None,
        "customer_promise": "AGRO-AI only uses approved customer context and stores a cited import trail.",
    }


def save_launch_job(db: Session, tenant_id: str, connection: ConnectorConnection, job_type: str, output_json: dict[str, Any], status: str = "completed") -> IngestionJob:
    job = IngestionJob(
        tenant_id=tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        job_type=job_type,
        status=status,
        input_json={"provider": connection.provider, "mode": connection.mode},
        output_json=output_json,
        completed_at=datetime.utcnow(),
    )
    db.add(job)
    return job


@router.get("/connectors/launch/manifest")
async def launch_manifest(provider: ProviderId | None = None, tenant_id: str = Depends(require_current_tenant_id)) -> dict[str, Any]:
    manifests = [manifest_for(provider)] if provider else [manifest_for(key) for key in CONNECTOR_MANIFESTS]
    return {"status": "ok", "tenant_id": tenant_id, "manifests": manifests}


@router.post("/connectors/launch/start")
async def start_launch_authorization(payload: LaunchStartRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
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

    auth_url = None
    auth_error = None
    state = None
    if auth_pattern == "oauth":
        state = os.urandom(24).hex()
        redirect_url = payload.redirect_url or API_OAUTH_CALLBACK_URL
        auth_url, auth_error = oauth_url(payload.provider, state, redirect_url)
        status = "oauth_ready" if auth_url else "platform_setup_required"
    elif auth_pattern == "service_account":
        status = "service_account_ready" if manifest["configured"] else "service_account_missing"
    else:
        status = "provider_access_ready" if manifest["configured"] else "provider_access_requested"

    merged = dict(connection.config_json or {})
    merged.update(sanitize_config({
        "surface": "launch_connector_flow",
        "launch_manifest": manifest,
        "authorization_status": status,
        "account_hint": payload.account_hint,
        "field_scope": payload.field_scope,
        "access_note": payload.access_note,
        "oauth_error": auth_error,
        "auth_url_available": bool(auth_url),
        "oauth_state": state,
    }))
    connection.config_json = merged
    connection.status = status
    connection.updated_at = datetime.utcnow()
    connection.last_error = auth_error
    if payload.account_hint or payload.field_scope:
        connection.credentials_ref = safe_credential_ref(payload.account_hint or payload.field_scope)

    job = save_launch_job(
        db,
        tenant_id,
        connection,
        "launch_authorization_start",
        {
            "provider": payload.provider,
            "auth_pattern": auth_pattern,
            "status": status,
            "auth_url_available": bool(auth_url),
            "permissions": manifest["permissions"],
            "data_objects": manifest["data_objects"],
            "next_step": manifest["production_next"],
        },
        "completed_with_warnings" if auth_error else "completed",
    )
    db.commit()
    db.refresh(connection)

    return {
        "status": status,
        "connection": public_connection(connection),
        "manifest": manifest,
        "auth_url": auth_url,
        "oauth_error": auth_error,
        "job": row_to_dict(job),
        "message": "Provider authorization is ready." if auth_url else manifest["production_next"],
    }


@router.post("/connectors/launch/access-request")
async def create_access_request(payload: AccessRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
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
    merged.update(sanitize_config({
        "authorization_status": "access_requested",
        "environment_url": payload.environment_url,
        "field_scope": payload.field_scope,
        "account_hint": payload.account_hint,
        "launch_manifest": manifest,
    }))
    connection.config_json = merged
    connection.status = "access_requested"
    connection.credentials_ref = safe_credential_ref(payload.credential_ref or payload.account_hint or payload.environment_url)
    connection.updated_at = datetime.utcnow()
    job = save_launch_job(
        db,
        tenant_id,
        connection,
        "provider_access_request",
        {
            "provider": payload.provider,
            "status": "access_requested",
            "permissions": manifest["permissions"],
            "data_objects": manifest["data_objects"],
            "next_step": manifest["production_next"],
        },
    )
    db.commit()
    db.refresh(connection)
    return {"status": "access_requested", "connection": public_connection(connection), "manifest": manifest, "job": row_to_dict(job)}


@router.get("/connectors/oauth/callback")
async def oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ensure_schema(db)
    connection = None
    if state:
        rows = db.query(ConnectorConnection).order_by(ConnectorConnection.updated_at.desc()).limit(500).all()
        connection = next((row for row in rows if (row.config_json or {}).get("oauth_state") == state), None)
        if connection is None and ":" in state:
            connection = db.get(ConnectorConnection, state.split(":", 1)[0])
    if connection:
        merged = dict(connection.config_json or {})
        merged.update(sanitize_config({
            "oauth_callback_received": True,
            "oauth_code_present": bool(code),
            "oauth_error": error,
            "authorization_status": "authorized_pending_token_exchange" if code and not error else "authorization_failed",
        }))
        connection.config_json = merged
        connection.status = "authorized_pending_token_exchange" if code and not error else "authorization_failed"
        connection.last_error = error
        connection.updated_at = datetime.utcnow()
        save_launch_job(
            db,
            connection.tenant_id,
            connection,
            "oauth_callback",
            {"code_present": bool(code), "error": error, "next_step": "Exchange code server-side and store provider token reference."},
            "completed_with_warnings" if error else "completed",
        )
        db.commit()
    status = "authorized" if code and not error else "authorization_failed"
    html = f"""
    <!doctype html>
    <html><head><meta charset=\"utf-8\"><title>AGRO-AI Connector</title></head>
    <body style=\"font-family: system-ui; padding: 32px;\">
      <h2>Connector {status.replace('_', ' ')}</h2>
      <p>You can close this tab and return to AGRO-AI.</p>
      <script>setTimeout(function() {{ window.location.href = '{APP_CONNECTOR_RETURN_URL}'; }}, 900);</script>
    </body></html>
    """
    return HTMLResponse(html)
