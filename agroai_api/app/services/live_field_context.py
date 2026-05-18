"""Live Field Context Assembler for connected sources."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.adapters.registry import AdapterRegistry
from app.services.intelligence_engine import CanonicalFieldContext


class LiveContextAssemblerError(Exception):
    pass


class LiveContextNotFoundError(LiveContextAssemblerError):
    pass


class LiveFieldContextAssembler:
    async def assemble_wiseconn_zone(self, zone_id: str) -> Dict[str, Any]:
        adapter = AdapterRegistry.get_wiseconn()
        warnings: List[str] = []
        live_inputs_used: List[str] = []

        field = CanonicalFieldContext(
            field_id=f"wiseconn-{zone_id}",
            source="wiseconn",
            source_entity_id=str(zone_id),
            controller_context={"provider": "WiseConn", "online": None},
            confidence_inputs=["live_context_assembler"],
        )

        try:
            farms = await adapter.list_farms()
            live_inputs_used.append("wiseconn.farms")
        except Exception:
            farms = []
            warnings.append("wiseconn_farms_unavailable")

        target_zone: Optional[Dict[str, Any]] = None
        target_farm: Optional[Dict[str, Any]] = None
        for farm in farms:
            farm_id = str(farm.get("id", ""))
            if not farm_id:
                continue
            try:
                zones = await adapter.list_zones(farm_id)
                live_inputs_used.append("wiseconn.zones")
            except Exception:
                warnings.append(f"wiseconn_zones_unavailable:{farm_id}")
                continue
            for zone in zones:
                if str(zone.get("id", "")) == str(zone_id):
                    target_zone = zone
                    target_farm = farm
                    break
            if target_zone:
                break

        if target_zone is None:
            raise LiveContextNotFoundError(f"WiseConn zone not found: {zone_id}")

        field.farm_id = str(target_farm.get("id")) if target_farm else None
        field.controller_context.online = bool(target_zone.get("enabled", True)) if isinstance(target_zone, dict) else None

        try:
            measures = await adapter.list_measures(str(zone_id))
            live_inputs_used.append("wiseconn.measures")
            if measures:
                first = measures[0]
                measure_id = first.get("id")
                if measure_id is not None:
                    last_data = await adapter.get_last_data(str(measure_id))
                    live_inputs_used.append("wiseconn.measure_last_data")
                    if isinstance(last_data, dict):
                        value = last_data.get("value")
                        if isinstance(value, (int, float)):
                            field.sensor_context.moisture_percent = float(value)
                            field.sensor_context.captured_at = datetime.now(timezone.utc)
        except Exception:
            warnings.append("wiseconn_telemetry_unavailable")

        try:
            irrigations = await adapter.list_irrigations(
                str(zone_id),
                start_time=datetime.now(timezone.utc) - timedelta(days=7),
                end_time=datetime.now(timezone.utc),
            )
            live_inputs_used.append("wiseconn.irrigations")
            if irrigations:
                field.recent_irrigation_context.events_last_7_days = len(irrigations)
        except Exception:
            warnings.append("wiseconn_irrigations_unavailable")

        return {
            "context": field,
            "warnings": warnings,
            "live_inputs_used": live_inputs_used,
            "manual_overrides_used": [],
            "context_origin": "live",
        }

    async def assemble_talgil_target(self, target_id: str) -> Dict[str, Any]:
        adapter = AdapterRegistry.get_talgil()
        warnings: List[str] = []
        live_inputs_used: List[str] = []

        field = CanonicalFieldContext(
            field_id=f"talgil-{target_id}",
            source="talgil",
            source_entity_id=str(target_id),
            controller_context={"provider": "Talgil", "online": None},
            confidence_inputs=["live_context_assembler"],
        )

        try:
            targets = await adapter.list_targets()
            live_inputs_used.append("talgil.targets")
        except Exception as exc:
            raise LiveContextAssemblerError(f"Talgil targets unavailable: {exc}") from exc

        target = next((row for row in targets if str(row.get("id", "")) == str(target_id)), None)
        if target is None:
            raise LiveContextNotFoundError(f"Talgil target not found: {target_id}")

        field.farm_id = str(target.get("id"))
        field.controller_context.online = bool(target.get("online"))

        try:
            zones = await adapter.list_zones(str(target_id))
            live_inputs_used.append("talgil.zones")
            if zones:
                first = zones[0]
                value = first.get("value")
                if isinstance(value, (int, float)):
                    field.sensor_context.moisture_percent = float(value)
        except Exception:
            warnings.append("talgil_sensors_unavailable")

        return {
            "context": field,
            "warnings": warnings,
            "live_inputs_used": live_inputs_used,
            "manual_overrides_used": [],
            "context_origin": "live",
        }

    async def assemble(self, source: str, entity_id: str) -> Dict[str, Any]:
        normalized_source = (source or "").lower()
        if normalized_source == "wiseconn":
            return await self.assemble_wiseconn_zone(entity_id)
        if normalized_source == "talgil":
            return await self.assemble_talgil_target(entity_id)
        raise LiveContextAssemblerError(f"Unsupported live source: {source}")
