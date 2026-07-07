"""Unified tenant-scoped runtime for WiseConn, Talgil, and OpenET.

Reuses the production connector substrate:
- ConnectorConnection ownership and workspace scope
- encrypted ConnectorCredential vault
- ConnectorSyncCursor incremental checkpoints
- idempotent DataSource/EvidenceRecord persistence
- durable provider-sync jobs and workers
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


def _stable_version(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_summary(payload: Any, limit: int = 2200) -> str:
    try:
        text = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    except TypeError:
        text = str(payload)
    return text[:limit]


def _id_from(record: dict[str, Any], *keys: str, fallback: str) -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _observed_at(record: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "time", "date", "datetime", "observed_at", "updated_at", "source_timestamp"):
        parsed = parse_observed_at(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _config(connection: ConnectorConnection) -> dict[str, Any]:
    return dict(connection.config_json or {})


def _selected_ids(connection: ConnectorConnection) -> list[str]:
    config = _config(connection)
    values = config.get("selected_resource_ids") or config.get("field_ids") or []
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",") if item.strip()]
    return [str(value) for value in values if str(value).strip()]


def _flatten_numbers(value: Any) -> list[float]:
    result: list[float] = []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [float(value)]
    if isinstance(value, list):
        for item in value:
            result.extend(_flatten_numbers(item))
    return result


def _geometry(connection: ConnectorConnection) -> list[float]:
    value = _config(connection).get("geometry") or []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [item.strip() for item in value.split(",") if item.strip()]
    return _flatten_numbers(value)


def _extract_openet_ids(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_").replace(" ", "_")
            if normalized in _OPENET_ID_KEYS:
                if isinstance(item, list):
                    result.extend(str(entry) for entry in item if str(entry).strip())
                elif item not in (None, ""):
                    result.append(str(item))
            else:
                result.extend(_extract_openet_ids(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_extract_openet_ids(item))
    return result


def _extract_geometry(value: Any) -> list[float]:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_").replace(" ", "_")
            if normalized in _GEOMETRY_KEYS:
                numbers = _flatten_numbers(item)
                if len(numbers) >= 6:
                    return numbers
        for item in value.values():
            found = _extract_geometry(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _extract_geometry(item)
            if found:
                return found
    return []


def _workspace_field_context(db: Session, connection: ConnectorConnection) -> tuple[list[str], list[list[float]]]:
    query = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == connection.tenant_id)
    if connection.workspace_id:
        query = query.filter(EvidenceRecord.workspace_id == connection.workspace_id)
    rows = query.order_by(EvidenceRecord.created_at.desc()).limit(500).all()
    ids: list[str] = []
    geometries: list[list[float]] = []
    for row in rows:
        for payload in (row.value_json or {}, row.metadata_json or {}):
            ids.extend(_extract_openet_ids(payload))
            geometry = _extract_geometry(payload)
            if geometry:
                geometries.append(geometry)
    return list(dict.fromkeys(value for value in ids if value))[:100], geometries[:50]


def build_ag_adapter(provider: str, credentials: dict[str, Any]):
    api_key = str(credentials.get("api_key") or credentials.get("token") or "").strip()
    # Provider destinations are server-owned. Legacy vault payloads cannot
    # redirect a secret-bearing request by supplying an api_url override.
    if provider == "wiseconn":
        return WiseConnAdapter(
            api_url=settings.WISECONN_API_URL,
            api_key=api_key,
            timeout=int(getattr(settings, "WISECONN_TIMEOUT_SECONDS", 30)),
            max_retries=int(getattr(settings, "WISECONN_MAX_RETRIES", 3)),
        )
    if provider == "talgil":
        return TalgilAdapter(
            api_url=settings.TALGIL_API_URL,
            api_key=api_key,
            timeout=int(getattr(settings, "TALGIL_TIMEOUT_SECONDS", 30)),
            max_retries=int(getattr(settings, "TALGIL_MAX_RETRIES", 3)),
        )
    if provider == "openet":
        return OpenETAdapter(
            api_url=settings.OPENET_API_URL,
            api_key=api_key,
            timeout=int(getattr(settings, "OPENET_TIMEOUT_SECONDS", 45)),
        )
    raise ValueError("unsupported agricultural provider")


def load_ag_adapter(db: Session, *, connection: ConnectorConnection):
    if connection.provider not in AG_PROVIDERS:
        raise ValueError("unsupported agricultural provider")
    credentials = load_connector_credentials(db, tenant_id=connection.tenant_id, connection_id=connection.id)
    return build_ag_adapter(connection.provider, credentials)


async def probe_ag_connection(db: Session, *, connection: ConnectorConnection) -> dict[str, Any]:
    adapter = load_ag_adapter(db, connection=connection)
    try:
        if connection.provider == "wiseconn":
            if not await adapter.check_auth():
                raise WiseConnAuthError("WiseConn authorization failed")
            farms = await adapter.list_farms()
            return {"authorized": True, "identity": {"provider": "wiseconn", "resource_count": len(farms)}, "resources": _resource_preview(farms, "farm")}
        if connection.provider == "talgil":
            if not await adapter.check_auth():
                raise TalgilAuthError("Talgil authorization failed")
            targets = await adapter.list_targets()
            return {"authorized": True, "identity": {"provider": "talgil", "resource_count": len(targets)}, "resources": _resource_preview(targets, "controller")}
        if not await adapter.check_auth():
            raise OpenETAuthError("OpenET authorization failed")
        account = await adapter.account_status()
        return {"authorized": True, "identity": {"provider": "openet", "account": _redact_mapping(account)}, "resources": []}
    finally:
        await adapter.close()


async def _resolve_openet_ids(db: Session, connection: ConnectorConnection, adapter: OpenETAdapter) -> tuple[list[str], list[float]]:
    config = _config(connection)
    ids = _selected_ids(connection)
    geometry = _geometry(connection)
    asset_id = str(config.get("openet_asset_id") or "").strip()
    scope_mode = str(config.get("scope_mode") or "")

    if not ids and asset_id:
        ids = await adapter.field_ids_for_asset(asset_id)
    if not ids and geometry:
        ids = await adapter.field_ids_for_geometry(geometry)
    if not ids and scope_mode == "agroai_fields":
        context_ids, geometries = _workspace_field_context(db, connection)
        ids.extend(context_ids)
        for candidate in geometries:
            if len(ids) >= 100:
                break
            ids.extend(await adapter.field_ids_for_geometry(candidate))
    return list(dict.fromkeys(str(value) for value in ids if str(value).strip()))[:100], geometry


async def discover_ag_resources(db: Session, *, connection: ConnectorConnection) -> dict[str, Any]:
    adapter = load_ag_adapter(db, connection=connection)
    try:
        if connection.provider == "wiseconn":
            farms = await adapter.list_farms()
            return {"provider": "wiseconn", "resources": _resource_preview(farms, "farm"), "count": len(farms)}
        if connection.provider == "talgil":
            targets = await adapter.list_targets()
            return {"provider": "talgil", "resources": _resource_preview(targets, "controller"), "count": len(targets)}

        ids, _geometry_value = await _resolve_openet_ids(db, connection, adapter)
        properties = await adapter.field_properties(ids) if ids else []
        return {
            "provider": "openet",
            "resources": _resource_preview(properties, "field") if properties else [{"id": value, "name": f"OpenET field {value}", "type": "field"} for value in ids],
            "count": len(properties) if properties else len(ids),
            "field_ids": ids,
        }
    finally:
        await adapter.close()


def _resource_preview(records: Iterable[dict[str, Any]], resource_type: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        resource_id = _id_from(record, "id", "ID", "field_id", "fieldId", "UID", fallback=str(index + 1))
        name = record.get("name") or record.get("Name") or record.get("label") or f"{resource_type.title()} {resource_id}"
        result.append({"id": resource_id, "name": str(name), "type": resource_type, "metadata": _redact_mapping(record)})
    return result[:500]


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("secret", "token", "api_key", "apikey", "password", "authorization")):
                result[str(key)] = "[redacted]"
            else:
                result[str(key)] = _redact_mapping(item)
        return result
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value


def _store(
    db: Session,
    *,
    connection: ConnectorConnection,
    object_id: str,
    record_type: str,
    name: str,
    payload: dict[str, Any],
    observed_at: datetime | None = None,
) -> bool:
    redacted = _redact_mapping(payload)
    return store_provider_record(
        db,
        connection=connection,
        object_id=object_id,
        version=_stable_version(payload),
        name=name,
        record_type=record_type,
        summary=_safe_summary(redacted),
        observed_at=observed_at or _observed_at(payload),
        metadata={"provider": connection.provider, "payload": redacted},
    )


async def sync_ag_provider(db: Session, *, connection: ConnectorConnection) -> dict[str, Any]:
    cursor = get_sync_cursor(db, connection=connection)
    cursor_state = dict(cursor.cursor_json or {})
    now = datetime.utcnow()
    previous = parse_observed_at(cursor_state.get("last_synced_at"))
    start = previous or now - timedelta(days=14 if connection.provider != "openet" else 365)
    adapter = load_ag_adapter(db, connection=connection)
    try:
        if connection.provider == "wiseconn":
            created, counts = await _sync_wiseconn(db, connection=connection, adapter=adapter, start=start, end=now)
        elif connection.provider == "talgil":
            created, counts = await _sync_talgil(db, connection=connection, adapter=adapter)
        else:
            created, counts = await _sync_openet(db, connection=connection, adapter=adapter, start=start, end=now)

        cursor.cursor_json = {**cursor_state, "last_synced_at": now.isoformat() + "Z", "created_records": created, "counts": counts}
        cursor.status = "synced"
        cursor.updated_at = now
        db.flush()
        return {"provider": connection.provider, "created_records": created, "counts": counts, "cursor": cursor.cursor_json}
    finally:
        await adapter.close()


async def _sync_wiseconn(db: Session, *, connection: ConnectorConnection, adapter: WiseConnAdapter, start: datetime, end: datetime) -> tuple[int, dict[str, int]]:
    farms = await adapter.list_farms()
    selected = set(_selected_ids(connection))
    if selected:
        farms = [farm for farm in farms if _id_from(farm, "id", "ID", fallback="") in selected]
    created = 0
    counts = {"farms": 0, "zones": 0, "measures": 0, "telemetry": 0, "irrigations": 0}
    for farm_index, farm in enumerate(farms[:50]):
        farm_id = _id_from(farm, "id", "ID", fallback=str(farm_index + 1))
        counts["farms"] += 1
        created += int(_store(db, connection=connection, object_id=f"farm:{farm_id}", record_type="wiseconn_farm", name=str(farm.get("name") or farm.get("Name") or f"WiseConn farm {farm_id}"), payload=farm))
        zones = await adapter.list_zones(farm_id)
        for zone_index, zone in enumerate(zones[:250]):
            zone_id = _id_from(zone, "id", "ID", fallback=f"{farm_id}:{zone_index + 1}")
            counts["zones"] += 1
            created += int(_store(db, connection=connection, object_id=f"zone:{zone_id}", record_type="wiseconn_zone", name=str(zone.get("name") or zone.get("Name") or f"WiseConn zone {zone_id}"), payload={**zone, "farm_id": farm_id}))
            measures = await adapter.list_measures(zone_id)
            for measure_index, measure in enumerate(measures[:250]):
                measure_id = _id_from(measure, "id", "ID", fallback=f"{zone_id}:{measure_index + 1}")
                counts["measures"] += 1
                created += int(_store(db, connection=connection, object_id=f"measure:{measure_id}", record_type="wiseconn_measure", name=str(measure.get("name") or measure.get("Name") or f"WiseConn measure {measure_id}"), payload={**measure, "zone_id": zone_id, "farm_id": farm_id}))
                points = await adapter.get_measure_data(measure_id, start, end)
                for point_index, point in enumerate(points[-1000:]):
                    point_key = _id_from(point, "id", "ID", "timestamp", "time", fallback=f"{point_index}:{_stable_version(point)[:16]}")
                    counts["telemetry"] += 1
                    created += int(_store(db, connection=connection, object_id=f"measure:{measure_id}:point:{point_key}", record_type="wiseconn_telemetry", name=f"WiseConn telemetry {measure_id}", payload={**point, "measure_id": measure_id, "zone_id": zone_id, "farm_id": farm_id}))
            irrigations = await adapter.list_irrigations(zone_id, start, end)
            for irrigation_index, irrigation in enumerate(irrigations[-1000:]):
                irrigation_id = _id_from(irrigation, "id", "irrigationId", "ID", fallback=f"{irrigation_index}:{_stable_version(irrigation)[:16]}")
                counts["irrigations"] += 1
                created += int(_store(db, connection=connection, object_id=f"irrigation:{irrigation_id}", record_type="wiseconn_irrigation", name=f"WiseConn irrigation {irrigation_id}", payload={**irrigation, "zone_id": zone_id, "farm_id": farm_id}))
    return created, counts


async def _sync_talgil(db: Session, *, connection: ConnectorConnection, adapter: TalgilAdapter) -> tuple[int, dict[str, int]]:
    targets = await adapter.list_targets()
    selected = set(_selected_ids(connection))
    if selected:
        targets = [target for target in targets if str(target.get("id")) in selected]
    created = 0
    counts = {"controllers": 0, "snapshots": 0, "sensors": 0}
    for target in targets[:200]:
        target_id = str(target.get("id"))
        counts["controllers"] += 1
        created += int(_store(db, connection=connection, object_id=f"controller:{target_id}", record_type="talgil_controller", name=str(target.get("name") or f"Talgil controller {target_id}"), payload=target))
        image = await adapter.get_target_image(target_id)
        counts["snapshots"] += 1
        created += int(_store(db, connection=connection, object_id=f"controller:{target_id}:snapshot", record_type="talgil_controller_snapshot", name=f"Talgil controller snapshot {target_id}", payload=image))
        sensors = image.get("Sensors") if isinstance(image, dict) else []
        for index, sensor in enumerate(sensors if isinstance(sensors, list) else []):
            if not isinstance(sensor, dict):
                continue
            sensor_id = _id_from(sensor, "UID", "id", "ID", fallback=f"{target_id}:{index + 1}")
            counts["sensors"] += 1
            created += int(_store(db, connection=connection, object_id=f"controller:{target_id}:sensor:{sensor_id}", record_type="talgil_sensor_snapshot", name=str(sensor.get("Name") or f"Talgil sensor {sensor_id}"), payload={**sensor, "controller_id": target_id}))
    return created, counts


async def _sync_openet(db: Session, *, connection: ConnectorConnection, adapter: OpenETAdapter, start: datetime, end: datetime) -> tuple[int, dict[str, int]]:
    ids, geometry = await _resolve_openet_ids(db, connection, adapter)
    if not ids and not geometry:
        raise RuntimeError("OpenET field scope could not be resolved from the selected source")
    if ids:
        config = _config(connection)
        config["field_ids"] = ids[:100]
        config["selected_resource_ids"] = ids[:100]
        connection.config_json = config

    created = 0
    counts = {"fields": 0, "timeseries": 0}
    if ids:
        properties = await adapter.field_properties(ids)
        for index, record in enumerate(properties):
            field_id = _id_from(record, "field_id", "fieldId", "id", fallback=ids[index] if index < len(ids) else str(index + 1))
            counts["fields"] += 1
            created += int(_store(db, connection=connection, object_id=f"field:{field_id}", record_type="openet_field", name=f"OpenET field {field_id}", payload=record))
        series = await adapter.timeseries_by_field_ids(field_ids=ids, start_date=start.date().isoformat(), end_date=end.date().isoformat(), interval="monthly")
    else:
        series = await adapter.timeseries_for_polygon(geometry=geometry, start_date=start.date().isoformat(), end_date=end.date().isoformat(), interval="monthly")

    for index, record in enumerate(series):
        object_hint = _id_from(record, "field_id", "fieldId", "id", "date", "time", "timestamp", fallback=f"{index}:{_stable_version(record)[:16]}")
        counts["timeseries"] += 1
        payload = {**record, "truth_label": "estimated", "source_provider": "OpenET", "source_model": record.get("model") or "Ensemble"}
        created += int(_store(db, connection=connection, object_id=f"timeseries:{object_hint}:{_stable_version(record)[:16]}", record_type="openet_estimated_et", name=f"OpenET ET estimate {object_hint}", payload=payload))
    return created, counts
