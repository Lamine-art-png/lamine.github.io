"""Tenant-scoped runtime for WiseConn, Talgil, and OpenET.

Reuses AGRO-AI's connector vault, sync cursors, idempotent provider record
store, durable jobs, and tenant/workspace ownership model.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.adapters.openet import OpenETAdapter, OpenETAuthError, OpenETRateLimitError
from app.adapters.talgil import TalgilAdapter, TalgilAuthError, TalgilRateLimitError
from app.adapters.wiseconn import WiseConnAdapter, WiseConnAuthError, WiseConnRateLimitError
from app.core.config import settings
from app.models.operational_records import ConnectorConnection, EvidenceRecord
from app.services.connector_vault import load_connector_credentials
from app.services.provider_record_store import parse_observed_at, store_provider_record
from app.services.provider_sync_state import get_sync_cursor

AG_PROVIDERS = {"wiseconn", "talgil", "openet"}
AUTH_ERRORS = (WiseConnAuthError, TalgilAuthError, OpenETAuthError)
RATE_LIMIT_ERRORS = (WiseConnRateLimitError, TalgilRateLimitError, OpenETRateLimitError)
_OPENET_ID_KEYS = {"openet_field_id", "openet_field_ids", "openetfieldid", "openetfieldids"}
_GEOMETRY_KEYS = {"geometry", "coordinates", "boundary", "polygon", "field_boundary"}


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("secret", "token", "api_key", "apikey", "password", "authorization")):
                output[str(key)] = "[redacted]"
            else:
                output[str(key)] = _redact_mapping(item)
        return output
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value


def _summary(payload: Any, limit: int = 2200) -> str:
    return json.dumps(_redact_mapping(payload), sort_keys=True, default=str, ensure_ascii=False)[:limit]


def _id(record: dict[str, Any], *keys: str, fallback: str) -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _observed(record: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "time", "date", "datetime", "observed_at", "updated_at", "source_timestamp"):
        parsed = parse_observed_at(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _config(connection: ConnectorConnection) -> dict[str, Any]:
    return dict(connection.config_json or {})


def _selected(connection: ConnectorConnection) -> list[str]:
    value = _config(connection).get("selected_resource_ids") or _config(connection).get("field_ids") or []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    return [str(item) for item in value if str(item).strip()]


def _numbers(value: Any) -> list[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [float(value)]
    if isinstance(value, list):
        result: list[float] = []
        for item in value:
            result.extend(_numbers(item))
        return result
    return []


def _geometry(connection: ConnectorConnection) -> list[float]:
    value = _config(connection).get("geometry") or []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [part.strip() for part in value.split(",") if part.strip()]
    return _numbers(value)


def _extract_openet_ids(value: Any) -> list[str]:
    output: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_").replace(" ", "_")
            if normalized in _OPENET_ID_KEYS:
                if isinstance(item, list):
                    output.extend(str(entry) for entry in item if str(entry).strip())
                elif item not in (None, ""):
                    output.append(str(item))
            else:
                output.extend(_extract_openet_ids(item))
    elif isinstance(value, list):
        for item in value:
            output.extend(_extract_openet_ids(item))
    return output


def _extract_geometry(value: Any) -> list[float]:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_").replace(" ", "_")
            if normalized in _GEOMETRY_KEYS:
                candidate = _numbers(item)
                if len(candidate) >= 6:
                    return candidate
        for item in value.values():
            candidate = _extract_geometry(item)
            if candidate:
                return candidate
    elif isinstance(value, list):
        for item in value:
            candidate = _extract_geometry(item)
            if candidate:
                return candidate
    return []


def _workspace_context(db: Session, connection: ConnectorConnection) -> tuple[list[str], list[list[float]]]:
    query = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == connection.tenant_id)
    if connection.workspace_id:
        query = query.filter(EvidenceRecord.workspace_id == connection.workspace_id)
    ids: list[str] = []
    geometries: list[list[float]] = []
    for row in query.order_by(EvidenceRecord.created_at.desc()).limit(500).all():
        for payload in (row.value_json or {}, row.metadata_json or {}):
            ids.extend(_extract_openet_ids(payload))
            geometry = _extract_geometry(payload)
            if geometry:
                geometries.append(geometry)
    return list(dict.fromkeys(ids))[:100], geometries[:50]


def build_ag_adapter(provider: str, credentials: dict[str, Any]):
    credential = str(credentials.get("api_key") or credentials.get("token") or "").strip()
    if provider == "wiseconn":
        return WiseConnAdapter(
            api_url=settings.WISECONN_API_URL,
            api_key=credential,
            timeout=int(getattr(settings, "WISECONN_TIMEOUT_SECONDS", 30)),
            max_retries=int(getattr(settings, "WISECONN_MAX_RETRIES", 3)),
        )
    if provider == "talgil":
        return TalgilAdapter(
            api_url=settings.TALGIL_API_URL,
            api_key=credential,
            timeout=int(getattr(settings, "TALGIL_TIMEOUT_SECONDS", 30)),
            max_retries=int(getattr(settings, "TALGIL_MAX_RETRIES", 3)),
        )
    if provider == "openet":
        configured_url = str(getattr(settings, "OPENET_API_URL", "") or "").strip()
        api_url = configured_url if configured_url and "mock-openet" not in configured_url else "https://openet-api.org"
        return OpenETAdapter(api_url=api_url, api_key=credential, timeout=int(getattr(settings, "OPENET_TIMEOUT_SECONDS", 45)))
    raise ValueError("unsupported agricultural provider")


def load_ag_adapter(db: Session, *, connection: ConnectorConnection):
    credentials = load_connector_credentials(db, tenant_id=connection.tenant_id, connection_id=connection.id)
    return build_ag_adapter(connection.provider, credentials)


def _resource_preview(records: Iterable[dict[str, Any]], resource_type: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        resource_id = _id(record, "id", "ID", "field_id", "fieldId", "UID", fallback=str(index + 1))
        name = record.get("name") or record.get("Name") or record.get("label") or f"{resource_type.title()} {resource_id}"
        output.append({"id": resource_id, "name": str(name), "type": resource_type, "metadata": _redact_mapping(record)})
    return output[:500]


async def probe_ag_candidate(provider: str, credential: str) -> dict[str, Any]:
    adapter = build_ag_adapter(provider, {"api_key": credential})
    try:
        if provider == "wiseconn":
            if not await adapter.check_auth():
                raise WiseConnAuthError("WiseConn authorization failed")
            farms = await adapter.list_farms()
            return {"identity": {"provider": provider, "resource_count": len(farms)}, "resources": _resource_preview(farms, "farm")}
        if provider == "talgil":
            if not await adapter.check_auth():
                raise TalgilAuthError("Talgil authorization failed")
            targets = await adapter.list_targets()
            return {"identity": {"provider": provider, "resource_count": len(targets)}, "resources": _resource_preview(targets, "controller")}
        if provider == "openet":
            if not await adapter.check_auth():
                raise OpenETAuthError("OpenET authorization failed")
            return {"identity": {"provider": provider, "account": _redact_mapping(await adapter.account_status())}, "resources": []}
        raise ValueError("unsupported agricultural provider")
    finally:
        await adapter.close()


async def _resolve_openet_ids(db: Session, connection: ConnectorConnection, adapter: OpenETAdapter) -> tuple[list[str], list[float]]:
    config = _config(connection)
    ids = _selected(connection)
    geometry = _geometry(connection)
    asset_id = str(config.get("openet_asset_id") or "").strip()
    if not ids and asset_id:
        ids = await adapter.field_ids_for_asset(asset_id)
    if not ids and geometry:
        ids = await adapter.field_ids_for_geometry(geometry)
    if not ids and config.get("scope_mode") == "agroai_fields":
        context_ids, geometries = _workspace_context(db, connection)
        ids.extend(context_ids)
        for candidate in geometries:
            if len(ids) >= 100:
                break
            ids.extend(await adapter.field_ids_for_geometry(candidate))
    return list(dict.fromkeys(str(item) for item in ids if str(item).strip()))[:100], geometry


async def discover_ag_resources(db: Session, *, connection: ConnectorConnection) -> dict[str, Any]:
    adapter = load_ag_adapter(db, connection=connection)
    try:
        if connection.provider == "wiseconn":
            farms = await adapter.list_farms()
            return {"provider": "wiseconn", "resources": _resource_preview(farms, "farm"), "count": len(farms)}
        if connection.provider == "talgil":
            targets = await adapter.list_targets()
            return {"provider": "talgil", "resources": _resource_preview(targets, "controller"), "count": len(targets)}
        ids, _ = await _resolve_openet_ids(db, connection, adapter)
        properties = await adapter.field_properties(ids) if ids else []
        resources = _resource_preview(properties, "field") if properties else [
            {"id": item, "name": f"OpenET field {item}", "type": "field"} for item in ids
        ]
        return {"provider": "openet", "resources": resources, "count": len(resources), "field_ids": ids}
    finally:
        await adapter.close()


def _store(db: Session, connection: ConnectorConnection, *, object_id: str, record_type: str, name: str, payload: dict[str, Any]) -> bool:
    return store_provider_record(
        db,
        connection=connection,
        object_id=object_id,
        version=_hash(payload),
        name=name,
        record_type=record_type,
        summary=_summary(payload),
        observed_at=_observed(payload),
        metadata={"provider": connection.provider, "payload": _redact_mapping(payload)},
    )


async def _sync_wiseconn(db: Session, connection: ConnectorConnection, adapter: WiseConnAdapter, start: datetime, end: datetime):
    selected = set(_selected(connection))
    farms = [farm for farm in await adapter.list_farms() if _id(farm, "id", "ID", fallback="") in selected]
    created = 0
    counts = {"farms": 0, "zones": 0, "measures": 0, "telemetry": 0, "irrigations": 0}
    for farm_index, farm in enumerate(farms[:50]):
        farm_id = _id(farm, "id", "ID", fallback=str(farm_index + 1))
        counts["farms"] += 1
        created += int(_store(db, connection, object_id=f"farm:{farm_id}", record_type="wiseconn_farm", name=str(farm.get("name") or farm.get("Name") or f"WiseConn farm {farm_id}"), payload=farm))
        for zone_index, zone in enumerate((await adapter.list_zones(farm_id))[:250]):
            zone_id = _id(zone, "id", "ID", fallback=f"{farm_id}:{zone_index + 1}")
            counts["zones"] += 1
            created += int(_store(db, connection, object_id=f"zone:{zone_id}", record_type="wiseconn_zone", name=str(zone.get("name") or zone.get("Name") or f"WiseConn zone {zone_id}"), payload={**zone, "farm_id": farm_id}))
            for measure_index, measure in enumerate((await adapter.list_measures(zone_id))[:250]):
                measure_id = _id(measure, "id", "ID", fallback=f"{zone_id}:{measure_index + 1}")
                counts["measures"] += 1
                created += int(_store(db, connection, object_id=f"measure:{measure_id}", record_type="wiseconn_measure", name=str(measure.get("name") or measure.get("Name") or f"WiseConn measure {measure_id}"), payload={**measure, "zone_id": zone_id, "farm_id": farm_id}))
                for point_index, point in enumerate((await adapter.get_measure_data(measure_id, start, end))[-1000:]):
                    key = _id(point, "id", "ID", "timestamp", "time", fallback=f"{point_index}:{_hash(point)[:16]}")
                    counts["telemetry"] += 1
                    created += int(_store(db, connection, object_id=f"measure:{measure_id}:point:{key}", record_type="wiseconn_telemetry", name=f"WiseConn telemetry {measure_id}", payload={**point, "measure_id": measure_id, "zone_id": zone_id, "farm_id": farm_id}))
            for index, irrigation in enumerate((await adapter.list_irrigations(zone_id, start, end))[-1000:]):
                key = _id(irrigation, "id", "irrigationId", "ID", fallback=f"{index}:{_hash(irrigation)[:16]}")
                counts["irrigations"] += 1
                created += int(_store(db, connection, object_id=f"irrigation:{key}", record_type="wiseconn_irrigation", name=f"WiseConn irrigation {key}", payload={**irrigation, "zone_id": zone_id, "farm_id": farm_id}))
    return created, counts


async def _sync_talgil(db: Session, connection: ConnectorConnection, adapter: TalgilAdapter):
    selected = set(_selected(connection))
    targets = [target for target in await adapter.list_targets() if str(target.get("id")) in selected]
    created = 0
    counts = {"controllers": 0, "snapshots": 0, "sensors": 0}
    for target in targets[:50]:
        target_id = str(target.get("id"))
        counts["controllers"] += 1
        created += int(_store(db, connection, object_id=f"controller:{target_id}", record_type="talgil_controller", name=str(target.get("name") or f"Talgil controller {target_id}"), payload=target))
        image = await adapter.get_target_image(target_id)
        counts["snapshots"] += 1
        created += int(_store(db, connection, object_id=f"controller:{target_id}:snapshot", record_type="talgil_controller_snapshot", name=f"Talgil controller snapshot {target_id}", payload=image))
        sensors = image.get("Sensors") if isinstance(image, dict) else []
        for index, sensor in enumerate(sensors if isinstance(sensors, list) else []):
            if not isinstance(sensor, dict):
                continue
            sensor_id = _id(sensor, "UID", "id", "ID", fallback=f"{target_id}:{index + 1}")
            counts["sensors"] += 1
            created += int(_store(db, connection, object_id=f"controller:{target_id}:sensor:{sensor_id}", record_type="talgil_sensor_snapshot", name=str(sensor.get("Name") or f"Talgil sensor {sensor_id}"), payload={**sensor, "controller_id": target_id}))
    return created, counts


async def _sync_openet(db: Session, connection: ConnectorConnection, adapter: OpenETAdapter, start: datetime, end: datetime):
    ids, geometry = await _resolve_openet_ids(db, connection, adapter)
    if not ids and not geometry:
        raise RuntimeError("OpenET field scope could not be resolved")
    created = 0
    counts = {"fields": 0, "timeseries": 0}
    if ids:
        config = _config(connection)
        config.update({"field_ids": ids, "selected_resource_ids": ids})
        connection.config_json = config
        for index, record in enumerate(await adapter.field_properties(ids)):
            field_id = _id(record, "field_id", "fieldId", "id", fallback=ids[index] if index < len(ids) else str(index + 1))
            counts["fields"] += 1
            created += int(_store(db, connection, object_id=f"field:{field_id}", record_type="openet_field", name=f"OpenET field {field_id}", payload=record))
        series = await adapter.timeseries_by_field_ids(field_ids=ids, start_date=start.date().isoformat(), end_date=end.date().isoformat())
    else:
        series = await adapter.timeseries_for_polygon(geometry=geometry, start_date=start.date().isoformat(), end_date=end.date().isoformat())
    for index, record in enumerate(series):
        hint = _id(record, "field_id", "fieldId", "id", "date", "time", "timestamp", fallback=f"{index}:{_hash(record)[:16]}")
        payload = {**record, "truth_label": "estimated", "source_provider": "OpenET", "source_model": record.get("model") or "Ensemble"}
        counts["timeseries"] += 1
        created += int(_store(db, connection, object_id=f"timeseries:{hint}:{_hash(record)[:16]}", record_type="openet_estimated_et", name=f"OpenET ET estimate {hint}", payload=payload))
    return created, counts


async def sync_ag_provider(db: Session, *, connection: ConnectorConnection) -> dict[str, Any]:
    cursor = get_sync_cursor(db, connection=connection)
    state = dict(cursor.cursor_json or {})
    now = datetime.utcnow()
    previous = parse_observed_at(state.get("last_synced_at"))
    start = previous or now - timedelta(days=365 if connection.provider == "openet" else 14)
    adapter = load_ag_adapter(db, connection=connection)
    try:
        if connection.provider == "wiseconn":
            created, counts = await _sync_wiseconn(db, connection, adapter, start, now)
        elif connection.provider == "talgil":
            created, counts = await _sync_talgil(db, connection, adapter)
        elif connection.provider == "openet":
            created, counts = await _sync_openet(db, connection, adapter, start, now)
        else:
            raise ValueError("unsupported agricultural provider")
        cursor.cursor_json = {**state, "last_synced_at": now.isoformat() + "Z", "created_records": created, "counts": counts}
        cursor.status = "synced"
        cursor.updated_at = now
        db.flush()
        return {"provider": connection.provider, "created_records": created, "counts": counts, "cursor": cursor.cursor_json}
    finally:
        await adapter.close()
