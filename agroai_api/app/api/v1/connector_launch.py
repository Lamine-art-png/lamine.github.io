from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.connectors import create_or_get_connection, ensure_schema, public_connection, row_to_dict, safe_credential_ref, sanitize_config
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.services.oauth_urls import oauth_url

router = APIRouter(tags=["connector-launch"])
ProviderId = Literal["wiseconn", "talgil", "universal_controller", "weather", "openet", "manual_csv", "gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce", "google_earth_engine", "custom_api"]
APP_CONNECTOR_RETURN_URL = "https://app.agroai-pilot.com/connectors"
API_OAUTH_CALLBACK_URL = "https://api.agroai-pilot.com/v1/connectors/oauth/callback"

CONNECTOR_MANIFESTS: dict[str, dict[str, Any]] = {
    "gmail": {"provider": "gmail", "auth_pattern": "oauth", "label": "Gmail", "permissions": ["approved email context", "attachments"], "data_objects": ["messages", "attachments"], "required_env": ["GOOGLE_OAUTH_CLIENT_ID"], "production_next": "Configure Google OAuth client id and callback URL."},
    "google_drive": {"provider": "google_drive", "auth_pattern": "oauth", "label": "Google Drive", "permissions": ["approved folders", "documents"], "data_objects": ["folders", "documents", "PDFs", "spreadsheets"], "required_env": ["GOOGLE_OAUTH_CLIENT_ID"], "production_next": "Configure Google OAuth client id and callback URL."},
    "dropbox": {"provider": "dropbox", "auth_pattern": "oauth", "label": "Dropbox", "permissions": ["approved folders", "files"], "data_objects": ["folders", "files", "PDFs"], "required_env": ["DROPBOX_OAUTH_CLIENT_ID"], "production_next": "Configure Dropbox OAuth client id and callback URL."},
    "box": {"provider": "box", "auth_pattern": "oauth", "label": "Box", "permissions": ["approved enterprise folders", "files"], "data_objects": ["folders", "files", "PDFs"], "required_env": ["BOX_OAUTH_CLIENT_ID"], "production_next": "Configure Box OAuth client id and callback URL."},
    "slack": {"provider": "slack", "auth_pattern": "oauth", "label": "Slack", "permissions": ["approved channel metadata", "files"], "data_objects": ["channels", "messages", "files"], "required_env": ["SLACK_OAUTH_CLIENT_ID"], "production_next": "Configure Slack OAuth client id and callback URL."},
    "salesforce": {"provider": "salesforce", "auth_pattern": "oauth", "label": "Salesforce", "permissions": ["approved account context", "cases"], "data_objects": ["accounts", "cases"], "required_env": ["SALESFORCE_OAUTH_CLIENT_ID"], "production_next": "Configure Salesforce OAuth client id and callback URL."},
    "outlook": {"provider": "outlook", "auth_pattern": "oauth", "label": "Outlook", "permissions": ["approved email context", "attachments"], "data_objects": ["messages", "attachments"], "required_env": ["MICROSOFT_OAUTH_CLIENT_ID"], "production_next": "Configure Microsoft OAuth client id and callback URL."},
    "wiseconn": {"provider": "wiseconn", "auth_pattern": "provider_api", "label": "WiseConn", "permissions": ["controller read access"], "data_objects": ["zones", "events", "flow"], "required_env": ["WISECONN_API_KEY"], "production_next": "Store customer WiseConn credential reference before live sync."},
    "talgil": {"provider": "talgil", "auth_pattern": "provider_api", "label": "Talgil", "permissions": ["controller read access"], "data_objects": ["programs", "zones", "flow"], "required_env": ["TALGIL_API_KEY"], "production_next": "Store customer Talgil credential reference before live sync."},
    "universal_controller": {"provider": "universal_controller", "auth_pattern": "enterprise_api", "label": "Universal Controller Gateway", "permissions": ["approved exports or API payloads"], "data_objects": ["farms", "fields", "zones", "valves", "pumps"], "required_env": [], "production_next": "Map the customer controller data contract."},
    "openet": {"provider": "openet", "auth_pattern": "provider_api", "label": "OpenET", "permissions": ["ET context"], "data_objects": ["ET", "ET0"], "required_env": ["OPENET_API_KEY"], "production_next": "Configure provider credentials or upload ET export."},
    "google_earth_engine": {"provider": "google_earth_engine", "auth_pattern": "service_account", "label": "Google Earth Engine", "permissions": ["project assets"], "data_objects": ["imagery", "geospatial context"], "required_env": ["GOOGLE_EARTH_ENGINE_PROJECT_ID", "GOOGLE_EARTH_ENGINE_SERVICE_ACCOUNT_JSON"], "production_next": "Set Earth Engine project and service account env vars."},
    "weather": {"provider": "weather", "auth_pattern": "provider_api", "label": "Weather", "permissions": ["weather context"], "data_objects": ["forecast", "station data"], "required_env": [], "production_next": "Configure weather provider credentials or use upload."},
    "custom_api": {"provider": "custom_api", "auth_pattern": "enterprise_api", "label": "Data Provider API", "permissions": ["approved provider endpoints"], "data_objects": ["vendor records", "telemetry"], "required_env": [], "production_next": "Create provider-specific contract and endpoint map."},
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
    required = item.get("required_env", [])
    configured = all(os.getenv(name, "").strip() for name in required)
    if not required:
        readiness = "ready_to_configure"
    elif item["auth_pattern"] == "service_account":
        readiness = "service_account_ready" if configured else "needs_service_account"
    else:
        readiness = "ready_to_authorize" if configured else "needs_platform_setup"
    return {**item, "configured": configured, "readiness": readiness, "callback_url": API_OAUTH_CALLBACK_URL if item["auth_pattern"] == "oauth" else None, "customer_promise": "AGRO-AI only uses approved customer context and stores a cited import trail."}

def save_launch_job(db: Session, tenant_id: str, connection: ConnectorConnection, job_type: str, output_json: dict[str, Any], status: str = "completed") -> IngestionJob:
    job = IngestionJob(tenant_id=tenant_id, workspace_id=connection.workspace_id, connector_connection_id=connection.id, job_type=job_type, status=status, input_json={"provider": connection.provider, "mode": connection.mode}, output_json=output_json, completed_at=datetime.utcnow())
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
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=mode, display_name=manifest["label"], config={"surface": "launch_connector_flow", "account_hint": payload.account_hint, "field_scope": payload.field_scope, "access_note": payload.access_note, "launch_manifest": manifest, **payload.metadata})
    auth_url = None
    auth_error = None
    state = None
    if auth_pattern == "oauth":
        state = os.urandom(24).hex()
        auth_url, auth_error = oauth_url(payload.provider, state, payload.redirect_url or API_OAUTH_CALLBACK_URL)
        status_value = "oauth_ready" if auth_url else "platform_setup_required"
    elif auth_pattern == "service_account":
        status_value = "service_account_ready" if manifest["configured"] else "service_account_missing"
    else:
        status_value = "provider_access_ready" if manifest["configured"] else "provider_access_requested"
    merged = dict(connection.config_json or {})
    merged.update(sanitize_config({"surface": "launch_connector_flow", "launch_manifest": manifest, "authorization_status": status_value, "account_hint": payload.account_hint, "field_scope": payload.field_scope, "access_note": payload.access_note, "oauth_error": auth_error, "auth_url_available": bool(auth_url), "oauth_state": state}))
    connection.config_json = merged
    connection.status = status_value
    connection.updated_at = datetime.utcnow()
    connection.last_error = auth_error
    if payload.account_hint or payload.field_scope:
        connection.credentials_ref = safe_credential_ref(payload.account_hint or payload.field_scope)
    job = save_launch_job(db, tenant_id, connection, "launch_authorization_start", {"provider": payload.provider, "auth_pattern": auth_pattern, "status": status_value, "auth_url_available": bool(auth_url), "permissions": manifest["permissions"], "data_objects": manifest["data_objects"], "next_step": manifest["production_next"]}, "completed_with_warnings" if auth_error else "completed")
    db.commit()
    db.refresh(connection)
    return {"status": status_value, "connection": public_connection(connection), "manifest": manifest, "auth_url": auth_url, "oauth_error": auth_error, "job": row_to_dict(job), "message": "Provider authorization is ready." if auth_url else manifest["production_next"]}

