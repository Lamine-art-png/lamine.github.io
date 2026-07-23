"""Official WhatsApp Cloud API transport.

No access token is accepted from a browser after connector setup. Per-tenant
tokens are loaded from the existing encrypted connector vault.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.whatsapp_runtime import floating, integer, value
from app.models.operational_records import ConnectorConnection
from app.services.connector_vault import load_connector_credentials

_ALLOWED_MEDIA_HOSTS = {
    "lookaside.fbsbx.com",
    "lookaside.facebook.com",
    "scontent.whatsapp.net",
}


class WhatsAppCloudError(RuntimeError):
    pass


def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = str(value("WHATSAPP_APP_SECRET", "") or "")
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    supplied = signature_header[7:].strip().lower()
    return hmac.compare_digest(expected, supplied)


def verify_challenge_token(supplied: str | None) -> bool:
    expected = str(value("WHATSAPP_VERIFY_TOKEN", "") or "")
    return bool(expected and supplied and hmac.compare_digest(expected.encode(), supplied.encode()))


def _api_version() -> str:
    version = str(value("WHATSAPP_GRAPH_API_VERSION", "") or "").strip()
    if not version:
        raise WhatsAppCloudError("WHATSAPP_GRAPH_API_VERSION is not configured")
    if not version.startswith("v") or not version[1:].replace(".", "").isdigit():
        raise WhatsAppCloudError("WHATSAPP_GRAPH_API_VERSION is invalid")
    return version


def _graph_url(path: str) -> str:
    base = str(value("WHATSAPP_GRAPH_API_BASE_URL", "https://graph.facebook.com") or "").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.hostname != "graph.facebook.com":
        if str(getattr(settings, "APP_ENV", "development")).lower() not in {"test", "development"}:
            raise WhatsAppCloudError("WhatsApp Graph API base URL is not allowed")
    return f"{base}/{_api_version()}/{path.lstrip('/')}"


def _token(db, connection: ConnectorConnection) -> str:
    credentials = load_connector_credentials(
        db, tenant_id=connection.tenant_id, connection_id=connection.id
    )
    token = str(credentials.get("access_token") or "").strip()
    if not token:
        raise WhatsAppCloudError("WhatsApp access token is unavailable")
    return token


def _timeout() -> httpx.Timeout:
    seconds = floating("WHATSAPP_HTTP_TIMEOUT_SECONDS", 20.0)
    return httpx.Timeout(seconds, connect=min(seconds, 10.0))


def _safe_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        message = ((payload.get("error") or {}).get("message") if isinstance(payload, dict) else None)
    except Exception:
        message = None
    return str(message or f"WhatsApp Cloud API returned HTTP {response.status_code}")[:500]


def probe_phone_number(db, connection: ConnectorConnection) -> dict:
    phone_number_id = str((connection.config_json or {}).get("phone_number_id") or "")
    if not phone_number_id:
        raise WhatsAppCloudError("phone_number_id is not configured")
    with httpx.Client(timeout=_timeout()) as client:
        response = client.get(
            _graph_url(phone_number_id),
            headers={"Authorization": f"Bearer {_token(db, connection)}"},
            params={"fields": "id,display_phone_number,verified_name,quality_rating"},
        )
    if response.status_code >= 400:
        raise WhatsAppCloudError(_safe_error(response))
    payload = response.json()
    return {
        "id": payload.get("id"),
        "display_phone_number": payload.get("display_phone_number"),
        "verified_name": payload.get("verified_name"),
        "quality_rating": payload.get("quality_rating"),
    }


def retrieve_media_to_temp(db, connection: ConnectorConnection, media_id: str) -> tuple[str, str, str, int]:
    token = _token(db, connection)
    headers = {"Authorization": f"Bearer {token}"}
    temp_path: str | None = None
    try:
        with httpx.Client(timeout=_timeout(), follow_redirects=False) as client:
            metadata_response = client.get(_graph_url(media_id), headers=headers)
            if metadata_response.status_code >= 400:
                raise WhatsAppCloudError(_safe_error(metadata_response))
            metadata = metadata_response.json()
            media_url = str(metadata.get("url") or "")
            mime_type = str(metadata.get("mime_type") or "application/octet-stream")[:200]
            expected_hash = str(metadata.get("sha256") or "")
            expected_size = int(metadata.get("file_size") or 0)

            parsed = urlparse(media_url)
            hostname = (parsed.hostname or "").lower()
            allowed = hostname in _ALLOWED_MEDIA_HOSTS or hostname.endswith(".facebook.com")
            if parsed.scheme != "https" or not allowed:
                raise WhatsAppCloudError("Meta returned an untrusted media URL")

            max_bytes = integer("WHATSAPP_MEDIA_MAX_BYTES", 50 * 1024 * 1024)
            if expected_size and expected_size > max_bytes:
                raise WhatsAppCloudError("WhatsApp media exceeds the configured size limit")

            with client.stream("GET", media_url, headers=headers) as response:
                if response.status_code >= 400:
                    raise WhatsAppCloudError(_safe_error(response))
                handle = tempfile.NamedTemporaryFile(prefix="agroai-wa-", delete=False)
                temp_path = handle.name
                digest = hashlib.sha256()
                total = 0
                try:
                    for chunk in response.iter_bytes(256 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise WhatsAppCloudError("WhatsApp media exceeds the configured size limit")
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                finally:
                    handle.close()

        actual_hash = digest.hexdigest()
        if expected_hash and not hmac.compare_digest(expected_hash.lower(), actual_hash):
            raise WhatsAppCloudError("WhatsApp media checksum verification failed")
        if expected_size and total != expected_size:
            raise WhatsAppCloudError("WhatsApp media length verification failed")
        return temp_path, mime_type, actual_hash, total
    except Exception:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
        raise


def send_text(db, connection: ConnectorConnection, *, to: str, body: str) -> str:
    phone_number_id = str((connection.config_json or {}).get("phone_number_id") or "")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    return _send_message(db, connection, phone_number_id, payload)


def send_template(
    db,
    connection: ConnectorConnection,
    *,
    to: str,
    name: str,
    language_code: str,
    parameters: list[str] | None = None,
) -> str:
    components = []
    if parameters:
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(value)[:1024]} for value in parameters[:20]],
        }]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language_code},
            **({"components": components} if components else {}),
        },
    }
    phone_number_id = str((connection.config_json or {}).get("phone_number_id") or "")
    return _send_message(db, connection, phone_number_id, payload)


def _send_message(db, connection: ConnectorConnection, phone_number_id: str, payload: dict) -> str:
    if not phone_number_id:
        raise WhatsAppCloudError("phone_number_id is not configured")
    with httpx.Client(timeout=_timeout()) as client:
        response = client.post(
            _graph_url(f"{phone_number_id}/messages"),
            headers={
                "Authorization": f"Bearer {_token(db, connection)}",
                "Content-Type": "application/json",
            },
            content=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        )
    if response.status_code >= 400:
        raise WhatsAppCloudError(_safe_error(response))
    result = response.json()
    messages = result.get("messages") if isinstance(result, dict) else None
    message_id = str((messages or [{}])[0].get("id") or "")
    if not message_id:
        raise WhatsAppCloudError("WhatsApp Cloud API did not return a message id")
    return message_id
