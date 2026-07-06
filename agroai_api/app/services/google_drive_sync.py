from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.models.operational_records import ConnectorConnection
from app.services.provider_oauth import ProviderOAuthError
from app.services.provider_record_store import parse_observed_at, store_provider_record
from app.services.provider_sync_state import get_sync_cursor


_DRIVE_HOST = "www.googleapis.com"
_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_CHANGES_URL = "https://www.googleapis.com/drive/v3/changes"
_START_TOKEN_URL = "https://www.googleapis.com/drive/v3/changes/startPageToken"


async def _request(
    client: httpx.AsyncClient,
    url: str,
    *,
    access_value: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _DRIVE_HOST:
        raise ProviderOAuthError("Google Drive pagination URL escaped the approved API host")
    headers = {"Authorization": "Bearer " + access_value}
    for attempt in range(4):
        response = await client.get(url, headers=headers, params=params)
        if response.status_code < 400:
            data = response.json()
            if isinstance(data, dict):
                return data
            raise ProviderOAuthError("Google Drive returned an invalid payload")
        if response.status_code in {401, 403}:
            raise ProviderOAuthError("Google Drive authorization is no longer usable", reconnect_required=True)
        if response.status_code in {408, 425, 429, 500, 502, 503, 504} and attempt < 3:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = min(5.0, max(0.2, float(retry_after))) if retry_after else min(5.0, 0.5 * (2 ** attempt))
            except ValueError:
                delay = min(5.0, 0.5 * (2 ** attempt))
            await asyncio.sleep(delay)
            continue
        raise ProviderOAuthError(
            f"Google Drive synchronization failed with status {response.status_code}",
            retryable=response.status_code in {408, 425, 429, 500, 502, 503, 504},
        )
    raise ProviderOAuthError("Google Drive synchronization retries exhausted", retryable=True)


def _store_file(db: Session, connection: ConnectorConnection, item: dict[str, Any], change_time: str | None = None) -> bool:
    object_id = str(item.get("id") or "")
    if not object_id or item.get("trashed"):
        return False
    name = str(item.get("name") or object_id)
    observed = parse_observed_at(item.get("modifiedTime") or change_time)
    version = str(
        item.get("modifiedTime")
        or item.get("md5Checksum")
        or item.get("size")
        or change_time
        or object_id
    )
    mime_type = str(item.get("mimeType") or "unknown")
    summary = f"Google Drive document {name} ({mime_type})"
    return store_provider_record(
        db,
        connection=connection,
        object_id=object_id,
        version=version,
        name=name,
        record_type="document_record",
        summary=summary,
        observed_at=observed,
        metadata={
            "provider_object_id": object_id,
            "mime_type": mime_type,
            "modified_time": item.get("modifiedTime"),
            "created_time": item.get("createdTime"),
            "size": item.get("size"),
            "web_view_link": item.get("webViewLink"),
            "parents": item.get("parents") or [],
            "change_time": change_time,
        },
    )


async def sync_google_drive(db: Session, *, connection: ConnectorConnection, access_value: str) -> dict[str, Any]:
    cursor = get_sync_cursor(db, connection=connection)
    cursor.last_attempt_at = datetime.utcnow()
    cursor.status = "syncing"
    db.commit()

    inserted = 0
    seen = 0
    async with httpx.AsyncClient(timeout=30) as client:
        if not cursor.cursor:
            token_data = await _request(client, _START_TOKEN_URL, access_value=access_value)
            next_cursor = str(token_data.get("startPageToken") or "")
            page_token: str | None = None
            while True:
                data = await _request(
                    client,
                    _FILES_URL,
                    access_value=access_value,
                    params={
                        "q": "trashed = false",
                        "spaces": "drive",
                        "pageSize": 1000,
                        "pageToken": page_token,
                        "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,createdTime,size,md5Checksum,webViewLink,parents,trashed)",
                    },
                )
                for item in data.get("files") or []:
                    if isinstance(item, dict):
                        seen += 1
                        inserted += int(_store_file(db, connection, item))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        else:
            page_token = cursor.cursor
            next_cursor = cursor.cursor
            while page_token:
                data = await _request(
                    client,
                    _CHANGES_URL,
                    access_value=access_value,
                    params={
                        "pageToken": page_token,
                        "pageSize": 1000,
                        "includeRemoved": "true",
                        "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,time,file(id,name,mimeType,modifiedTime,createdTime,size,md5Checksum,webViewLink,parents,trashed))",
                    },
                )
                for change in data.get("changes") or []:
                    if not isinstance(change, dict) or change.get("removed"):
                        continue
                    item = change.get("file")
                    if isinstance(item, dict):
                        seen += 1
                        inserted += int(_store_file(db, connection, item, str(change.get("time") or "") or None))
                page_token = data.get("nextPageToken")
                next_cursor = str(data.get("newStartPageToken") or page_token or next_cursor)

    cursor.cursor = next_cursor or cursor.cursor
    cursor.cursor_json = {"provider": "google_drive", "mode": "changes", "last_seen": seen}
    cursor.status = "ready"
    cursor.last_success_at = datetime.utcnow()
    cursor.updated_at = datetime.utcnow()
    # Deliberately do not commit here. The provider runner commits these staged
    # records and cursor changes only through its worker-owned fenced completion.
    return {
        "provider": "google_drive",
        "seen": seen,
        "inserted": inserted,
        "cursor_advanced": bool(cursor.cursor),
    }
