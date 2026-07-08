from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.connectors import create_or_get_connection, public_connection, row_to_dict, safe_credential_ref, sanitize_config, verify_connector_schema
from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.services.connector_vault import credential_reference, store_connector_credentials
from app.services.oauth_state_store import consume_oauth_state, issue_oauth_state
from app.services.oauth_urls import oauth_url
from app.services.provider_oauth import (
    ProviderOAuthError,
    exchange_authorization_code,
    probe_provider_identity,
    scopes_from_payload,
    token_expiry,
    validate_scopes,
)
from app.services.provider_sync_jobs import queue_provider_sync

router = APIRouter(tags=["connector-launch"])
ProviderId = Literal["wiseconn", "talgil", "universal_controller", "weather", "openet", "manual_csv", "gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce", "john_deere", "google_earth_engine", "custom_api"]
APP_CONNECTOR_RETURN_URL = os.getenv("APP_URL", settings.APP_URL).rstrip("/") + "/"
API_OAUTH_CALLBACK_URL = os.getenv("API_OAUTH_CALLBACK_URL", settings.API_URL.rstrip("/") + "/v1/connectors/oauth/callback")
OAUTH_PROVIDERS = {"gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce", "john_deere"}

CONNECTOR_MANIFESTS: dict[str, dict[str, Any]] = {
    "gmail": {"provider": "gmail", "auth_pattern": "oauth", "label": "Gmail", "permissions": ["approved email context", "attachments"], "data_objects": ["messages", "attachments"], "required_env": ["GOOGLE_OAUTH_CLIENT_ID"], "production_next": "Configure Google OAuth client id and callback URL."},
    "google_drive": {"provider": "google_drive", "auth_pattern": "oauth", "label": "Google Drive", "permissions": ["approved folders", "documents"], "data_objects": ["folders", "documents", "PDFs", "spreadsheets"], "required_env": ["GOOGLE_OAUTH_CLIENT_ID"], "production_next": "Configure Google OAuth client id and callback URL."},
    "dropbox": {"provider": "dropbox", "auth_pattern": "oauth", "label": "Dropbox", "permissions": ["approved folders", "files"], "data_objects": ["folders", "files", "PDFs"], "required_env": ["DROPBOX_OAUTH_CLIENT_ID"], "production_next": "Configure Dropbox OAuth client id and callback URL."},
    "box": {"provider": "box", "auth_pattern": "oauth", "label": "Box", "permissions": ["approved enterprise folders", "files"], "data_objects": ["folders", "files", "PDFs"], "required_env": ["BOX_OAUTH_CLIENT_ID"], "production_next": "Configure Box OAuth client id and callback URL."},
    "slack": {"provider": "slack", "auth_pattern": "oauth", "label": "Slack", "permissions": ["approved channel metadata", "files"], "data_objects": ["channels", "messages", "files"], "required_env": ["SLACK_OAUTH_CLIENT_ID"], "production_next": "Configure Slack OAuth client id and callback URL."},
    "salesforce": {"provider": "salesforce", "auth_pattern": "oauth", "label": "Salesforce", "permissions": ["approved account context", "cases"], "data_objects": ["accounts", "cases"], "required_env": ["SALESFORCE_OAUTH_CLIENT_ID"], "production_next": "Configure Salesforce OAuth client id and callback URL."},
    "outlook": {"provider": "outlook", "auth_pattern": "oauth", "label": "Outlook", "permissions": ["approved email context", "attachments"], "data_objects": ["messages", "attachments"], "required_env": ["MICROSOFT_OAUTH_CLIENT_ID"], "production_next": "Configure Microsoft OAuth client id and callback URL."},
    "john_deere": {
        "provider": "john_deere",
        "auth_pattern": "oauth",
        "label": "John Deere Operations Center",
        "permissions": ["customer-authorized read access", "approved operational context"],
        "data_objects": ["organizations", "clients", "farms", "fields", "boundaries", "field operations", "equipment reference", "crop types", "guidance lines", "users", "organization settings"],
        "required_env": ["JOHN_DEERE_OAUTH_CLIENT_ID", "JOHN_DEERE_OAUTH_CLIENT_SECRET"],
        "production_next": "Authorize a customer Operations Center account. Work Plans are intentionally excluded from phase-one sync.",
    },
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


def callback_url_for(provider: str) -> str:
    return os.getenv(f"{provider.upper()}_OAUTH_REDIRECT_URI", API_OAUTH_CALLBACK_URL).strip() or API_OAUTH_CALLBACK_URL


def return_url(provider: str, status: str, connection_id: str | None = None) -> str:
    extra = f"&connection_id={connection_id}" if connection_id else ""
    return f"{APP_CONNECTOR_RETURN_URL}?connector={provider}&status={status}{extra}"


def html_status(provider: str, status: str, message: str, connection_id: str | None = None) -> HTMLResponse:
    href = return_url(provider, status, connection_id)
    return HTMLResponse(f"<html><body><h2>Connector {status.replace('_', ' ')}</h2><p>{message}</p><p><a href='{href}'>Return to AGRO-AI</a></p></body></html>")


def _safe_error(exc: Exception) -> str:
    text = re.sub(r"(?i)(access_token|refresh_token|client_secret|code)=?[^\s,&]+", r"\1=[redacted]", str(exc))
    return text[:900]


async def exchange_dropbox_code(code: str) -> dict[str, Any]:
    client_id = os.getenv("DROPBOX_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("DROPBOX_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Dropbox OAuth client configuration is missing.")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://api.dropboxapi.com/oauth2/token",
            data={"code": code, "grant_type": "authorization_code", "client_id": client_id, "client_secret": client_secret, "redirect_uri": callback_url_for("dropbox")},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Dropbox token exchange failed with status {response.status_code}")
    return response.json()


async def probe_dropbox(access_token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        account_response = await client.post("https://api.dropboxapi.com/2/users/get_current_account", headers=headers)
        if account_response.status_code >= 400:
            raise RuntimeError(f"Dropbox account probe failed with status {account_response.status_code}")
        files_response = await client.post("https://api.dropboxapi.com/2/files/list_folder", headers={**headers, "Content-Type": "application/json"}, json={"path": "", "limit": 10})
    account = account_response.json()
    files = files_response.json() if files_response.status_code < 400 else {"entries": []}
    entries = files.get("entries", []) if isinstance(files, dict) else []
    return {"account_id": account.get("account_id"), "email": account.get("email"), "name": (account.get("name") or {}).get("display_name") if isinstance(account.get("name"), dict) else None, "files_preview": [{"name": item.get("name"), "path_lower": item.get("path_lower"), "tag": item.get(".tag")} for item in entries[:10] if isinstance(item, dict)], "file_count_preview": len(entries)}


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
    return {**item, "configured": configured, "readiness": readiness, "callback_url": callback_url_for(provider) if item["auth_pattern"] == "oauth" else None, "customer_promise": "AGRO-AI only uses approved customer context and stores a cited import trail."}


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
    verify_connector_schema(db)
    manifest = manifest_for(payload.provider)
    auth_pattern = manifest["auth_pattern"]
    mode = "oauth" if auth_pattern == "oauth" else auth_pattern
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=mode, display_name=manifest["label"], config={"surface": "launch_connector_flow", "account_hint": payload.account_hint, "field_scope": payload.field_scope, "access_note": payload.access_note, "launch_manifest": manifest, **payload.metadata})
    auth_url = None
    auth_error = None
    if auth_pattern == "oauth":
        redirect_uri = callback_url_for(payload.provider)
        state = issue_oauth_state(db, connection=connection, tenant_id=tenant_id, provider=payload.provider, redirect_url=redirect_uri)
        auth_url, auth_error = oauth_url(payload.provider, state, redirect_uri)
        status_value = "oauth_pending" if auth_url else "platform_setup_required"
    elif auth_pattern == "service_account":
        status_value = "service_account_ready" if manifest["configured"] else "service_account_missing"
    else:
        status_value = "provider_access_ready" if manifest["configured"] else "provider_access_requested"
    merged = dict(connection.config_json or {})
    merged.update(sanitize_config({"surface": "launch_connector_flow", "launch_manifest": manifest, "authorization_status": status_value, "account_hint": payload.account_hint, "field_scope": payload.field_scope, "access_note": payload.access_note, "oauth_error": auth_error, "auth_url_available": bool(auth_url)}))
    connection.config_json = merged
    connection.status = status_value
    connection.updated_at = datetime.utcnow()
    connection.last_error = auth_error
    if payload.account_hint or payload.field_scope:
        connection.credentials_ref = safe_credential_ref(payload.account_hint or payload.field_scope)
    job = save_launch_job(db, tenant_id, connection, "launch_authorization_start", {"provider": payload.provider, "auth_pattern": auth_pattern, "status": status_value, "auth_url_available": bool(auth_url), "permissions": manifest["permissions"], "data_objects": manifest["data_objects"], "next_step": manifest["production_next"]}, "completed_with_warnings" if auth_error else "completed")
    db.commit()
    db.refresh(connection)
    return {"status": status_value, "connection": public_connection(connection), "manifest": manifest, "auth_url": auth_url, "authorization_url": auth_url, "url": auth_url, "redirect_url": auth_url, "oauth_error": auth_error, "job": row_to_dict(job), "message": "Provider authorization URL created." if auth_url else manifest["production_next"]}


@router.post("/connectors/launch/access-request")
async def create_access_request(payload: AccessRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    manifest = manifest_for(payload.provider)
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=manifest["auth_pattern"], display_name=payload.display_name or manifest["label"], config={"surface": "access_request", "environment_url": payload.environment_url, "field_scope": payload.field_scope, "account_hint": payload.account_hint, "launch_manifest": manifest, **payload.metadata})
    merged = dict(connection.config_json or {})
    merged.update(sanitize_config({"authorization_status": "access_requested", "environment_url": payload.environment_url, "field_scope": payload.field_scope, "account_hint": payload.account_hint, "launch_manifest": manifest}))
    connection.config_json = merged
    connection.status = "access_requested"
    connection.credentials_ref = safe_credential_ref(payload.credential_ref or payload.account_hint or payload.environment_url)
    connection.updated_at = datetime.utcnow()
    job = save_launch_job(db, tenant_id, connection, "access_request", {"provider": payload.provider, "status": "access_requested"})
    db.commit()
    db.refresh(connection)
    return {"status": "access_requested", "connection": public_connection(connection), "manifest": manifest, "job": row_to_dict(job)}


def _consume_state_for_known_callback(db: Session, state: str | None) -> dict[str, Any] | None:
    candidates = {API_OAUTH_CALLBACK_URL}
    for provider in OAUTH_PROVIDERS:
        candidates.add(callback_url_for(provider))
    for redirect_uri in candidates:
        payload = consume_oauth_state(db, state=state, redirect_url=redirect_uri)
        if payload is not None:
            payload["validated_redirect_uri"] = redirect_uri
            return payload
    return None


@router.get("/connectors/oauth/callback")
async def oauth_callback(code: str | None = Query(default=None), state: str | None = Query(default=None), error: str | None = Query(default=None), db: Session = Depends(get_db)):
    verify_connector_schema(db)
    verified = _consume_state_for_known_callback(db, state)
    if not verified:
        return html_status("unknown", "authorization_failed", "AGRO-AI could not validate this OAuth callback. The state may be invalid, expired, or already used.")
    connection = db.get(ConnectorConnection, str(verified["cid"]))
    if connection is None or connection.tenant_id != str(verified["tid"]) or connection.provider != str(verified["provider"]):
        return html_status("unknown", "authorization_failed", "AGRO-AI could not validate connector ownership for this callback.")
    provider = connection.provider
    if error or not code:
        merged = dict(connection.config_json or {})
        merged.update(sanitize_config({"oauth_callback_received": True, "oauth_code_present": bool(code), "oauth_error": error, "authorization_status": "authorization_failed"}))
        connection.config_json = merged
        connection.status = "authorization_failed"
        connection.last_error = (error or "missing_oauth_code")[:1200]
        connection.updated_at = datetime.utcnow()
        save_launch_job(db, connection.tenant_id, connection, "oauth_callback", {"code_present": bool(code), "error": error}, "completed_with_warnings")
        db.commit()
        return RedirectResponse(return_url(provider, "authorization_failed", connection.id))

    if provider == "dropbox":
        try:
            token = await exchange_dropbox_code(code)
            access_token = str(token.get("access_token") or "")
            probe = await probe_dropbox(access_token) if access_token else {}
            expires_at = None
            if token.get("expires_in"):
                expires_at = datetime.utcnow() + timedelta(seconds=int(token["expires_in"]))
            scopes = str(token.get("scope") or "").split()
            vault_row = store_connector_credentials(db, tenant_id=connection.tenant_id, connection=connection, provider="dropbox", payload=token, token_expires_at=expires_at, scopes=scopes)
            merged = dict(connection.config_json or {})
            merged.update(sanitize_config({"oauth_callback_received": True, "oauth_code_present": True, "authorization_status": "connected", "token_exchange_status": "completed", "token_type": token.get("token_type"), "scope": token.get("scope"), "provider_account_id": token.get("account_id") or token.get("uid") or probe.get("account_id"), "provider_account_email": probe.get("email"), "provider_account_name": probe.get("name"), "files_preview": probe.get("files_preview", []), "file_count_preview": probe.get("file_count_preview", 0), "refresh_token_present": bool(token.get("refresh_token"))}))
            connection.config_json = merged
            connection.status = "connected"
            connection.credentials_ref = credential_reference(vault_row)
            now = datetime.utcnow()
            connection.last_test_at = now
            connection.last_sync_at = now
            connection.last_error = None
            connection.updated_at = now
            save_launch_job(db, connection.tenant_id, connection, "oauth_token_exchange", {"provider": "dropbox", "status": "connected", "refresh_token_present": bool(token.get("refresh_token")), "account_probe": probe, "next_step": "Dropbox authorization and encrypted credential custody completed."})
            db.commit()
            return RedirectResponse(return_url("dropbox", "connected", connection.id))
        except Exception as exc:
            db.rollback()
            safe_error = _safe_error(exc)
            connection = db.get(ConnectorConnection, str(verified["cid"]))
            if connection is None:
                return html_status("dropbox", "token_exchange_failed", "Dropbox authorization failed after callback validation.")
            merged = dict(connection.config_json or {})
            merged.update(sanitize_config({"oauth_callback_received": True, "oauth_code_present": True, "authorization_status": "token_exchange_failed", "token_exchange_error": safe_error}))
            connection.config_json = merged
            connection.status = "token_exchange_failed"
            connection.last_error = safe_error
            connection.updated_at = datetime.utcnow()
            save_launch_job(db, connection.tenant_id, connection, "oauth_token_exchange", {"provider": "dropbox", "status": "token_exchange_failed", "error": safe_error}, "failed")
            db.commit()
            return RedirectResponse(return_url("dropbox", "token_exchange_failed", connection.id))

    if provider == "john_deere":
        try:
            redirect_uri = str(verified.get("validated_redirect_uri") or callback_url_for("john_deere"))
            token = await exchange_authorization_code("john_deere", code=code, redirect_uri=redirect_uri)
            scopes_ok, missing_scopes = validate_scopes("john_deere", token)
            if not scopes_ok:
                raise ProviderOAuthError(f"john_deere authorization missing required scope count={len(missing_scopes)}", reconnect_required=True)
            access_value = str(token.get("access_token") or "")
            identity = await probe_provider_identity("john_deere", access_value)
            scopes = scopes_from_payload(token)
            expires_at = token_expiry(token)
            vault_row = store_connector_credentials(db, tenant_id=connection.tenant_id, connection=connection, provider="john_deere", payload=token, token_expires_at=expires_at, scopes=scopes)
            merged = dict(connection.config_json or {})
            merged.update(sanitize_config({
                "oauth_callback_received": True,
                "oauth_code_present": True,
                "authorization_status": "connected",
                "token_exchange_status": "completed",
                "provider_account_id": identity.get("provider_account_id"),
                "provider_account_name": identity.get("provider_account_name"),
                "authorized_organization_count": identity.get("authorized_organization_count", 0),
                "organizations_preview": identity.get("organizations_preview", []),
                "scope": " ".join(scopes),
                "refresh_token_present": bool(token.get("refresh_token")),
                "token_expires_at": expires_at.isoformat() if expires_at else None,
                "read_only": True,
                "work_plans_included": False,
            }))
            connection.config_json = merged
            connection.status = "connected"
            connection.credentials_ref = credential_reference(vault_row)
            connection.last_test_at = datetime.utcnow()
            connection.last_error = None
            connection.updated_at = datetime.utcnow()
            save_launch_job(db, connection.tenant_id, connection, "oauth_token_exchange", {"provider": "john_deere", "status": "connected", "refresh_token_present": bool(token.get("refresh_token")), "authorized_organization_count": identity.get("authorized_organization_count", 0), "read_only": True, "work_plans_included": False})
            db.commit()
            # Queue the first bounded read sync immediately. The durable outbox owns
            # publication/retry and the provider worker performs the actual reads.
            queue_provider_sync(db, tenant_id=connection.tenant_id, connection=connection)
            return RedirectResponse(return_url("john_deere", "connected", connection.id))
        except Exception as exc:
            db.rollback()
            safe_error = _safe_error(exc)
            connection = db.get(ConnectorConnection, str(verified["cid"]))
            if connection is None:
                return html_status("john_deere", "token_exchange_failed", "John Deere authorization failed after callback validation.")
            reconnect_required = bool(isinstance(exc, ProviderOAuthError) and exc.reconnect_required)
            status_value = "reconnect_required" if reconnect_required else "token_exchange_failed"
            merged = dict(connection.config_json or {})
            merged.update(sanitize_config({"oauth_callback_received": True, "oauth_code_present": True, "authorization_status": status_value, "token_exchange_error": safe_error}))
            connection.config_json = merged
            connection.status = status_value
            connection.credentials_ref = None
            connection.last_error = safe_error
            connection.updated_at = datetime.utcnow()
            save_launch_job(db, connection.tenant_id, connection, "oauth_token_exchange", {"provider": "john_deere", "status": status_value, "error": safe_error}, "failed")
            db.commit()
            return RedirectResponse(return_url("john_deere", status_value, connection.id))

    merged = dict(connection.config_json or {})
    merged.update(sanitize_config({"oauth_callback_received": True, "oauth_code_present": True, "oauth_error": None, "authorization_status": "authorized_pending_token_exchange"}))
    connection.config_json = merged
    connection.status = "authorized_pending_token_exchange"
    connection.last_error = None
    connection.updated_at = datetime.utcnow()
    save_launch_job(db, connection.tenant_id, connection, "oauth_callback", {"code_present": True, "error": None, "next_step": "Exchange code server-side and store encrypted provider credentials."})
    db.commit()
    return html_status(provider, "authorized", "Authorization was received. This provider still needs a token-exchange adapter before file sync is enabled.", connection.id)
