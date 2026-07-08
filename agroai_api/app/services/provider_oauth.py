from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import httpx


class ProviderOAuthError(RuntimeError):
    def __init__(self, message: str, *, reconnect_required: bool = False, retryable: bool = False):
        super().__init__(message)
        self.reconnect_required = reconnect_required
        self.retryable = retryable


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DRIVE_BASE_URL = "https://www.googleapis.com/drive/v3"
JOHN_DEERE_TOKEN_URL = "https://signin.johndeere.com/oauth2/aus78tnlaysMraFhC1t7/v1/token"
JOHN_DEERE_API_BASE_URL = "https://api.deere.com/platform"


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ProviderOAuthError(f"Provider platform configuration is incomplete: {name}")
    return value


def _status_error(provider: str, operation: str, response: httpx.Response) -> ProviderOAuthError:
    reconnect = response.status_code in {400, 401, 403}
    retryable = response.status_code in {408, 425, 429, 500, 502, 503, 504}
    return ProviderOAuthError(
        f"{provider} {operation} failed with status {response.status_code}",
        reconnect_required=reconnect,
        retryable=retryable,
    )


def token_expiry(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("expires_in")
    if value in (None, ""):
        return None
    try:
        seconds = max(0, int(value))
    except (TypeError, ValueError):
        return None
    return datetime.utcnow() + timedelta(seconds=seconds)


def required_scopes(provider: str) -> set[str]:
    if provider == "google_drive":
        return {"https://www.googleapis.com/auth/drive.readonly"}
    if provider == "outlook":
        return {"offline_access", "User.Read", "Mail.Read", "Files.Read"}
    # Deere route entitlements are governed by the registered application and
    # customer authorization. Do not hard-fail callback completion when the
    # token response omits an echo of the granted scope string.
    if provider == "john_deere":
        return set()
    return set()


def scopes_from_payload(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("scope") or ""
    if isinstance(raw, str):
        return [item for item in raw.replace(",", " ").split() if item]
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    return []


def validate_scopes(provider: str, payload: dict[str, Any]) -> tuple[bool, list[str]]:
    granted = set(scopes_from_payload(payload))
    missing = sorted(required_scopes(provider) - granted)
    return not missing, missing


def _deere_token_url() -> str:
    return os.getenv("JOHN_DEERE_OAUTH_TOKEN_URL", JOHN_DEERE_TOKEN_URL).strip() or JOHN_DEERE_TOKEN_URL


def _deere_api_base() -> str:
    return os.getenv("JOHN_DEERE_API_BASE_URL", JOHN_DEERE_API_BASE_URL).rstrip("/")


def _collection_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("values", "items", "results", "organizations"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    embedded = payload.get("_embedded")
    if isinstance(embedded, dict):
        for value in embedded.values():
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


async def exchange_authorization_code(provider: str, *, code: str, redirect_uri: str) -> dict[str, Any]:
    if provider == "google_drive":
        data = {
            "code": code,
            "client_id": _required_env("GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": _required_env("GOOGLE_OAUTH_CLIENT_SECRET"),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        url = GOOGLE_TOKEN_URL
    elif provider == "outlook":
        data = {
            "code": code,
            "client_id": _required_env("MICROSOFT_OAUTH_CLIENT_ID"),
            "client_secret": _required_env("MICROSOFT_OAUTH_CLIENT_SECRET"),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "scope": "offline_access User.Read Mail.Read Files.Read",
        }
        url = MICROSOFT_TOKEN_URL
    elif provider == "john_deere":
        data = {
            "code": code,
            "client_id": _required_env("JOHN_DEERE_OAUTH_CLIENT_ID"),
            "client_secret": _required_env("JOHN_DEERE_OAUTH_CLIENT_SECRET"),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        url = _deere_token_url()
    else:
        raise ProviderOAuthError(f"No production token-exchange adapter exists for provider '{provider}'")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if response.status_code >= 400:
        raise _status_error(provider, "token exchange", response)
    payload = response.json()
    if not payload.get("access_token"):
        raise ProviderOAuthError(f"{provider} token exchange returned no access credential")
    return payload


async def refresh_provider_credentials(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    refresh_value = str(payload.get("refresh_token") or "")
    if not refresh_value:
        raise ProviderOAuthError(f"{provider} refresh credential is unavailable", reconnect_required=True)

    if provider == "google_drive":
        data = {
            "refresh_token": refresh_value,
            "client_id": _required_env("GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": _required_env("GOOGLE_OAUTH_CLIENT_SECRET"),
            "grant_type": "refresh_token",
        }
        url = GOOGLE_TOKEN_URL
    elif provider == "outlook":
        data = {
            "refresh_token": refresh_value,
            "client_id": _required_env("MICROSOFT_OAUTH_CLIENT_ID"),
            "client_secret": _required_env("MICROSOFT_OAUTH_CLIENT_SECRET"),
            "grant_type": "refresh_token",
            "scope": "offline_access User.Read Mail.Read Files.Read",
        }
        url = MICROSOFT_TOKEN_URL
    elif provider == "john_deere":
        data = {
            "refresh_token": refresh_value,
            "client_id": _required_env("JOHN_DEERE_OAUTH_CLIENT_ID"),
            "client_secret": _required_env("JOHN_DEERE_OAUTH_CLIENT_SECRET"),
            "grant_type": "refresh_token",
        }
        url = _deere_token_url()
    else:
        raise ProviderOAuthError(f"No production refresh adapter exists for provider '{provider}'")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if response.status_code >= 400:
        error = _status_error(provider, "credential refresh", response)
        if response.status_code == 400:
            error.reconnect_required = True
        raise error
    refreshed = response.json()
    if not refreshed.get("access_token"):
        raise ProviderOAuthError(f"{provider} refresh returned no access credential", reconnect_required=True)

    merged = dict(payload)
    merged.update(refreshed)
    if not refreshed.get("refresh_token"):
        merged["refresh_token"] = refresh_value
    return merged


async def probe_provider_identity(provider: str, access_value: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_value}"}
    if provider == "google_drive":
        url = f"{DRIVE_BASE_URL}/about"
        params = {"fields": "user(displayName,emailAddress,permissionId),storageQuota(limit,usage)"}
    elif provider == "outlook":
        url = f"{GRAPH_BASE_URL}/me"
        params = {"$select": "id,displayName,mail,userPrincipalName"}
    elif provider == "john_deere":
        url = f"{_deere_api_base()}/organizations"
        params = {}
        headers["Accept"] = "application/json"
    else:
        raise ProviderOAuthError(f"No production identity probe exists for provider '{provider}'")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers=headers, params=params)
    if response.status_code >= 400:
        raise _status_error(provider, "identity probe", response)
    data = response.json()
    if provider == "google_drive":
        user = data.get("user") or {}
        quota = data.get("storageQuota") or {}
        return {
            "provider_account_id": user.get("permissionId"),
            "provider_account_email": user.get("emailAddress"),
            "provider_account_name": user.get("displayName"),
            "quota_usage": quota.get("usage"),
            "quota_limit": quota.get("limit"),
        }
    if provider == "john_deere":
        organizations = _collection_items(data)
        preview = []
        for item in organizations[:10]:
            preview.append({
                "id": item.get("id") or item.get("organizationId") or item.get("uid"),
                "name": item.get("name") or item.get("displayName"),
            })
        first = preview[0] if preview else {}
        return {
            "provider_account_id": first.get("id"),
            "provider_account_name": first.get("name") or "John Deere Operations Center",
            "authorized_organization_count": len(organizations),
            "organizations_preview": preview,
        }
    return {
        "provider_account_id": data.get("id"),
        "provider_account_email": data.get("mail") or data.get("userPrincipalName"),
        "provider_account_name": data.get("displayName"),
    }


async def revoke_provider_credentials(provider: str, payload: dict[str, Any]) -> bool:
    if provider != "google_drive":
        return False
    value = str(payload.get("refresh_token") or payload.get("access_token") or "")
    if not value:
        return False
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_REVOKE_URL,
            params={"token": value},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code not in {200, 204, 400}:
        raise _status_error(provider, "revocation", response)
    return response.status_code in {200, 204}