@router.post("/connectors/launch/access-request")
async def create_access_request(payload: AccessRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    manifest = manifest_for(payload.provider)
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=manifest["auth_pattern"], display_name=payload.display_name or manifest["label"], config={"surface": "access_request", "environment_url": payload.environment_url, "field_scope": payload.field_scope, "account_hint": payload.account_hint, "launch_manifest": manifest, **payload.metadata})
    merged = dict(connection.config_json or {})
    merged.update(sanitize_config({"authorization_status": "access_requested", "environment_url": payload.environment_url, "field_scope": payload.field_scope, "account_hint": payload.account_hint, "launch_manifest": manifest}))
    connection.config_json = merged
    connection.status = "access_requested"
    connection.credentials_ref = safe_credential_ref(payload.credential_ref or payload.account_hint or payload.environment_url)
    connection.updated_at = datetime.utcnow()
    job = save_launch_job(db, tenant_id, connection, "provider_access_request", {"provider": payload.provider, "status": "access_requested", "permissions": manifest["permissions"], "data_objects": manifest["data_objects"], "next_step": manifest["production_next"]})
    db.commit()
    db.refresh(connection)
    return {"status": "access_requested", "connection": public_connection(connection), "manifest": manifest, "job": row_to_dict(job)}

@router.get("/connectors/oauth/callback")
async def oauth_callback(code: str | None = Query(default=None), state: str | None = Query(default=None), error: str | None = Query(default=None), db: Session = Depends(get_db)) -> HTMLResponse:
    ensure_schema(db)
    connection = None
    if state:
        rows = db.query(ConnectorConnection).order_by(ConnectorConnection.updated_at.desc()).limit(500).all()
        connection = next((row for row in rows if (row.config_json or {}).get("oauth_state") == state), None)
        if connection is None and ":" in state:
            connection = db.get(ConnectorConnection, state.split(":", 1)[0])
    if connection:
        merged = dict(connection.config_json or {})
        merged.update(sanitize_config({"oauth_callback_received": True, "oauth_code_present": bool(code), "oauth_error": error, "authorization_status": "authorized_pending_token_exchange" if code and not error else "authorization_failed"}))
        connection.config_json = merged
        connection.status = "authorized_pending_token_exchange" if code and not error else "authorization_failed"
        connection.last_error = error
        connection.updated_at = datetime.utcnow()
        save_launch_job(db, connection.tenant_id, connection, "oauth_callback", {"code_present": bool(code), "error": error, "next_step": "Exchange code server-side and store provider token reference."}, "completed_with_warnings" if error else "completed")
        db.commit()
    status_value = "authorized" if code and not error else "authorization_failed"
    return HTMLResponse(f"<html><body><h2>Connector {status_value.replace('_', ' ')}</h2><p>You can close this tab and return to AGRO-AI.</p><p><a href='{APP_CONNECTOR_RETURN_URL}'>Return to AGRO-AI</a></p></body></html>")
