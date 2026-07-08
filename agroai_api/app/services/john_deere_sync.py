from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models.operational_records import ConnectorConnection
from app.services.provider_oauth import ProviderOAuthError
from app.services.provider_record_store import parse_observed_at, store_provider_record


DEFAULT_API_BASE = "https://api.deere.com/platform"
MAX_ORGANIZATIONS = 25
MAX_PAGES_PER_ROUTE = 5
MAX_RECORDS_PER_ROUTE = 500

# Intentionally excludes Work Plans. Those routes remain a separate approval lane.
ORG_ROUTE_SPECS: tuple[tuple[str, str], ...] = (
    ("clients", "john_deere_client"),
    ("farms", "john_deere_farm"),
    ("fields", "john_deere_field"),
    ("boundaries", "john_deere_boundary"),
    ("fieldOperations", "john_deere_field_operation"),
    ("equipment", "john_deere_equipment"),
    ("guidanceLines", "john_deere_guidance_line"),
    ("users", "john_deere_user"),
    ("settings", "john_deere_organization_setting"),
)
GLOBAL_ROUTE_SPECS: tuple[tuple[str, str], ...] = (
    ("cropTypes", "john_deere_crop_type"),
    ("measurementTypes", "john_deere_measurement_type"),
    ("equipment/makes", "john_deere_equipment_make"),
    ("equipment/types", "john_deere_equipment_type"),
    ("equipment/models", "john_deere_equipment_model"),
)


def _api_base() -> str:
    return os.getenv("JOHN_DEERE_API_BASE_URL", DEFAULT_API_BASE).rstrip("/")


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("values", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    embedded = payload.get("_embedded")
    if isinstance(embedded, dict):
        for value in embedded.values():
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    # Some Deere collection responses use a domain-named array.
    for value in payload.values():
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
    return []


def _next_url(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    links = payload.get("_links") or payload.get("links")
    if not isinstance(links, dict):
        return None
    candidate = links.get("next")
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        return str(candidate.get("href") or candidate.get("uri") or "").strip() or None
    return None


def _record_id(record: dict[str, Any], *, fallback: str) -> str:
    for key in ("id", "uid", "organizationId", "clientId", "farmId", "fieldId", "boundaryId", "operationId", "equipmentId"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _record_name(record: dict[str, Any], *, record_type: str, object_id: str) -> str:
    for key in ("name", "displayName", "label", "title"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return f"{record_type.replace('_', ' ').title()} {object_id}"


def _observed_at(record: dict[str, Any]) -> datetime | None:
    for key in ("updatedAt", "modifiedAt", "createdAt", "startDate", "endDate", "timestamp", "date"):
        parsed = parse_observed_at(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _version(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _summary(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, default=str, ensure_ascii=False)[:4000]


def _safe_metadata(record: dict[str, Any], *, route: str, organization_id: str | None) -> dict[str, Any]:
    # Deere records are operational context, not credentials. Still redact common
    # secret-bearing keys before persistence.
    redacted: dict[str, Any] = {}
    for key, value in record.items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("secret", "token", "password", "authorization", "api_key", "apikey")):
            redacted[str(key)] = "[redacted]"
        else:
            redacted[str(key)] = value
    return {
        "provider": "john_deere",
        "route": route,
        "organization_id": organization_id,
        "payload": redacted,
        "read_only": True,
        "work_plans_included": False,
    }


async def _fetch_collection(
    client: httpx.AsyncClient,
    *,
    url: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    next_url: str | None = url
    pages = 0
    while next_url and pages < MAX_PAGES_PER_ROUTE and len(records) < MAX_RECORDS_PER_ROUTE:
        response = await client.get(next_url)
        if response.status_code in {401, 403}:
            if response.status_code == 401:
                raise ProviderOAuthError("John Deere authorization is no longer valid.", reconnect_required=True)
            warnings.append(f"route_forbidden:{url}")
            break
        if response.status_code == 404:
            warnings.append(f"route_unavailable:{url}")
            break
        if response.status_code == 429:
            raise ProviderOAuthError("John Deere rate limit reached.", retryable=True)
        if response.status_code >= 500:
            raise ProviderOAuthError(f"John Deere route failed with status {response.status_code}.", retryable=True)
        if response.status_code >= 400:
            warnings.append(f"route_failed:{response.status_code}:{url}")
            break
        try:
            payload = response.json()
        except ValueError:
            warnings.append(f"route_invalid_json:{url}")
            break
        records.extend(_items(payload))
        next_url = _next_url(payload)
        if next_url and next_url.startswith("/"):
            next_url = _api_base() + next_url
        pages += 1
    return records[:MAX_RECORDS_PER_ROUTE], warnings


def _persist_records(
    db: Session,
    *,
    connection: ConnectorConnection,
    records: list[dict[str, Any]],
    record_type: str,
    route: str,
    organization_id: str | None,
) -> int:
    created = 0
    for index, record in enumerate(records):
        object_id = _record_id(record, fallback=f"{route}:{organization_id or 'global'}:{index + 1}")
        if store_provider_record(
            db,
            connection=connection,
            object_id=f"{record_type}:{object_id}",
            version=_version(record),
            name=_record_name(record, record_type=record_type, object_id=object_id),
            record_type=record_type,
            summary=_summary(record),
            observed_at=_observed_at(record),
            metadata=_safe_metadata(record, route=route, organization_id=organization_id),
        ):
            created += 1
    return created


async def sync_john_deere(
    db: Session,
    *,
    connection: ConnectorConnection,
    access_value: str,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_value}",
        "Accept": "application/json",
        "User-Agent": "AGRO-AI-Operations-Center-Connector/1.0",
    }
    created = 0
    counts: dict[str, int] = {}
    warnings: list[str] = []
    base = _api_base()

    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
        organizations, org_warnings = await _fetch_collection(client, url=f"{base}/organizations")
        warnings.extend(org_warnings)
        organizations = organizations[:MAX_ORGANIZATIONS]
        counts["organizations"] = len(organizations)
        created += _persist_records(
            db,
            connection=connection,
            records=organizations,
            record_type="john_deere_organization",
            route="organizations",
            organization_id=None,
        )

        for org_index, organization in enumerate(organizations):
            organization_id = _record_id(organization, fallback=f"org-{org_index + 1}")
            for route, record_type in ORG_ROUTE_SPECS:
                path = f"organizations/{organization_id}/{route}"
                records, route_warnings = await _fetch_collection(client, url=f"{base}/{path}")
                warnings.extend(route_warnings)
                counts[path] = len(records)
                created += _persist_records(
                    db,
                    connection=connection,
                    records=records,
                    record_type=record_type,
                    route=path,
                    organization_id=organization_id,
                )

        for route, record_type in GLOBAL_ROUTE_SPECS:
            records, route_warnings = await _fetch_collection(client, url=f"{base}/{route}")
            warnings.extend(route_warnings)
            counts[route] = len(records)
            created += _persist_records(
                db,
                connection=connection,
                records=records,
                record_type=record_type,
                route=route,
                organization_id=None,
            )

    db.flush()
    return {
        "provider": "john_deere",
        "created_records": created,
        "counts": counts,
        "warnings": list(dict.fromkeys(warnings))[:100],
        "read_only": True,
        "work_plans_included": False,
        "synced_at": datetime.utcnow().isoformat() + "Z",
    }
