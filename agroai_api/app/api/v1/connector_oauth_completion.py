from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.v1.connector_launch import (
    API_OAUTH_CALLBACK_URL,
    OAUTH_PROVIDERS,
    callback_url_for,
    exchange_dropbox_code,
    html_status,
    probe_dropbox,
    return_url,
    save_launch_job,
)
from app.api.v1.connectors import public_connection, sanitize_config, verify_connector_schema
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection
from app.services.connector_vault import credential_reference, store_connector_credentials
from app.services.oauth_state_store import consume_oauth_state
from app.services.provider_oauth import (
    ProviderOAuthError,
    exchange_authorization_code,
    probe_provider_identity,
    scopes_from_payload,
    token_expiry,
    validate_scopes,
)


router = APIRouter(tags=["connector-oauth-completion"])
_COMPLETED_PROVIDERS = {"dropbox", "google_drive", "outlook"}


def _consume_known_state(db: Session, state: str | None) -> dict[str, Any] | None:
    candidates = {API_OAUTH_CALLBACK_URL}
    for provider in OAUTH_PROVIDERS:
        candidates.add(callback_url_for(provider))
    for redirect_uri in candidates:
        payload = consume_oauth_state(db, state=state, redirect_url=redirect_uri)
        if payload is not None:
            payload["validated_redirect_uri"] = redirect_uri
            return payload
    return None


def _safe_failure_message(exc: Exception) -> str:
    if isinstance(exc, ProviderOAuthError):
        return str(exc)[:700]
    return f"{exc.__class__.__name__}: provider completion failed"[:700]


def _complete_connection(
    db: Session,
    *,
    connection: ConnectorConnection,
    provider: str,
    token: dict[str, Any],
    identity: dict[str, Any],
    expires_at: datetime | None,
    scopes: list[str],
) -> None:
    vault_row = store_connector_credentials(
        db,
        tenant_id=connection.tenant_id,
        connection=connection,
        provider=provider,
        payload=token,
        token_expires_at=expires_at,
        scopes=scopes,
    )
    now = datetime.utcnow()
    merged = dict(connection.config_json or {})
    merged.update(
        sanitize_config(
            {
                "oauth_callback_received": True,
                "oauth_code_present": True,
                "authorization_status": "connected",
                "token_exchange_status": "completed",
                "provider_account_id": identity.get("provider_account_id"),
                "provider_account_email": identity.get("provider_account_email"),
                "provider_account_name": identity.get("provider_account_name"),
                "scope": " ".join(scopes),
                "refresh_token_present": bool(token.get("refresh_token")),
                "token_expires_at": expires_at.isoformat() if expires_at else None,
            }
        )
    )
    connection.config_json = merged
    connection.status = "connected"
    connection.credentials_ref = credential_reference(vault_row)
    connection.last_test_at = now
    connection.last_error = None
    connection.updated_at = now
    save_launch_job(
        db,
        connection.tenant_id,
        connection,
        "oauth_token_exchange",
        {
            "provider": provider,
            "status": "connected",
            "refresh_token_present": bool(token.get("refresh_token")),
            "scope_count": len(scopes),
            "account_probe": identity,
        },
    )


