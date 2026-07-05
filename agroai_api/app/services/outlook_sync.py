from __future__ import annotations

import asyncio
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.models.operational_records import ConnectorConnection
from app.services.provider_oauth import ProviderOAuthError
from app.services.provider_record_store import parse_observed_at, store_provider_record
from app.services.provider_sync_state import get_sync_cursor


GRAPH_HOST = "graph.microsoft.com"
INITIAL_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$top=100"


async def request_page(client: httpx.AsyncClient, url: str, access_value: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != GRAPH_HOST:
        raise ProviderOAuthError("Outlook pagination URL is outside the approved host")
    headers = {"Authorization": "Bearer " + access_value}
    for attempt in range(4):
        response = await client.get(url, headers=headers)
        if response.status_code < 400:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ProviderOAuthError("Outlook sync returned an invalid payload")
        if response.status_code in {401, 403}:
            raise ProviderOAuthError("Outlook authorization is no longer usable", reconnect_required=True)
        if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < 3:
            await asyncio.sleep(min(5.0, 0.5 * (2 ** attempt)))
            continue
        raise ProviderOAuthError(
            f"Outlook sync failed with status {response.status_code}",
            retryable=response.status_code in {408, 429, 500, 502, 503, 504},
        )
    raise ProviderOAuthError("Outlook sync retries exhausted", retryable=True)


def store_message(db: Session, connection: ConnectorConnection, item: dict) -> bool:
    object_id = str(item.get("id") or "")
    if not object_id or item.get("@removed"):
        return False
    subject = str(item.get("subject") or "Outlook message")
    observed = parse_observed_at(item.get("lastModifiedDateTime") or item.get("receivedDateTime"))
    version = str(item.get("lastModifiedDateTime") or item.get("receivedDateTime") or object_id)
    preview = str(item.get("bodyPreview") or "")[:1200]
    return store_provider_record(
        db,
        connection=connection,
        object_id=object_id,
        version=version,
        name=subject,
        record_type="email_record",
        summary=("Outlook message: " + subject + ". " + preview),
        observed_at=observed,
        metadata={
            "provider_object_id": object_id,
            "received_at": item.get("receivedDateTime"),
            "modified_at": item.get("lastModifiedDateTime"),
            "has_attachments": bool(item.get("hasAttachments")),
        },
    )


async def sync_outlook(db: Session, connection: ConnectorConnection, access_value: str) -> dict:
    cursor = get_sync_cursor(db, connection=connection)
    cursor.last_attempt_at = datetime.utcnow()
    cursor.status = "syncing"
    db.commit()

    url = cursor.cursor or INITIAL_URL
    next_cursor = cursor.cursor
    inserted = 0
    seen = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            data = await request_page(client, url, access_value)
            for item in data.get("value") or []:
                if isinstance(item, dict) and not item.get("@removed"):
                    seen += 1
                    inserted += int(store_message(db, connection, item))
            next_link = data.get("@odata.nextLink")
            delta_link = data.get("@odata.deltaLink")
            if delta_link:
                next_cursor = str(delta_link)
            url = str(next_link) if next_link else ""

    cursor.cursor = next_cursor
    cursor.cursor_json = {"provider": "outlook", "mode": "delta", "last_seen": seen}
    cursor.status = "ready"
    cursor.last_success_at = datetime.utcnow()
    cursor.updated_at = datetime.utcnow()
    db.commit()
    return {"provider": "outlook", "seen": seen, "inserted": inserted, "cursor_advanced": bool(cursor.cursor)}
