from __future__ import annotations

import os
import urllib.parse
from typing import Any


def _query(base: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return f"{base}?{urllib.parse.urlencode(clean)}"


def oauth_url(provider: str, state: str, redirect_url: str) -> tuple[str | None, str | None]:
    """Return a provider authorization URL or a setup error.

    This helper is intentionally side-effect free. It lets Render import the API
    even when OAuth providers are not configured yet, while still returning a
    real auth URL as soon as the matching client id exists in env.
    """
    provider = (provider or "").strip().lower()
    if provider in {"gmail", "google_drive"}:
        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "GOOGLE_OAUTH_CLIENT_ID is not configured."
        scope = "https://www.googleapis.com/auth/drive.readonly" if provider == "google_drive" else "https://www.googleapis.com/auth/gmail.readonly"
        return _query("https://accounts.google.com/o/oauth2/v2/auth", {"client_id": client_id, "redirect_uri": redirect_url, "response_type": "code", "scope": scope, "access_type": "offline", "prompt": "consent", "state": state}), None
    if provider == "outlook":
        client_id = os.getenv("MICROSOFT_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "MICROSOFT_OAUTH_CLIENT_ID is not configured."
        return _query("https://login.microsoftonline.com/common/oauth2/v2.0/authorize", {"client_id": client_id, "redirect_uri": redirect_url, "response_type": "code", "scope": "offline_access User.Read Mail.Read Files.Read", "state": state}), None
    if provider == "john_deere":
        client_id = os.getenv("JOHN_DEERE_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "JOHN_DEERE_OAUTH_CLIENT_ID is not configured."
        authorize_url = os.getenv(
            "JOHN_DEERE_OAUTH_AUTHORIZE_URL",
            "https://signin.johndeere.com/oauth2/aus78tnlaysMraFhC1t7/v1/authorize",
        ).strip()
        # Keep Work Plans out of phase-one authorization. Route access remains
        # controlled by Deere app approval and the customer-authorized account.
        scopes = os.getenv(
            "JOHN_DEERE_OAUTH_SCOPES",
            "ag1 ag2 ag3 eq1 eq2 org1 org2 offline_access",
        ).strip()
        return _query(authorize_url, {"client_id": client_id, "redirect_uri": redirect_url, "response_type": "code", "scope": scopes, "state": state}), None
    if provider == "dropbox":
        client_id = os.getenv("DROPBOX_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "DROPBOX_OAUTH_CLIENT_ID is not configured."
        return _query("https://www.dropbox.com/oauth2/authorize", {"client_id": client_id, "redirect_uri": redirect_url, "response_type": "code", "token_access_type": "offline", "force_reapprove": "true", "state": state}), None
    if provider == "box":
        client_id = os.getenv("BOX_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "BOX_OAUTH_CLIENT_ID is not configured."
        return _query("https://account.box.com/api/oauth2/authorize", {"client_id": client_id, "redirect_uri": redirect_url, "response_type": "code", "state": state}), None
    if provider == "slack":
        client_id = os.getenv("SLACK_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "SLACK_OAUTH_CLIENT_ID is not configured."
        return _query("https://slack.com/oauth/v2/authorize", {"client_id": client_id, "redirect_uri": redirect_url, "scope": "channels:read,files:read,channels:history", "state": state}), None
    if provider == "salesforce":
        client_id = os.getenv("SALESFORCE_OAUTH_CLIENT_ID", "").strip()
        login_url = os.getenv("SALESFORCE_LOGIN_URL", "https://login.salesforce.com").rstrip("/")
        if not client_id:
            return None, "SALESFORCE_OAUTH_CLIENT_ID is not configured."
        return _query(f"{login_url}/services/oauth2/authorize", {"client_id": client_id, "redirect_uri": redirect_url, "response_type": "code", "state": state}), None
    return None, f"OAuth is not supported for provider '{provider}'."