@router.get("/connectors/oauth/callback")
async def oauth_completion_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    verify_connector_schema(db)
    verified = _consume_known_state(db, state)
    if not verified:
        return html_status(
            "unknown",
            "authorization_failed",
            "AGRO-AI could not validate this OAuth callback. The state may be invalid, expired, or already used.",
        )

    connection = db.get(ConnectorConnection, str(verified["cid"]))
    if (
        connection is None
        or connection.tenant_id != str(verified["tid"])
        or connection.provider != str(verified["provider"])
    ):
        return html_status(
            "unknown",
            "authorization_failed",
            "AGRO-AI could not validate connector ownership for this callback.",
        )

    provider = connection.provider
    if error or not code:
        merged = dict(connection.config_json or {})
        merged.update(
            sanitize_config(
                {
                    "oauth_callback_received": True,
                    "oauth_code_present": bool(code),
                    "oauth_error": error,
                    "authorization_status": "authorization_failed",
                }
            )
        )
        connection.config_json = merged
        connection.status = "authorization_failed"
        connection.last_error = (error or "missing_oauth_code")[:700]
        connection.updated_at = datetime.utcnow()
        save_launch_job(
            db,
            connection.tenant_id,
            connection,
            "oauth_callback",
            {"code_present": bool(code), "status": "authorization_failed"},
            "completed_with_warnings",
        )
        db.commit()
        return RedirectResponse(return_url(provider, "authorization_failed", connection.id))

    if provider not in _COMPLETED_PROVIDERS:
        merged = dict(connection.config_json or {})
        merged.update(
            sanitize_config(
                {
                    "oauth_callback_received": True,
                    "oauth_code_present": True,
                    "authorization_status": "authorized_pending_token_exchange",
                }
            )
        )
        connection.config_json = merged
        connection.status = "authorized_pending_token_exchange"
        connection.last_error = None
        connection.updated_at = datetime.utcnow()
        save_launch_job(
            db,
            connection.tenant_id,
            connection,
            "oauth_callback",
            {
                "provider": provider,
                "status": "authorized_pending_token_exchange",
                "next_step": "Provider is intentionally outside the completed launch adapter set.",
            },
        )
        db.commit()
        return html_status(
            provider,
            "authorized_pending_token_exchange",
            "Authorization was received, but this provider is not enabled for production synchronization in the current launch scope.",
            connection.id,
        )

    try:
        if provider == "dropbox":
            token = await exchange_dropbox_code(code)
            access_value = str(token.get("access_token") or "")
            probe = await probe_dropbox(access_value) if access_value else {}
            identity = {
                "provider_account_id": token.get("account_id") or token.get("uid") or probe.get("account_id"),
                "provider_account_email": probe.get("email"),
                "provider_account_name": probe.get("name"),
            }
            expires_at = None
            if token.get("expires_in"):
                expires_at = datetime.utcnow() + timedelta(seconds=int(token["expires_in"]))
            scopes = scopes_from_payload(token)
        else:
            token = await exchange_authorization_code(
                provider,
                code=code,
                redirect_uri=str(verified.get("validated_redirect_uri") or callback_url_for(provider)),
            )
            scopes_ok, missing_scopes = validate_scopes(provider, token)
            if not scopes_ok:
                raise ProviderOAuthError(
                    f"{provider} authorization did not grant required scope count={len(missing_scopes)}",
                    reconnect_required=True,
                )
            access_value = str(token.get("access_token") or "")
            identity = await probe_provider_identity(provider, access_value)
            expires_at = token_expiry(token)
            scopes = scopes_from_payload(token)

        _complete_connection(
            db,
            connection=connection,
            provider=provider,
            token=token,
            identity=identity,
            expires_at=expires_at,
            scopes=scopes,
        )
        db.commit()
        return RedirectResponse(return_url(provider, "connected", connection.id))
    except Exception as exc:
        db.rollback()
        connection = db.get(ConnectorConnection, str(verified["cid"]))
        if connection is None:
            return html_status(provider, "token_exchange_failed", "Provider authorization could not be completed.")
        safe_error = _safe_failure_message(exc)
        reconnect_required = bool(isinstance(exc, ProviderOAuthError) and exc.reconnect_required)
        status_value = "reconnect_required" if reconnect_required else "token_exchange_failed"
        merged = dict(connection.config_json or {})
        merged.update(
            sanitize_config(
                {
                    "oauth_callback_received": True,
                    "oauth_code_present": True,
                    "authorization_status": status_value,
                    "token_exchange_error": safe_error,
                }
            )
        )
        connection.config_json = merged
        connection.status = status_value
        connection.credentials_ref = None
        connection.last_error = safe_error
        connection.updated_at = datetime.utcnow()
        save_launch_job(
            db,
            connection.tenant_id,
            connection,
            "oauth_token_exchange",
            {"provider": provider, "status": status_value, "error": safe_error},
            "failed",
        )
        db.commit()
        return RedirectResponse(return_url(provider, status_value, connection.id))
