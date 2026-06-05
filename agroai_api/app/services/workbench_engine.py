from __future__ import annotations

import csv
import io
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

from app.models.workbench import (
    NormalizedSignal,
    ReconciliationResult,
    ReportArtifact,
    WorkbenchAnalysisResult,
    WorkbenchDataArtifact,
    WorkbenchSession,
)
from app.services.workbench_sample_data import get_sample_files, get_incomplete_evidence_files
from app.services.live_field_context import (
    LiveContextAssemblerError,
    LiveFieldContextAssembler,
)
from app.services.irrigation_decision_orchestrator import IrrigationDecisionOrchestrator

try:
    import openpyxl
except Exception:
    openpyxl = None


SESSIONS: Dict[str, Dict[str, Any]] = {}
ALLOWED_EXT = {"csv", "json", "txt", "xlsx"}
ALIAS = {
    "actual_m3": "actual_m3",
    "actual_volume": "actual_m3",
    "applied_duration": "applied_duration_min",
    "applied_duration_min": "applied_duration_min",
    "block": "block",
    "date": "timestamp",
    "deficit": "deficit_percent",
    "depth": "depth_mm",
    "depth_mm": "depth_mm",
    "duration": "duration_min",
    "et0": "eto",
    "eto_mm": "eto",
    "evapotranspiration": "eto",
    "field": "block",
    "flow": "flow_m3h",
    "flow_m3h": "flow_m3h",
    "inches": "depth_in",
    "mm": "depth_mm",
    "moisture": "moisture_percent",
    "moisture_percent": "moisture_percent",
    "notes": "notes",
    "observation": "notes",
    "planned_duration": "scheduled_duration_min",
    "planned_m3": "planned_m3",
    "precipitation": "rain",
    "pressure": "pressure_kpa",
    "pressure_kpa": "pressure_kpa",
    "rain": "rain",
    "rain_forecast_mm": "rain",
    "rainfall": "rain",
    "runtime": "duration_min",
    "scheduled_duration": "scheduled_duration_min",
    "scheduled_duration_min": "scheduled_duration_min",
    "soil_moisture": "moisture_percent",
    "time": "timestamp",
    "variance": "variance_percent",
    "variance_percent": "variance_percent",
    "zone": "zone",
}


def create_session(mode: str = "uploaded", workspace_name: str = "Water Command Center") -> WorkbenchSession:
    now = datetime.utcnow()
    sid = str(uuid.uuid4())
    sess = WorkbenchSession(
        session_id=sid,
        workspace_name=workspace_name,
        mode=mode,
        created_at=now,
        updated_at=now,
        status="ready",
    )
    SESSIONS[sid] = {"session": sess, "artifacts": [], "analysis": None, "audit": [], "evidence_actions": []}
    return sess


def detect_source_kind(filename: str, columns: List[str]) -> str:
    name = filename.lower()
    cols = " ".join(c.lower() for c in columns)
    if "controller_events" in name or "event_type" in cols:
        return "controller_events"
    if "flow_meter" in name or "meter_id" in cols or "planned_m3" in cols:
        return "flow_meter"
    if "crop_profile" in name or "root_zone_depth_cm" in cols or "growth_stage" in cols:
        return "crop_profile"
    if "water_cost" in name or "cost_per_acre_ft" in cols:
        return "water_costs"
    if "satellite" in name or "ndvi" in cols or "vegetation_stress_index" in cols:
        return "satellite_observation"
    if "weather" in name or "eto" in cols or "rain" in cols:
        return "weather"
    if "soil" in name or "moisture" in cols or "deficit_percent" in cols:
        return "soil_moisture"
    if "note" in name or "observation" in cols or "notes" in cols:
        return "field_notes"
    if "irrig" in name or "duration" in cols or "runtime" in cols:
        return "irrigation_records"
    if "controller" in name or "flow" in cols or "pressure" in cols:
        return "controller_logs"
    return "unknown"


def parse_uploaded_file(filename: str, content: bytes) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    ext = filename.rsplit(".", 1)[-1].lower()
    warnings: List[str] = []
    if ext not in ALLOWED_EXT:
        raise ValueError("Unsupported file type")
    if ext == "csv":
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8", errors="ignore"))))
    elif ext == "json":
        payload = json.loads(content.decode("utf-8", errors="ignore"))
        rows = payload if isinstance(payload, list) else [payload]
    elif ext == "txt":
        lines = [line.strip() for line in content.decode("utf-8", errors="ignore").splitlines() if line.strip()]
        rows = [{"notes": line} for line in lines]
    else:
        if openpyxl is None:
            raise ValueError("Excel parsing requires openpyxl dependency")
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        sheet = wb.active
        values = list(sheet.values)
        if not values:
            return [], [], ["Workbook has no rows"]
        headers = [str(header) for header in values[0]]
        rows = [dict(zip(headers, row)) for row in values[1:]]
    cols = list(rows[0].keys()) if rows else []
    return rows, cols, warnings


def infer_schema(columns: List[str]) -> Dict[str, str]:
    out = {}
    for column in columns:
        key = column.strip().lower().replace(" ", "_")
        out[column] = ALIAS.get(key, key)
    return out


def normalize_units(row: Dict[str, Any], schema: Dict[str, str]) -> Dict[str, Any]:
    normalized = {}
    for key, value in row.items():
        canonical = schema.get(key, key)
        if canonical == "depth_in":
            try:
                normalized["depth_mm"] = float(value) * 25.4
            except Exception:
                normalized["depth_mm"] = value
        elif canonical == "duration_min" and isinstance(value, str) and "hour" in value.lower():
            try:
                normalized[canonical] = float(value.split()[0]) * 60
            except Exception:
                normalized[canonical] = value
        else:
            normalized[canonical] = value
    if "timestamp" in normalized:
        try:
            normalized["timestamp"] = datetime.fromisoformat(str(normalized["timestamp"]).replace("Z", "+00:00")).isoformat()
        except Exception:
            pass
    return normalized


def _to_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _avg(values: Iterable[Any]) -> float | None:
    numbers = [value for value in (_to_float(item) for item in values) if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _max_abs(values: Iterable[Any]) -> float | None:
    numbers = [value for value in (_to_float(item) for item in values) if value is not None]
    if not numbers:
        return None
    return max(numbers, key=lambda value: abs(value))


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_timestamp(rows: Iterable[Dict[str, Any]]) -> str | None:
    stamps = [dt for dt in (_parse_dt(row.get("timestamp")) for row in rows) if dt is not None]
    if not stamps:
        return None
    return max(stamps).isoformat()


def _latest_by_timestamp(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
    stamped = [(dt, row) for row in rows if (dt := _parse_dt(row.get("timestamp"))) is not None]
    if not stamped:
        return None
    return max(stamped, key=lambda item: item[0])[1]


def _status_verified(status: Any) -> bool:
    return str(status or "").lower() in {"complete", "controller_confirmed", "flow_meter_confirmed", "flow-meter-confirmed"}


def _flow_evidence(controller_rows: List[Dict[str, Any]], flow_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    positive_controller = [row for row in controller_rows if (_to_float(row.get("flow_m3h")) or 0) > 0]
    latest = _latest_by_timestamp(positive_controller)
    provenance = "controller_event"

    # Accept flow-meter records that include a flow rate as a validated source when
    # no positive controller evidence exists.
    if not latest:
        positive_fm_rate = [row for row in flow_rows if (_to_float(row.get("flow_m3h")) or 0) > 0]
        latest = _latest_by_timestamp(positive_fm_rate)
        if latest:
            provenance = "flow_meter"

    max_variance = _max_abs(row.get("variance_percent") for row in flow_rows)

    if not latest:
        return {"status": "unavailable", "notes": ["No positive controller or flow-meter flow evidence found."]}

    severe_pressure = False
    if provenance == "controller_event":
        pressure = _to_float(latest.get("pressure_kpa"))
        if pressure is not None and pressure < 150:
            severe_pressure = True
        if str(latest.get("status", "")).lower() in {"pressure_failure", "critical_pressure", "severe_pressure"}:
            severe_pressure = True

    if max_variance is not None and abs(max_variance) >= 20:
        return {
            "status": "inconsistent",
            "value_m3h": _to_float(latest.get("flow_m3h")),
            "notes": [f"Flow-meter variance reached {max_variance:.1f}%."],
        }
    if severe_pressure:
        return {
            "status": "inconsistent",
            "value_m3h": _to_float(latest.get("flow_m3h")),
            "notes": ["Severe pressure warning prevents validated flow use."],
        }

    pressure_state = "partial"
    if provenance == "controller_event" and latest.get("pressure_kpa") not in ("", None):
        pressure_state = "stable"

    return {
        "status": "validated",
        "value_m3h": _to_float(latest.get("flow_m3h")),
        "provenance": provenance,
        "block": latest.get("block") or latest.get("zone"),
        "timestamp": latest.get("timestamp"),
        "pressure_state": pressure_state,
        "notes": [],
    }


def _recent_irrigation_evidence(rows: List[Dict[str, Any]], block: str) -> Dict[str, Any]:
    verified = [
        row
        for row in rows
        if str(row.get("block", row.get("zone", ""))).lower() == block.lower()
        and (_to_float(row.get("depth_mm")) or 0) > 0
        and _status_verified(row.get("status") or row.get("confirmation"))
    ]
    latest = _latest_by_timestamp(verified)
    if not latest:
        return {"status": "unavailable", "notes": ["No verified recent applied-water event with positive depth."]}
    return {
        "status": "candidate",
        "depth_mm": _to_float(latest.get("depth_mm")),
        "block": latest.get("block") or latest.get("zone"),
        "timestamp": latest.get("timestamp"),
        "confirmation": latest.get("confirmation") or latest.get("status") or "complete",
    }


def _fmt_number(value: float | None, suffix: str = "", digits: int = 1) -> str:
    if value is None:
        return "not available"
    return f"{value:.{digits}f}{suffix}"


_AREA_UNIT_FACTORS: Dict[str, float] = {
    "ha": 1.0, "hectare": 1.0, "hectares": 1.0,
    "ac": 0.404686, "acre": 0.404686, "acres": 0.404686,
    "m2": 1e-4, "sqm": 1e-4, "sq_m": 1e-4,
    "square_meter": 1e-4, "square_meters": 1e-4,
}


def normalize_area_ha(area: Any, unit: Any) -> tuple[float | None, List[str]]:
    """Normalize area to hectares. Returns (area_ha, warnings)."""
    if area is None:
        return None, []
    try:
        area_f = float(area)
    except (TypeError, ValueError):
        return None, [f"Area value '{area}' is not a valid number."]
    if area_f <= 0:
        return None, [f"Area {area_f} is invalid (must be positive). Estimated volume and duration are withheld."]
    if not unit:
        return None, ["Area unit is missing. Estimated volume and duration are withheld until an explicit area unit is provided."]
    unit_key = str(unit).lower().strip().replace("-", "_").replace(" ", "_")
    factor = _AREA_UNIT_FACTORS.get(unit_key)
    if factor is None:
        return None, [f"Unknown area unit '{unit}'. Estimated volume and duration are withheld."]
    return round(area_f * factor, 6), []


class EvidenceOrderViolation(Exception):
    def __init__(self, action_type: str, required_step: str) -> None:
        self.action_type = action_type
        self.required_step = required_step
        super().__init__(
            f"Cannot record '{action_type}' before '{required_step}' is complete. "
            "Evidence steps must follow: recommended → scheduled → applied → observed → verified. "
            "Supply override_reason to record an out-of-order step with an audit entry."
        )


class SchedulingNotAllowed(Exception):
    def __init__(self, reasons: List[str]) -> None:
        self.reasons = reasons
        super().__init__(
            "Scheduling is not allowed because the recommendation does not meet the scheduling gate. "
            f"Reasons: {'; '.join(reasons)}"
        )


def _is_schedulable(recommendation: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if recommendation.get("kernel_action") != "irrigate":
        reasons.append("Kernel action is not 'irrigate'")
    if recommendation.get("estimated_volume_m3") is None:
        reasons.append("Estimated volume is unavailable — area required")
    if recommendation.get("flow_validation_status") != "validated":
        reasons.append("Flow evidence is not validated for execution timing")
    if recommendation.get("gross_depth_mm") is None:
        reasons.append("Gross irrigation depth is unavailable")
    if recommendation.get("duration_min") is None:
        reasons.append("Duration is unavailable — validated flow evidence required")
    return len(reasons) == 0, reasons


def build_artifact(session_id: str, filename: str, content: bytes, content_type: str = "application/octet-stream") -> WorkbenchDataArtifact:
    rows, columns, warnings = parse_uploaded_file(filename, content)
    return WorkbenchDataArtifact(
        artifact_id=str(uuid.uuid4()),
        session_id=session_id,
        filename=filename,
        content_type=content_type,
        source_kind=detect_source_kind(filename, columns),
        rows_detected=len(rows),
        columns_detected=columns,
        parse_status="parsed",
        warnings=warnings,
        parsed_rows=rows,
    )


def create_sample_package_session(workspace_name: str = "Alpha Vineyard · Water Command Center") -> Dict[str, Any]:
    session = create_session(mode="uploaded", workspace_name=workspace_name)
    artifacts = [build_artifact(session.session_id, item.filename, item.content, item.content_type) for item in get_sample_files()]
    SESSIONS[session.session_id]["artifacts"].extend(artifacts)
    SESSIONS[session.session_id]["is_sample_package"] = True
    SESSIONS[session.session_id]["audit"].append(
        {"time": datetime.utcnow().isoformat(), "event": "Sample data package loaded", "artifact_count": len(artifacts)}
    )
    return {"session": session, "artifacts": artifacts}


def create_incomplete_evidence_session(workspace_name: str = "Incomplete Evidence Review · Water Command Center") -> Dict[str, Any]:
    session = create_session(mode="uploaded", workspace_name=workspace_name)
    artifacts = [build_artifact(session.session_id, item.filename, item.content, item.content_type) for item in get_incomplete_evidence_files()]
    SESSIONS[session.session_id]["artifacts"].extend(artifacts)
    SESSIONS[session.session_id]["is_sample_package"] = True
    SESSIONS[session.session_id]["audit"].append(
        {"time": datetime.utcnow().isoformat(), "event": "Incomplete evidence sample package loaded", "artifact_count": len(artifacts)}
    )
    return {"session": session, "artifacts": artifacts}


def _rows_by_kind(artifacts: List[WorkbenchDataArtifact]) -> Dict[str, List[Dict[str, Any]]]:
    rows: Dict[str, List[Dict[str, Any]]] = {}
    for artifact in artifacts:
        rows.setdefault(artifact.source_kind, []).extend(artifact.parsed_rows)
    return rows


def _rows_for(rows: List[Dict[str, Any]], farm: str, block: str) -> List[Dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("farm", "")).lower() == farm.lower()
        and str(row.get("block", row.get("zone", ""))).lower() == block.lower()
    ]


def _first_profile(rows: List[Dict[str, Any]], farm: str, block: str) -> Dict[str, Any]:
    target = _rows_for(rows, farm, block)
    if target:
        return target[0]
    return rows[0] if rows else {}


def _date_window(rows: List[Dict[str, Any]]) -> str:
    stamps = sorted(str(row.get("timestamp", ""))[:10] for row in rows if row.get("timestamp"))
    if not stamps:
        return "not available"
    if stamps[0] == stamps[-1]:
        return stamps[0]
    return f"{stamps[0]} to {stamps[-1]}"


def _field_note_support(notes: List[Dict[str, Any]], farm: str, block: str) -> List[str]:
    selected = []
    farm_l = farm.lower()
    block_l = block.lower()
    for row in notes:
        row_farm = str(row.get("farm", "")).strip()
        row_block = str(row.get("block", "")).strip()
        note = str(row.get("notes", ""))
        if row_farm and row_block:
            # Structured columns present: require both to match.
            if row_farm.lower() == farm_l and row_block.lower() == block_l:
                if note:
                    selected.append(note)
            # Structured columns present but don't match — do not include.
            continue
        # Unstructured note: require BOTH identifiers to appear in the text.
        if farm_l and block_l:
            if farm_l in note.lower() and block_l in note.lower():
                selected.append(note)
        elif farm_l and farm_l in note.lower():
            selected.append(note)
    return selected


_CUSTOMER_READABLE_NEXT_EVIDENCE: Dict[str, str] = {
    "eto_mm": "Upload or connect weather data for the block's region.",
    "crop_type": "Complete crop mapping — specify the crop species for this block.",
    "soil_type": "Complete soil mapping — specify the soil type for this block.",
    "irrigation_method": "Confirm the irrigation method for this block.",
    "field_area_ha": "Provide the block area with an explicit unit (hectares or acres).",
    "validated_flow_or_application_rate": "Upload or connect validated flow evidence for this block.",
    "recent_verified_applied_water_credit": "Upload or connect a recent controller-confirmed or flow-meter-confirmed applied-water event for this block.",
    "block_boundary_mapping": "Map the block boundary before enabling earth observation.",
    "current_field_observation": "Add a current field observation for this block.",
    "block_mapping": "Complete block mapping before scheduling.",
    "farm_mapping": "Complete farm mapping before scheduling.",
    "variety_mapping": "Complete variety mapping for this crop.",
}


def _customer_readable_next_evidence(missing_inputs: List[str]) -> List[str]:
    readable: List[str] = []
    seen: set = set()
    for key in missing_inputs:
        msg = _CUSTOMER_READABLE_NEXT_EVIDENCE.get(key)
        if msg and msg not in seen:
            readable.append(msg)
            seen.add(msg)
    return readable


def assemble_context_from_artifacts(
    artifacts: List[WorkbenchDataArtifact],
    selected_farm: str | None = None,
    selected_block: str | None = None,
) -> Dict[str, Any]:
    rows = _rows_by_kind(artifacts)
    profile_rows = rows.get("crop_profile", [])

    extra_warnings: List[str] = []
    preferred_farm = "Alpha Vineyard"
    preferred_block = "Block A North"

    if selected_farm and selected_block:
        # Explicit scope requested — honor it; disclose gap if no matching profile.
        scoped_profiles = _rows_for(profile_rows, selected_farm, selected_block)
        if scoped_profiles:
            profile = scoped_profiles[0]
        else:
            profile = {}
            extra_warnings.append(
                f"No crop profile matched the requested scope '{selected_farm} / {selected_block}'. "
                "Agronomic context is incomplete; scheduling withheld pending complete evidence."
            )
        farm = selected_farm
        block = selected_block
    elif selected_farm and not selected_block:
        # Partial scope: fail closed — do not default to any block.
        raise ValueError(
            f"'selected_farm' was provided without 'selected_block'. "
            "Both are required for explicit scope analysis. "
            "Omit both to use the default scope."
        )
    elif not selected_farm and selected_block:
        # Partial scope: fail closed — do not fall back to any representative scope.
        raise ValueError(
            f"'selected_block' was provided without 'selected_farm'. "
            "Both are required for explicit scope analysis. "
            "Omit both to use the default scope."
        )
    else:
        # No explicit scope — default to sample-package selection or first profile with disclosure.
        scoped_profiles = _rows_for(profile_rows, preferred_farm, preferred_block)
        if scoped_profiles:
            profile = scoped_profiles[0]
            farm = str(profile.get("farm") or preferred_farm)
            block = str(profile.get("block") or preferred_block)
        elif profile_rows:
            profile = profile_rows[0]
            farm = str(profile.get("farm") or preferred_farm)
            block = str(profile.get("block") or preferred_block)
            if farm != preferred_farm or block != preferred_block:
                extra_warnings.append(
                    f"No explicit farm/block scope was supplied. Analysis defaulted to the first crop profile "
                    f"entry ('{farm} / {block}'). Supply selected_farm and selected_block for precise analysis."
                )
        else:
            profile = {}
            farm = preferred_farm
            block = preferred_block

    # Extract region early — needed to scope regional signals in the loop below.
    region = str(profile.get("region") or "").strip()
    region_l = region.lower() if region else None

    # Source kinds that carry farm+block columns — require exact attribution for selected scope.
    _farm_block_scope_kinds = {
        "controller_events", "controller_logs", "flow_meter", "soil_moisture",
        "satellite_observation", "crop_profile", "field_notes",
    }
    # Source kinds filtered by region — include only matching-region rows for operational signals.
    _region_scope_kinds = {"weather", "water_costs"}

    # Build selected-scope signals: only records with exact farm+block attribution or region match.
    # Unattributed rows (no farm/block columns) are excluded — they cannot be confirmed on-scope.
    farm_l = farm.lower()
    block_l = block.lower()
    signals: List[Any] = []
    for artifact in artifacts:
        schema = infer_schema(artifact.columns_detected)
        for index, row in enumerate(artifact.parsed_rows):
            normalized_row = normalize_units(row, schema)
            if artifact.source_kind in _farm_block_scope_kinds:
                row_farm = str(normalized_row.get("farm", "")).strip().lower()
                row_block = str(normalized_row.get("block", normalized_row.get("zone", ""))).strip().lower()
                # Require both identifiers to be present and match the selected scope.
                if not (row_farm and row_block and row_farm == farm_l and row_block == block_l):
                    continue
            elif artifact.source_kind in _region_scope_kinds:
                # Regional signals require an explicit region match.
                # Without a profile region no regional rows are operationally admitted.
                if not region_l:
                    continue
                row_region = str(normalized_row.get("region", "")).strip().lower()
                if not row_region or row_region != region_l:
                    continue  # Exclude unattributed or non-matching region records from selected scope.
            for key, value in normalized_row.items():
                unit = "mm" if key in {"eto", "rain", "depth_mm"} else None
                signals.append(
                    NormalizedSignal(
                        signal_id=str(uuid.uuid4()),
                        source_kind=artifact.source_kind,
                        field_name=key,
                        canonical_name=key,
                        value=value,
                        unit=unit,
                        timestamp=normalized_row.get("timestamp"),
                        confidence=0.82 if artifact.source_kind != "unknown" else 0.45,
                        raw_reference=f"{artifact.filename}:{index + 1}",
                    ).model_dump()
                )

    # Derive source kind sets after scope filtering.
    selected_source_kinds = sorted({sig["source_kind"] for sig in signals if sig.get("source_kind")})
    package_source_kinds = sorted({artifact.source_kind for artifact in artifacts})

    # Extract area from crop profile so the orchestrator can compute volume and duration.
    area_ha: float | None = None
    area_warnings_from_profile: List[str] = []
    if profile.get("area") is not None:
        area_ha, area_warnings_from_profile = normalize_area_ha(profile.get("area"), profile.get("area_unit"))

    controller_rows = _rows_for(rows.get("controller_events", []) + rows.get("controller_logs", []), farm, block)
    flow_rows = _rows_for(rows.get("flow_meter", []), farm, block)
    soil_rows = _rows_for(rows.get("soil_moisture", []), farm, block)
    satellite_rows = _rows_for(rows.get("satellite_observation", []), farm, block)
    field_notes = _field_note_support(rows.get("field_notes", []), farm, block)
    # Add synthetic signals for safely-attributed text-only field notes (TXT files often lack
    # structured farm/block columns and bypass the signal loop). Attribution was verified by
    # _field_note_support — only include notes that matched the selected farm and block.
    if field_notes and "field_notes" not in selected_source_kinds:
        for _note in field_notes:
            signals.append(
                NormalizedSignal(
                    signal_id=str(uuid.uuid4()),
                    source_kind="field_notes",
                    field_name="field_observation",
                    canonical_name="field_observation",
                    value=_note,
                    confidence=0.75,
                    raw_reference="field_notes:txt",
                ).model_dump()
            )
        selected_source_kinds = sorted(set(selected_source_kinds) | {"field_notes"})
    # Filter weather and water-cost rows to the profile region (region already extracted above).
    all_weather_rows = rows.get("weather", [])
    all_water_cost_rows = rows.get("water_costs", [])
    region_warnings: List[str] = []
    if region:
        weather_rows = [r for r in all_weather_rows if str(r.get("region", "")).strip().lower() == region.lower()]
        water_cost_rows = [r for r in all_water_cost_rows if str(r.get("region", "")).strip().lower() == region.lower()]
        if not weather_rows and all_weather_rows:
            region_warnings.append(
                f"No weather records matched region '{region}'. Weather demand is withheld to avoid cross-region data mix."
            )
        if not water_cost_rows and all_water_cost_rows:
            region_warnings.append(
                f"No water-cost records matched region '{region}'. Water-cost context is withheld."
            )
    else:
        # Region mapping required — withhold both regional evidence types operationally.
        weather_rows = []
        water_cost_rows = []
        if all_weather_rows:
            region_warnings.append(
                "Region mapping is required before using weather demand records. "
                "Weather ETo and rainfall are withheld until region is specified in the crop profile."
            )
        if all_water_cost_rows:
            region_warnings.append(
                "Region mapping is required before using water-cost context. "
                "Water-cost records are withheld until region is specified in the crop profile."
            )

    avg_eto = _avg(row.get("eto_mm", row.get("eto")) for row in weather_rows)
    rain_total = sum(value for value in (_to_float(row.get("rain_forecast_mm", row.get("rain"))) for row in weather_rows) if value)
    avg_deficit = _avg(row.get("deficit_percent") for row in soil_rows)
    avg_moisture = _avg(row.get("moisture_percent") for row in soil_rows)
    flow_evidence = _flow_evidence(controller_rows, flow_rows)
    recent_evidence = _recent_irrigation_evidence(controller_rows + flow_rows, block)
    max_flow_variance = _max_abs(row.get("variance_percent") for row in flow_rows)
    controller_variances = []
    for row in controller_rows:
        scheduled = _to_float(row.get("scheduled_duration_min"))
        applied = _to_float(row.get("applied_duration_min"))
        if scheduled and applied is not None and scheduled > 0:
            controller_variances.append(((applied - scheduled) / scheduled) * 100)
    max_controller_variance = _max_abs(controller_variances)
    applied_variance = max_flow_variance if max_flow_variance is not None else max_controller_variance

    operating_window = str(profile.get("operating_window") or "").strip() or None
    evaluation_baseline_mm = profile.get("evaluation_baseline_mm")
    evaluation_baseline_label = str(profile.get("evaluation_baseline_label") or "").strip() or None

    context: Dict[str, Any] = {
        "signals": signals,
        "farm": farm,
        "block": block,
        "crop": profile.get("crop", "not available"),
        "variety": profile.get("variety", "not available"),
        "soil": profile.get("soil_type", "not available"),
        "irrigation_method": profile.get("irrigation_method", "not available"),
        "root_zone_depth_cm": profile.get("root_zone_depth_cm", "not available"),
        "growth_stage": profile.get("growth_stage", "not available"),
        "management_goal": profile.get("management_goal", "not available"),
        "region": region or None,
        "operating_window": operating_window,
        "evaluation_baseline_mm": evaluation_baseline_mm,
        "evaluation_baseline_label": evaluation_baseline_label,
        "weather_window": _date_window(weather_rows),
        "moisture_deficit": _fmt_number(avg_deficit, "%", 1),
        "flow_variance": _fmt_number(applied_variance, "%", 1),
        "provider_context": ", ".join(sorted({str(row.get("provider")) for row in controller_rows if row.get("provider")})) or "not available",
        "field_notes": field_notes,
        "source_kinds": package_source_kinds,
        "selected_source_kinds": selected_source_kinds,
        "package_source_kinds": package_source_kinds,
        "selected_farm": selected_farm,
        "selected_block": selected_block,
        "metrics": {
            "avg_eto_mm": avg_eto,
            "rain_forecast_total_mm": rain_total,
            "avg_deficit_percent": avg_deficit,
            "avg_moisture_percent": avg_moisture,
            "flow_m3h": flow_evidence.get("value_m3h"),
            "validated_flow_m3h": flow_evidence.get("value_m3h") if flow_evidence.get("status") == "validated" else None,
            "flow_validation_status": flow_evidence.get("status"),
            "flow_evidence": flow_evidence,
            "recent_irrigation_depth_mm": recent_evidence.get("depth_mm"),
            "recent_irrigation_evidence": recent_evidence,
            "recent_irrigation_credit_status": recent_evidence.get("status") if recent_evidence.get("status") != "candidate" else "partial",
            "recent_irrigation_credit_mm": None,
            # evidence_reference_time is NOT set automatically; it must be injected
            # explicitly for historical-package evaluation (sample package or
            # historical_evaluation=True with an explicit evidence_reference_time).
            "max_flow_variance_percent": max_flow_variance,
            "max_controller_variance_percent": max_controller_variance,
            "applied_variance_percent": applied_variance,
            "missing_pressure_count": len([row for row in controller_rows if not str(row.get("pressure_kpa", "")).strip()]),
            "controller_event_count": len(controller_rows),
            "valid_controller_events": len([row for row in controller_rows if str(row.get("status", "")).lower() in {"complete", "variance_watch", "planned_applied_mismatch"}]),
            "satellite_stress_index": _avg(row.get("vegetation_stress_index") for row in satellite_rows),
            "water_cost_per_acre_ft": _avg(row.get("cost_per_acre_ft") for row in water_cost_rows),
        },
        "counts": {
            # Selected-scope counts — used for presence checks, confidence, completeness.
            "controller_events_read": len(controller_rows),
            "weather_records_read": len(weather_rows),
            "soil_readings_read": len(soil_rows),
            "field_notes_parsed": len(field_notes),
            "flow_meter_records_read": len(flow_rows),
            "crop_profile_loaded": len(_rows_for(profile_rows, farm, block)),
            "satellite_observations_read": len(satellite_rows),
            "water_cost_records_read": len(water_cost_rows),
            # Package-wide counts — kept for source-row reporting only.
            "pkg_controller_events_read": len(rows.get("controller_events", [])) + len(rows.get("controller_logs", [])),
            "pkg_soil_readings_read": len(rows.get("soil_moisture", [])),
            "pkg_field_notes_parsed": len(rows.get("field_notes", [])),
            "pkg_flow_meter_records_read": len(rows.get("flow_meter", [])),
            "pkg_crop_profile_loaded": len(profile_rows),
            "pkg_satellite_observations_read": len(rows.get("satellite_observation", [])),
            "pkg_weather_records_read": len(all_weather_rows),
            "pkg_water_cost_records_read": len(all_water_cost_rows),
        },
    }
    # Inject area from crop profile so the orchestrator can compute volume and duration.
    if area_ha is not None:
        context["area"] = area_ha
    if extra_warnings:
        context.setdefault("warnings", []).extend(extra_warnings)
    if area_warnings_from_profile:
        context.setdefault("warnings", []).extend(area_warnings_from_profile)
    if region_warnings:
        context.setdefault("warnings", []).extend(region_warnings)

    # Derive available scope options from crop-profile rows for frontend selectors.
    available_farms: List[str] = sorted({str(p.get("farm", "")).strip() for p in profile_rows if str(p.get("farm", "")).strip()})
    available_blocks_by_farm: Dict[str, List[str]] = {}
    for _p in profile_rows:
        _f = str(_p.get("farm", "")).strip()
        _b = str(_p.get("block", "")).strip()
        if _f and _b:
            blk_list = available_blocks_by_farm.setdefault(_f, [])
            if _b not in blk_list:
                blk_list.append(_b)
    for _f_key in available_blocks_by_farm:
        available_blocks_by_farm[_f_key] = sorted(available_blocks_by_farm[_f_key])
    _scope_dim_keys = [("farm", "farm"), ("block", "block"), ("crop", "crop"), ("variety", "variety"), ("region", "region")]
    _scope_flag_keys = [("farm_mapping_complete", "farm_mapping_complete"), ("block_mapping_complete", "block_mapping_complete"), ("block_boundary_mapped", "block_boundary_mapped")]
    available_scope_dimensions: List[str] = []
    for _dim, _key in _scope_dim_keys:
        if any(str(_p.get(_key, "")).strip() for _p in profile_rows):
            available_scope_dimensions.append(_dim)
    for _dim, _key in _scope_flag_keys:
        if any(bool(_p.get(_key)) for _p in profile_rows):
            available_scope_dimensions.append(_dim)
    context["available_farms"] = available_farms
    context["available_blocks_by_farm"] = available_blocks_by_farm
    context["available_scopes"] = available_scope_dimensions
    context["scope_defaulted"] = bool(len(available_farms) > 1 and not selected_farm)

    context["mapping_completeness"] = _mapping_completeness(context, rows)
    context["source_rows"] = _build_source_rows(
        rows, farm, block, region or None,
        context["metrics"], context["counts"], flow_evidence,
    )
    context["_rows"] = rows
    return context


def assemble_context_from_live(source: str, entity_id: str) -> Dict[str, Any]:
    return {
        "signals": [],
        "farm": "Connected field",
        "block": str(entity_id),
        "crop": "provider context pending",
        "soil": "provider context pending",
        "irrigation_method": "provider context pending",
        "root_zone_depth_cm": "provider context pending",
        "weather_window": "provider context pending",
        "moisture_deficit": "provider context pending",
        "flow_variance": "provider context pending",
        "provider_context": f"{source} entity {entity_id}",
        "source_kinds": ["live_request"],
        "live_request": {
            "source": source,
            "entity_id": entity_id,
            "credential_note": "Provider credentials must be provisioned server-side before live telemetry can be expanded.",
        },
        "metrics": {},
        "counts": {
            "controller_events_read": 0,
            "weather_records_read": 0,
            "soil_readings_read": 0,
            "field_notes_parsed": 0,
            "flow_meter_records_read": 0,
            "crop_profile_loaded": 0,
            "satellite_observations_read": 0,
            "water_cost_records_read": 0,
        },
        "warnings": [],
        "live_inputs_used": [],
        "context_origin": "live",
    }


def _map_live_context(assembled: Dict[str, Any], source: str, entity_id: str) -> Dict[str, Any]:
    """Map a LiveFieldContextAssembler result onto the Workbench context shape.

    Only telemetry the connected source actually returned is reflected; agronomic
    profile fields stay 'provider context pending' because live telemetry does not
    include crop/soil profiles. This keeps the result truthful and never fabricates.
    """
    field = assembled.get("context")
    base = assemble_context_from_live(source, entity_id)
    counts = dict(base["counts"])
    signals: List[Dict[str, Any]] = []

    moisture = getattr(getattr(field, "sensor_context", None), "moisture_percent", None)
    if isinstance(moisture, (int, float)):
        counts["soil_readings_read"] = 1
        signals.append({"canonical_name": "moisture_percent", "value": moisture, "source_kind": "live_telemetry"})
        base["moisture_deficit"] = f"{round(100 - float(moisture))}% deficit (live sensor)"

    events = getattr(getattr(field, "recent_irrigation_context", None), "events_last_7_days", None)
    if isinstance(events, int) and events > 0:
        counts["controller_events_read"] = events

    farm_id = getattr(field, "farm_id", None)
    base.update(
        {
            "signals": signals,
            "farm": farm_id or base["farm"],
        "counts": counts,
        "warnings": list(assembled.get("warnings", [])),
        "live_inputs_used": list(assembled.get("live_inputs_used", [])),
            "context_origin": assembled.get("context_origin", "live"),
            "provider_context": f"{source} entity {entity_id}",
        }
    )
    return base


async def assemble_live_context(source: str, entity_id: str) -> Dict[str, Any]:
    """Assemble live connected-source context via the real assembler.

    Degrades safely (truthful warnings, no fabricated telemetry) when provider
    reads are unavailable, so the Workbench live route always returns a result.
    """
    try:
        assembled = await LiveFieldContextAssembler().assemble(source, entity_id)
        return _map_live_context(assembled, source, entity_id)
    except LiveContextAssemblerError as exc:
        context = assemble_context_from_live(source, entity_id)
        context["warnings"] = [f"live_context_unavailable:{exc}"]
        context["live_inputs_used"] = []
        return context
    except Exception as exc:  # never 500 the live route on adapter faults
        context = assemble_context_from_live(source, entity_id)
        context["warnings"] = [f"live_context_error:{type(exc).__name__}"]
        context["live_inputs_used"] = []
        return context


def _presence_missing(counts: Dict[str, int], live: bool) -> List[str]:
    if live:
        return ["Credential-backed provider telemetry not yet provisioned for this workspace"]
    required = [
        ("controller_events_read", "Controller events missing"),
        ("weather_records_read", "Weather summary missing"),
        ("soil_readings_read", "Soil moisture missing"),
        ("field_notes_parsed", "Field notes missing"),
        ("flow_meter_records_read", "Flow-meter records missing"),
        ("crop_profile_loaded", "Crop profile missing"),
        ("satellite_observations_read", "Earth observation sample layer missing"),
    ]
    return [label for key, label in required if counts.get(key, 0) == 0]


def compute_confidence(signal_count: int, missing: List[str], conflicts: List[str], source_count: int = 1) -> Tuple[float, str]:
    score = 0.46 + min(signal_count, 120) * 0.002 + min(source_count, 8) * 0.045 - len(missing) * 0.055 - len(conflicts) * 0.04
    score = max(0.25, min(0.93, score))
    return round(score, 2), "High" if score >= 0.8 else "Medium" if score >= 0.6 else "Low"


def reconcile_signals(context: Dict[str, Any]) -> ReconciliationResult:
    signals = context.get("signals", [])
    counts = context.get("counts", {})
    metrics = context.get("metrics", {})
    live = bool(context.get("live_request")) and not signals
    missing = _presence_missing(counts, live)
    conflicts = []
    applied_variance = metrics.get("applied_variance_percent")
    has_variance_conflict = applied_variance is not None and abs(applied_variance) >= 10
    has_pressure_conflict = metrics.get("missing_pressure_count", 0) > 0
    if has_variance_conflict:
        conflicts.append("Planned vs applied variance exceeded 10%")
    if has_pressure_conflict:
        conflicts.append("Pressure telemetry has gaps")

    # Use selected_source_kinds for confidence and completeness — not package-wide source count.
    selected_source_kinds = context.get("selected_source_kinds", context.get("source_kinds", []))
    confidence, label = compute_confidence(len(signals), missing, conflicts, len(selected_source_kinds))
    source_count = max(len(selected_source_kinds), 1)
    completeness = max(35, min(96, int(52 + source_count * 6 - len(missing) * 7 - len(conflicts) * 3)))
    avg_eto = metrics.get("avg_eto_mm")
    avg_deficit = metrics.get("avg_deficit_percent")
    satellite_stress = metrics.get("satellite_stress_index")
    controller_total = metrics.get("controller_event_count", 0)
    valid_total = metrics.get("valid_controller_events", 0)
    missing_pressure = metrics.get("missing_pressure_count", 0)

    # Derive interpretation from actual reconciliation state.
    if live:
        interpretation = "Live provider request accepted; expanded telemetry remains pending"
    elif missing and conflicts:
        interpretation = "Sources reconciled, but scheduling remains blocked pending additional evidence and conflict resolution"
    elif missing:
        interpretation = "Sources reconciled, but scheduling remains blocked pending additional evidence"
    elif conflicts:
        interpretation = "Sources reconciled with conflicts detected; verification required before scheduling"
    else:
        interpretation = "Sources reconciled and ready for scheduling review"

    # Summarize field observation support conservatively — no fabricated claims.
    field_obs_count = counts.get("field_notes_parsed", 0)
    if field_obs_count > 0:
        field_obs_support = f"Selected-block field observations are available ({field_obs_count} note{'s' if field_obs_count != 1 else ''})."
    else:
        field_obs_support = "No selected-block field observation is available."

    # Build conflicts_resolved from actual conflict types — do not emit generic pressure claims.
    conflicts_resolved: List[str] = []
    if has_variance_conflict:
        conflicts_resolved.append("Controller and flow-meter variance reconciled with verification watch")
    if has_pressure_conflict:
        conflicts_resolved.append("Missing pressure cases lowered confidence and added a pump-pressure verification requirement")
    if not conflicts_resolved:
        conflicts_resolved = ["No material source conflict required escalation"]

    return ReconciliationResult(
        matched_signals=sorted({signal.get("canonical_name") for signal in signals if signal.get("canonical_name")})[:35],
        conflicts_detected=conflicts,
        missing_inputs=missing,
        confidence_score=confidence,
        confidence_label=label,
        evidence_completeness=f"{completeness}%",
        interpretation=interpretation,
        planned_vs_applied_variance=_fmt_number(applied_variance, "%", 1),
        controller_event_validity=f"{valid_total}/{controller_total} controller events usable; {missing_pressure} missing pressure cases",
        flow_meter_agreement=(
            f"Flow meter variance peaked at {_fmt_number(metrics.get('max_flow_variance_percent'), '%', 1)}"
            if metrics.get("max_flow_variance_percent") is not None
            else "Flow-meter evidence not available"
        ),
        weather_demand=(
            f"Average ETo {_fmt_number(avg_eto, ' mm', 1)} with {metrics.get('rain_forecast_total_mm', 0):.1f} mm forecast rain"
            if avg_eto is not None
            else "Weather demand not available"
        ),
        soil_moisture_deficit=(
            f"Average root-zone deficit {_fmt_number(avg_deficit, '%', 1)}"
            if avg_deficit is not None
            else "Soil deficit not available"
        ),
        field_observation_support=field_obs_support,
        satellite_stress_support=(
            f"Earth observation sample layer stress index {_fmt_number(satellite_stress, '', 2)}"
            if satellite_stress is not None
            else "Earth observation sample layer not available"
        ),
        conflicts_resolved=conflicts_resolved,
    )


def _postprocess_reconciliation_interpretation(
    reconciliation: ReconciliationResult,
    recommendation: Dict[str, Any],
    context: Dict[str, Any],
) -> ReconciliationResult:
    """Update reconciliation interpretation to reflect the final recommendation kernel state."""
    live = bool(context.get("live_request")) and not context.get("signals")
    if live:
        interp = "Live provider request accepted; expanded telemetry remains pending"
    else:
        kernel = recommendation.get("kernel_action")
        schedulable = recommendation.get("schedulable", False)
        if kernel == "irrigate" and schedulable:
            interp = "Sources reconciled into a schedulable water decision"
        elif kernel == "irrigate" and not schedulable:
            interp = "Sources reconciled, but scheduling remains blocked pending additional evidence"
        elif kernel in {"wait", "wait_and_monitor", "monitor"}:
            interp = "Sources reconciled into a wait-and-monitor recommendation"
        elif kernel in {"inspect", "insufficient_data"}:
            interp = "Sources reconciled into an inspection recommendation"
        else:
            return reconciliation  # Unknown kernel — preserve existing interpretation
    return reconciliation.model_copy(update={"interpretation": interp})


def generate_recommendation(reconciliation: ReconciliationResult, context: Dict[str, Any]) -> Dict[str, Any]:
    origin = "live_intelligence_engine" if context.get("context_origin") == "live" else "uploaded_intelligence_engine"
    orchestrated = IrrigationDecisionOrchestrator().run(context, mode=context.get("context_origin", "uploaded"), origin=origin)
    decision = orchestrated["decision"]
    key_drivers = decision.get("key_drivers") or reconciliation.missing_inputs
    duration = decision.get("duration_minutes")
    net_depth = decision.get("net_irrigation_depth_mm")
    gross_depth = decision.get("gross_irrigation_depth_mm")
    volume = decision.get("estimated_volume_m3")
    block = str(context.get("block") or "")
    block_label = f" {block}" if block and block not in ("not available", "") else ""
    action_label = decision.get("recommended_action") or "Decision pending source review"
    if decision.get("action") == "irrigate":
        if duration is not None:
            action_label = f"Irrigate{block_label} — {gross_depth:.1f} mm gross ({duration:.0f} min) in approved window"
        else:
            action_label = f"Irrigate{block_label} — validate flow evidence before scheduling"

    # Compute savings against evaluation baseline if available and action is irrigate.
    estimated_water_savings_pct: float | None = None
    baseline_mm = _to_float(context.get("evaluation_baseline_mm"))
    baseline_label = context.get("evaluation_baseline_label")
    baseline_calculation_note: str | None = None
    if decision.get("action") == "irrigate" and gross_depth is not None and baseline_mm and baseline_mm > 0:
        savings = max(0.0, (baseline_mm - gross_depth) / baseline_mm * 100.0)
        estimated_water_savings_pct = round(savings, 1)
        baseline_calculation_note = (
            f"Savings = (baseline {baseline_mm} mm − recommended {gross_depth:.1f} mm gross) / baseline × 100 = {estimated_water_savings_pct}%"
        )

    next_evidence_required = _customer_readable_next_evidence(decision.get("missing_inputs", []))

    recommendation = {
        "action": action_label,
        "decision": action_label,
        "start_time": decision.get("timing_window"),
        "start": decision.get("timing_window"),
        "duration": f"{duration:.0f} min" if duration is not None else None,
        "duration_min": duration,
        "depth": f"{net_depth:.1f} mm net" if net_depth is not None else None,
        "depth_mm": net_depth,
        "gross_depth": f"{gross_depth:.1f} mm gross" if gross_depth is not None else None,
        "gross_depth_mm": gross_depth,
        "estimated_volume": f"{volume:.1f} m3" if volume is not None else None,
        "estimated_volume_m3": volume,
        "confidence": decision.get("confidence_score") / 100 if isinstance(decision.get("confidence_score"), (int, float)) else reconciliation.confidence_score,
        "confidence_label": decision.get("confidence"),
        "evidence_completeness": decision.get("evidence_completeness"),
        "key_drivers": key_drivers,
        "assumptions": decision.get("assumptions", []),
        "limitations": decision.get("limitations", []),
        "missing_inputs": decision.get("missing_inputs", []),
        "next_evidence_required": next_evidence_required,
        "verification_requirement": "; ".join(decision.get("verification_requirements", [])),
        "calculation_trace": decision.get("calculation_trace", {}),
        "calibration_status": decision.get("calibration_status"),
        "calibration_pack_version": decision.get("calibration_pack_version"),
        "recommendation_origin": origin,
        "flow_validation_status": decision.get("flow_validation_status"),
        "flow_validation_notes": decision.get("flow_validation_notes", []),
        "recent_irrigation_credit_status": decision.get("recent_irrigation_credit_status"),
        "recent_irrigation_credit_notes": decision.get("recent_irrigation_credit_notes", []),
        "kernel_action": decision.get("action"),
        "duration_basis": decision.get("duration_basis"),
        "no_fabricated_duration": duration is None,
        "estimated_water_savings_percent": estimated_water_savings_pct,
        "baseline_label": baseline_label,
        "baseline_value_mm": baseline_mm,
        "recommended_gross_depth_mm": gross_depth,
        "baseline_calculation_note": baseline_calculation_note,
        "baseline_limitation": "This is a representative evaluation-baseline estimate, not a verified tenant-specific production saving." if estimated_water_savings_pct is not None else None,
        "evaluation_reference_time": orchestrated.get("evaluation_reference_time"),
    }

    schedulable, scheduling_reasons = _is_schedulable(recommendation)
    recommendation["schedulable"] = schedulable
    recommendation["scheduling_block_reason"] = scheduling_reasons[0] if scheduling_reasons else None
    recommendation["scheduling_block_reasons"] = scheduling_reasons

    if decision.get("action") in {"insufficient_data", "inspect"} or reconciliation.confidence_score < 0.55:
        recommendation["limitations"] = list(
            dict.fromkeys(
                list(recommendation.get("limitations") or [])
                + ["Source package is incomplete for an operational water recommendation"]
            )
        )
        return recommendation

    return recommendation

def generate_analysis_summary(reconciliation: ReconciliationResult, recommendation: Dict[str, Any]) -> str:
    return (
        f"AGRO-AI reconciled available source evidence, resolved {len(reconciliation.conflicts_detected)} conflicts, "
        f"and produced '{recommendation['action']}' with {reconciliation.confidence_label.lower()} confidence."
    )


def generate_report_artifact(session_id: str, recommendation: Dict[str, Any], reconciliation: ReconciliationResult, context: Dict[str, Any]) -> ReportArtifact:
    summary = generate_analysis_summary(reconciliation, recommendation)
    savings_pct = recommendation.get("estimated_water_savings_percent")
    has_savings = savings_pct is not None
    metrics = {
        "water_saved_assumption": (
            recommendation.get("baseline_limitation") or
            "Water-savings estimate is withheld until tenant-specific baseline and applied-water evidence are available."
        ),
        "evidence_completeness": reconciliation.evidence_completeness,
        "applied_variance": reconciliation.planned_vs_applied_variance,
        "compliance_posture": "Evaluation-session evidence package only; durable tenant persistence is future work.",
        "confidence": recommendation["confidence"],
        "estimated_water_savings_percent": savings_pct,
        "baseline_label": recommendation.get("baseline_label"),
        "baseline_value_mm": recommendation.get("baseline_value_mm"),
        "recommended_gross_depth_mm": recommendation.get("recommended_gross_depth_mm"),
        "baseline_calculation_note": recommendation.get("baseline_calculation_note"),
    }
    export_row = {
        "session_id": session_id,
        "farm": context.get("farm"),
        "block": context.get("block"),
        "action": recommendation["action"],
        "confidence": recommendation["confidence"],
        "evidence_completeness": reconciliation.evidence_completeness,
        "applied_variance": reconciliation.planned_vs_applied_variance,
        "schedulable": recommendation.get("schedulable"),
        "flow_validation_status": recommendation.get("flow_validation_status"),
        "recent_irrigation_credit_status": recommendation.get("recent_irrigation_credit_status"),
    }
    if has_savings:
        export_row.update({
            "estimated_water_savings_percent": savings_pct,
            "baseline_label": recommendation.get("baseline_label"),
            "baseline_value_mm": recommendation.get("baseline_value_mm"),
            "recommended_gross_depth_mm": recommendation.get("recommended_gross_depth_mm"),
            "baseline_calculation_note": recommendation.get("baseline_calculation_note"),
            "baseline_limitation": recommendation.get("baseline_limitation"),
        })
    return ReportArtifact(
        report_id=str(uuid.uuid4()),
        title="Irrigation Intelligence Report",
        report_type="workbench_v1",
        summary=summary,
        metrics=metrics,
        export_rows=[export_row],
    )


def _analysis_trace(context: Dict[str, Any], reconciliation: ReconciliationResult) -> List[Dict[str, Any]]:
    counts = context.get("counts", {})
    # Use selected_source_kinds — unavailable package sources must not improve trace completion.
    source_count = len(context.get("selected_source_kinds", context.get("source_kinds", [])))
    signal_count = len(context.get("signals", []))
    return [
        {
            "title": "Source records ingested",
            "status": "complete" if source_count else "limited",
            "details": f"{source_count} source kinds available; {signal_count} normalized signals prepared.",
            "objects_processed": signal_count,
            "confidence_delta": 0.08 if source_count >= 4 else -0.05,
        },
        {
            "title": "Schema detected",
            "status": "complete" if source_count else "limited",
            "details": "Controller, weather, soil, notes, flow, crop, water-cost, and earth-observation schemas checked.",
            "objects_processed": source_count,
            "confidence_delta": 0.06 if source_count >= 6 else -0.03,
        },
        {
            "title": "Units normalized",
            "status": "complete" if signal_count else "limited",
            "details": "Timestamps, duration fields, ETo, rain, deficit, flow, and variance fields were canonicalized.",
            "objects_processed": signal_count,
            "confidence_delta": 0.05 if signal_count else -0.04,
        },
        {
            "title": "Field context assembled",
            "status": "complete" if counts.get("crop_profile_loaded", 0) else "limited",
            "details": f"{context.get('farm')} / {context.get('block')} matched to {context.get('crop')} on {context.get('soil')} soil.",
            "objects_processed": counts.get("crop_profile_loaded", 0),
            "confidence_delta": 0.07 if counts.get("crop_profile_loaded", 0) else -0.05,
        },
        {
            "title": "Source conflicts reconciled",
            "status": "review" if reconciliation.conflicts_detected else "complete",
            "details": f"{reconciliation.planned_vs_applied_variance} planned-vs-applied variance; {reconciliation.flow_meter_agreement}.",
            "objects_processed": counts.get("controller_events_read", 0) + counts.get("flow_meter_records_read", 0),
            "confidence_delta": -0.04 if reconciliation.conflicts_detected else 0.08,
        },
        {
            "title": "Confidence scored",
            "status": "complete" if counts.get("weather_records_read", 0) and counts.get("soil_readings_read", 0) else "limited",
            "details": f"{reconciliation.weather_demand}; {reconciliation.soil_moisture_deficit}; {reconciliation.field_observation_support}.",
            "objects_processed": counts.get("weather_records_read", 0) + counts.get("soil_readings_read", 0) + counts.get("field_notes_parsed", 0),
            "confidence_delta": 0.09 if counts.get("weather_records_read", 0) and counts.get("soil_readings_read", 0) else -0.06,
        },
        {
            "title": "Recommendation prepared",
            "status": "complete",
            "details": f"{reconciliation.confidence_label} confidence at {reconciliation.confidence_score}; evidence completeness {reconciliation.evidence_completeness}.",
            "objects_processed": len(reconciliation.matched_signals),
            "confidence_delta": 0.04,
        },
        {
            "title": "Verification plan prepared",
            "status": "complete" if reconciliation.confidence_score >= 0.55 else "limited",
            "details": "Recommendation, limitations, report summary, and verification requirement assembled.",
            "objects_processed": 1,
            "confidence_delta": 0.03 if reconciliation.confidence_score >= 0.55 else -0.04,
        },
    ]


def _build_source_rows(
    rows: Dict[str, List[Dict[str, Any]]],
    farm: str,
    block: str,
    region: str | None,
    metrics: Dict[str, Any],
    counts: Dict[str, Any],
    flow_evidence: Dict[str, Any],
) -> List[Dict[str, Any]]:
    result = []

    all_ctrl = rows.get("controller_events", []) + rows.get("controller_logs", [])
    sel_ctrl = _rows_for(all_ctrl, farm, block)
    ctrl_ts = _latest_timestamp(sel_ctrl)
    ctrl_summary = f"{len(sel_ctrl)} events for {block}"
    ctrl_flow = flow_evidence.get("value_m3h") if flow_evidence.get("provenance") == "controller_event" else None
    ctrl_pressure = flow_evidence.get("pressure_state") if flow_evidence.get("provenance") == "controller_event" else None
    if ctrl_flow:
        ctrl_summary += f"; flow {ctrl_flow:.1f} m³/h"
    if ctrl_pressure == "stable":
        ctrl_summary += "; pressure stable"
    ctrl_status = "accepted" if sel_ctrl else "unavailable"
    result.append({
        "source_label": "Controller history",
        "source_kind": "controller_events",
        "selected_scope_record_count": len(sel_ctrl),
        "package_record_count": len(all_ctrl),
        "latest_timestamp": ctrl_ts,
        "latest_signal_summary": ctrl_summary,
        "status": ctrl_status,
        "limitations": [],
        "contribution_label": "Not scored",
    })

    all_weather = rows.get("weather", [])
    sel_weather = (
        [r for r in all_weather if str(r.get("region", "")).strip().lower() == region.lower()]
        if region else all_weather
    )
    avg_eto = metrics.get("avg_eto_mm")
    weather_summary = f"{len(sel_weather)} records"
    if avg_eto is not None:
        weather_summary += f"; avg ETo {avg_eto:.2f} mm/day"
    weather_lims = ([f"No weather records matched region '{region}'"] if not sel_weather and region else [])
    result.append({
        "source_label": "Weather demand",
        "source_kind": "weather",
        "selected_scope_record_count": len(sel_weather),
        "package_record_count": len(all_weather),
        "latest_timestamp": _latest_timestamp(sel_weather),
        "latest_signal_summary": weather_summary,
        "status": "accepted" if sel_weather else "unavailable",
        "limitations": weather_lims,
        "contribution_label": "Not scored",
    })

    all_soil = rows.get("soil_moisture", [])
    sel_soil = _rows_for(all_soil, farm, block)
    avg_deficit = metrics.get("avg_deficit_percent")
    soil_summary = f"{len(sel_soil)} readings for {block}"
    if avg_deficit is not None:
        soil_summary += f"; avg deficit {avg_deficit:.1f}%"
    result.append({
        "source_label": "Soil moisture",
        "source_kind": "soil_moisture",
        "selected_scope_record_count": len(sel_soil),
        "package_record_count": len(all_soil),
        "latest_timestamp": _latest_timestamp(sel_soil),
        "latest_signal_summary": soil_summary,
        "status": "accepted" if sel_soil else "unavailable",
        "limitations": [],
        "contribution_label": "Not scored",
    })

    all_flow = rows.get("flow_meter", [])
    sel_flow = _rows_for(all_flow, farm, block)
    if not sel_flow:
        fm_status = "unavailable"
        fm_notes = ["No flow meter records for this block"]
        fm_summary = "No flow meter records for this block"
    else:
        fm_max_variance = _max_abs(row.get("variance_percent") for row in sel_flow)
        fm_status = "inconsistent" if (fm_max_variance is not None and abs(fm_max_variance) >= 20) else "accepted"
        fm_notes = [f"Flow-meter variance {fm_max_variance:.1f}%"] if fm_status == "inconsistent" else []
        fm_summary = f"{len(sel_flow)} records for {block}"
    result.append({
        "source_label": "Flow meter",
        "source_kind": "flow_meter",
        "selected_scope_record_count": len(sel_flow),
        "package_record_count": len(all_flow),
        "latest_timestamp": _latest_timestamp(sel_flow),
        "latest_signal_summary": fm_summary,
        "status": fm_status,
        "limitations": fm_notes,
        "contribution_label": "Not scored",
    })

    all_notes = rows.get("field_notes", [])
    notes_count = counts.get("field_notes_parsed", 0)
    pkg_notes_count = counts.get("pkg_field_notes_parsed", len(all_notes))
    result.append({
        "source_label": "Field observation",
        "source_kind": "field_notes",
        "selected_scope_record_count": notes_count,
        "package_record_count": pkg_notes_count,
        "latest_timestamp": None,
        "latest_signal_summary": f"{notes_count} field observation{'s' if notes_count != 1 else ''}",
        "status": "accepted" if notes_count > 0 else "unavailable",
        "limitations": [],
        "contribution_label": "Not scored",
    })

    all_sat = rows.get("satellite_observation", [])
    sel_sat = _rows_for(all_sat, farm, block)
    result.append({
        "source_label": "Earth observation layer",
        "source_kind": "satellite_observation",
        "selected_scope_record_count": len(sel_sat),
        "package_record_count": len(all_sat),
        "latest_timestamp": _latest_timestamp(sel_sat),
        "latest_signal_summary": f"{len(sel_sat)} observations for {block}",
        "status": "accepted" if sel_sat else "unavailable",
        "limitations": [],
        "contribution_label": "Not scored",
    })

    all_profile = rows.get("crop_profile", [])
    sel_profile = _rows_for(all_profile, farm, block)
    result.append({
        "source_label": "Crop profile",
        "source_kind": "crop_profile",
        "selected_scope_record_count": len(sel_profile),
        "package_record_count": len(all_profile),
        "latest_timestamp": None,
        "latest_signal_summary": f"Profile for {farm} / {block}",
        "status": "accepted" if sel_profile else "unavailable",
        "limitations": [],
        "contribution_label": "Not scored",
    })

    all_costs = rows.get("water_costs", [])
    sel_costs = (
        [r for r in all_costs if str(r.get("region", "")).strip().lower() == region.lower()]
        if region else all_costs
    )
    result.append({
        "source_label": "Water costs",
        "source_kind": "water_costs",
        "selected_scope_record_count": len(sel_costs),
        "package_record_count": len(all_costs),
        "latest_timestamp": None,
        "latest_signal_summary": f"{len(sel_costs)} cost record{'s' if len(sel_costs) != 1 else ''}",
        "status": "accepted" if sel_costs else "unavailable",
        "limitations": [],
        "contribution_label": "Not scored",
    })

    return result


def _mapping_completeness(
    context: Dict[str, Any],
    rows: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, bool]:
    unknown_values = {"", "unknown", "not available", "null", "none", "provider context pending"}
    farm = str(context.get("farm") or "").strip()
    block = str(context.get("block") or "").strip()
    crop = str(context.get("crop") or "").strip().lower()
    variety = str(context.get("variety") or "").strip().lower()
    soil = str(context.get("soil") or "").strip().lower()
    method = str(context.get("irrigation_method") or "").strip().lower()
    counts = context.get("counts", {})

    crop_known = crop not in unknown_values
    variety_known = variety not in unknown_values
    soil_known = soil not in unknown_values
    method_known = method not in unknown_values

    satellite_available = bool(_rows_for(rows.get("satellite_observation", []), farm, block))
    sel_profile_for_block = _rows_for(rows.get("crop_profile", []), farm, block)
    # farm_mapping_complete: explicit field from crop profile only — not inferred from a non-empty label.
    explicit_farm_mapped = any(bool(p.get("farm_mapping_complete")) for p in sel_profile_for_block)
    # block_mapping_complete: explicit field from crop profile only.
    explicit_block_mapped = any(bool(p.get("block_mapping_complete")) for p in sel_profile_for_block)
    explicit_boundary_mapped = any(bool(p.get("block_boundary_mapped")) for p in sel_profile_for_block)
    # field_observation_available: selected scope only (package-wide fallback removed).
    field_notes_available = counts.get("field_notes_parsed", 0) > 0

    return {
        "farm_mapping_complete": explicit_farm_mapped,
        "block_mapping_complete": explicit_block_mapped,
        "block_boundary_mapped": explicit_boundary_mapped,
        "crop_mapping_complete": crop_known,
        "variety_mapping_complete": variety_known,
        "soil_mapping_complete": soil_known,
        "irrigation_method_mapping_complete": method_known,
        "field_observation_available": field_notes_available,
        "earth_observation_available": satellite_available,
    }


def _data_source_summary(artifacts: List[WorkbenchDataArtifact], live_source: str | None = None) -> Dict[str, Any]:
    source_kinds = sorted({artifact.source_kind for artifact in artifacts})
    if live_source and not source_kinds:
        source_kinds = ["live_request"]
    return {
        "file_count": len(artifacts),
        "rows_parsed": sum(artifact.rows_detected for artifact in artifacts),
        "source_kinds_detected": source_kinds,
        "files": [
            {
                "filename": artifact.filename,
                "source_kind": artifact.source_kind,
                "rows": artifact.rows_detected,
                "columns": artifact.columns_detected,
            }
            for artifact in artifacts
        ],
    }


def _public_context(context: Dict[str, Any]) -> Dict[str, Any]:
    area_ha = context.get("area")
    return {
        "farm": context.get("farm"),
        "block": context.get("block"),
        "crop": context.get("crop"),
        "variety": context.get("variety"),
        "soil": context.get("soil"),
        "irrigation_method": context.get("irrigation_method"),
        "root_zone_depth_cm": context.get("root_zone_depth_cm"),
        "growth_stage": context.get("growth_stage"),
        "management_goal": context.get("management_goal"),
        "region": context.get("region"),
        "operating_window": context.get("operating_window"),
        "area_ha": area_ha,
        "area_unit": "ha" if area_ha is not None else None,
        "evaluation_baseline_mm": context.get("evaluation_baseline_mm"),
        "evaluation_baseline_label": context.get("evaluation_baseline_label"),
        "weather_window": context.get("weather_window"),
        "moisture_deficit": context.get("moisture_deficit"),
        "flow_variance": context.get("flow_variance"),
        "provider_context": context.get("provider_context"),
        "field_notes_used": context.get("field_notes", []),
        "live_request": context.get("live_request"),
        "normalized_signal_count": len(context.get("signals", [])),
        "selected_farm": context.get("selected_farm"),
        "selected_block": context.get("selected_block"),
        "selected_source_kinds": context.get("selected_source_kinds", []),
        "package_source_kinds": context.get("package_source_kinds", []),
        "available_farms": context.get("available_farms", []),
        "available_blocks_by_farm": context.get("available_blocks_by_farm", {}),
        "available_scopes": context.get("available_scopes", []),
        "scope_defaulted": context.get("scope_defaulted", False),
        **(context.get("mapping_completeness") or {}),
    }


def _apply_manual_overrides(context: Dict[str, Any], overrides: Dict[str, Any] | None) -> Dict[str, Any]:
    if not overrides:
        return context
    safe = {k: v for k, v in overrides.items() if v not in (None, "", {}, [])}
    if "crop_type" in safe:
        context["crop"] = safe["crop_type"]
    if "soil_type" in safe:
        context["soil"] = safe["soil_type"]
    if "irrigation_method" in safe:
        context["irrigation_method"] = safe["irrigation_method"]
    if "area" in safe:
        area_ha, area_warnings = normalize_area_ha(safe["area"], safe.get("area_unit"))
        if area_ha is not None:
            context["area"] = area_ha
        if area_warnings:
            context.setdefault("warnings", []).extend(area_warnings)
    if isinstance(safe.get("weather_context"), dict):
        context.setdefault("metrics", {})
        context["metrics"]["avg_eto_mm"] = safe["weather_context"].get("eto_mm", context["metrics"].get("avg_eto_mm"))
        context["metrics"]["rain_forecast_total_mm"] = safe["weather_context"].get(
            "precipitation_forecast_mm",
            context["metrics"].get("rain_forecast_total_mm"),
        )
    if isinstance(safe.get("sensor_context"), dict):
        context.setdefault("metrics", {})
        sensor = safe["sensor_context"]
        context["metrics"]["avg_moisture_percent"] = sensor.get("moisture_percent", context["metrics"].get("avg_moisture_percent"))
        if sensor.get("flow_m3h") is not None:
            context["metrics"]["flow_m3h"] = sensor.get("flow_m3h")
            context["flow_evidence"] = {
                "value_m3h": sensor.get("flow_m3h"),
                "provenance": sensor.get("flow_provenance") or sensor.get("provenance"),
                "block": sensor.get("block") or context.get("block"),
                "timestamp": sensor.get("timestamp"),
                "pressure_state": sensor.get("pressure_state"),
            }
        context["metrics"]["pressure_kpa"] = sensor.get("pressure_kpa", context["metrics"].get("pressure_kpa"))
    if isinstance(safe.get("recent_irrigation_context"), dict):
        context.setdefault("metrics", {})
        recent = safe["recent_irrigation_context"]
        if recent.get("last_depth_mm") is not None:
            context["recent_irrigation_evidence"] = {
                "depth_mm": recent.get("last_depth_mm"),
                "block": recent.get("block") or context.get("block"),
                "timestamp": recent.get("timestamp") or recent.get("last_irrigation_at"),
                "confirmation": recent.get("confirmation") or recent.get("status"),
            }
    if safe.get("field_observations"):
        context["field_notes"] = list(context.get("field_notes", [])) + list(safe["field_observations"])
    context["manual_overrides_used"] = sorted(safe.keys())
    return context


def analyze_session(
    session_id: str,
    mode: str = "uploaded",
    live_source: str | None = None,
    live_entity_id: str | None = None,
    live_context: Dict[str, Any] | None = None,
    manual_overrides: Dict[str, Any] | None = None,
    historical_evaluation: bool | None = None,
    evidence_reference_time: str | None = None,
    selected_farm: str | None = None,
    selected_block: str | None = None,
) -> WorkbenchAnalysisResult:
    store = SESSIONS[session_id]
    artifacts = store["artifacts"]
    is_live = bool(live_source and live_entity_id and not artifacts)
    if is_live:
        # Prefer the real assembler output passed in by the async route; fall
        # back to the degraded (truthful, empty) live context otherwise.
        context = live_context if live_context is not None else assemble_context_from_live(live_source, live_entity_id)
    else:
        context = assemble_context_from_artifacts(artifacts, selected_farm=selected_farm, selected_block=selected_block)
        # Inject evidence_reference_time for sample packages (fixed dataset with known reference)
        # or when the caller explicitly requests historical evaluation.
        if store.get("is_sample_package"):
            ref = _latest_timestamp(
                [row for art in artifacts for row in art.parsed_rows if art.source_kind in {"controller_events", "controller_logs", "flow_meter", "soil_moisture", "weather"}]
            )
            if ref:
                context.setdefault("metrics", {})["evidence_reference_time"] = ref
        elif historical_evaluation and evidence_reference_time:
            context.setdefault("metrics", {})["evidence_reference_time"] = evidence_reference_time
        if live_source and live_entity_id:
            merged = live_context if live_context is not None else assemble_context_from_live(live_source, live_entity_id)
            context["live_request"] = merged.get("live_request")
            context["provider_context"] = f"{context.get('provider_context', 'uploaded evidence')} + {live_source} entity {live_entity_id}"
    context = _apply_manual_overrides(context, manual_overrides)
    if not is_live and context.get("_rows") is not None:
        context["mapping_completeness"] = _mapping_completeness(context, context["_rows"])

    reconciliation = reconcile_signals(context)
    recommendation = generate_recommendation(reconciliation, context)
    reconciliation = _postprocess_reconciliation_interpretation(reconciliation, recommendation, context)
    report = generate_report_artifact(session_id, recommendation, reconciliation, context)
    report_summary = {
        **report.model_dump(),
        "water_saved_assumption": report.metrics["water_saved_assumption"],
        "evidence_completeness": report.metrics["evidence_completeness"],
        "applied_variance": report.metrics["applied_variance"],
        "compliance_posture": report.metrics["compliance_posture"],
        "executive_summary": report.summary,
    }
    limitations = list(dict.fromkeys(recommendation.get("limitations", [])))
    if live_source and live_entity_id:
        limitations.append("Provider credential storage and tenant provisioning must be completed server-side before expanded live telemetry is available.")

    if is_live:
        analysis_mode_val = "live"
        context_origin = "live"
    elif artifacts:
        analysis_mode_val = "uploaded"
        context_origin = "uploaded"
    else:
        analysis_mode_val = mode if mode in ("demo", "live", "uploaded") else "uploaded"
        context_origin = "uploaded"

    result = WorkbenchAnalysisResult(
        analysis_id=str(uuid.uuid4()),
        session_id=session_id,
        status="complete",
        data_sources=_data_source_summary(artifacts, live_source),
        normalized_context=_public_context(context),
        signal_summary=context.get("counts", {}),
        reconciliation=reconciliation,
        recommendation=recommendation,
        verification_plan={
            "steps": ["Recommended", "Scheduled", "Applied", "Observed", "Verified"],
            "requirement": recommendation.get("verification_requirement"),
        },
        report_summary=report_summary,
        source_trace=[{"source": artifact.filename, "warnings": artifact.warnings, "source_kind": artifact.source_kind} for artifact in artifacts],
        analysis_trace=_analysis_trace(context, reconciliation),
        limitations=limitations,
        model_status="deterministic_engine",
        created_at=datetime.utcnow(),
        backend_status="available",
        analysis_mode=analysis_mode_val,
        recommendation_origin=recommendation.get("recommendation_origin", "deterministic_engine"),
        context_origin=context_origin,
        live_inputs_used=list(context.get("live_inputs_used", [])),
        uploaded_artifacts_used=[artifact.filename for artifact in artifacts],
        warnings=list(context.get("warnings", [])),
        source_rows=list(context.get("source_rows", [])),
    )
    store["analysis"] = result
    store["session"].updated_at = datetime.utcnow()
    store["audit"].append({"time": datetime.utcnow().isoformat(), "event": "Workbench analysis completed", "mode": mode})
    return result


EVIDENCE_ORDER = ["recommended", "scheduled", "applied", "observed", "verified"]
EVIDENCE_LABELS = {
    "recommended": "Recommended",
    "scheduled": "Scheduled",
    "applied": "Applied",
    "observed": "Observed",
    "verified": "Verified",
}
EVIDENCE_PREREQUISITES = {
    "scheduled": "recommended",
    "applied": "scheduled",
    "observed": "applied",
    "verified": "observed",
}
EVIDENCE_DEFAULT_TEXT = {
    "scheduled": "Schedule approval recorded.",
    "applied": "Operator applied-water confirmation recorded.",
    "observed": "Field observation recorded.",
    "verified": "Outcome verification recorded for review.",
}
EVIDENCE_TYPES = {
    "recommended": "system_generated",
    "scheduled": "operator_attestation",
    "applied": "operator_attestation",
    "observed": "field_observation",
    "verified": "operator_attestation",
}


def get_evidence_chain(session_id: str) -> Dict[str, Any]:
    store = SESSIONS.get(session_id)
    if not store:
        raise KeyError("Session not found")
    now = datetime.utcnow().isoformat()
    actions = list(store.get("evidence_actions", []))
    latest_by_type = {item["type"]: item for item in actions}
    chain = []
    for key in EVIDENCE_ORDER:
        event = latest_by_type.get(key)
        if key == "recommended" and not event and store.get("analysis"):
            event = {
                "type": "recommended",
                "evidence_type": "system_generated",
                "timestamp": getattr(store["analysis"], "created_at", None).isoformat()
                if getattr(store["analysis"], "created_at", None)
                else now,
                "actor": "AGRO-AI Workbench",
                "evidence_summary": "Verified water decision prepared from the current source package.",
            }
        chain.append(
            {
                "key": key,
                "label": EVIDENCE_LABELS[key],
                "status": "Complete" if event else "Pending",
                "owner": event.get("actor", "Operations user") if event else "Operations user",
                "timestamp": event.get("timestamp", "") if event else "",
                "evidence": event.get("evidence_summary", f"{EVIDENCE_LABELS[key]} pending") if event else f"{EVIDENCE_LABELS[key]} pending",
                "evidence_type": event.get("evidence_type", EVIDENCE_TYPES.get(key, "operator_attestation")) if event else None,
            }
        )
    return {"session_id": session_id, "evidence_chain": chain, "audit_events": store.get("audit", [])}


def record_evidence_action(
    session_id: str,
    action_type: str,
    actor: str,
    evidence_summary: str | None = None,
    payload: Dict[str, Any] | None = None,
    override_reason: str | None = None,
) -> Dict[str, Any]:
    if action_type not in {"scheduled", "applied", "observed", "verified"}:
        raise ValueError("Unsupported evidence action")
    store = SESSIONS.get(session_id)
    if not store:
        raise KeyError("Session not found")

    # Scheduling gate — must run BEFORE any evidence-order override audit is written.
    # override_reason cannot bypass this gate.
    if action_type == "scheduled":
        analysis = store.get("analysis")
        if analysis is None:
            raise SchedulingNotAllowed(["No analysis exists for this session — run analysis before scheduling"])
        rec = getattr(analysis, "recommendation", None) or {}
        if not isinstance(rec, dict) or not rec.get("schedulable", False):
            reasons = (rec.get("scheduling_block_reasons") if isinstance(rec, dict) else []) or ["Recommendation does not meet scheduling gate"]
            raise SchedulingNotAllowed(reasons)

    # Enforce evidence chain ordering.
    prerequisite = EVIDENCE_PREREQUISITES.get(action_type)
    if prerequisite:
        existing = {item["type"] for item in store.get("evidence_actions", [])}
        if prerequisite == "recommended":
            has_prerequisite = bool(store.get("analysis"))
        else:
            has_prerequisite = prerequisite in existing
        if not has_prerequisite:
            if not override_reason:
                raise EvidenceOrderViolation(action_type, prerequisite)
            # Override permitted — write audit entry before recording.
            store["audit"].append({
                "time": datetime.utcnow().isoformat(),
                "event": f"Evidence order override: {action_type} recorded before {prerequisite} was complete.",
                "actor": actor,
                "override_reason": override_reason,
                "override_label": "Evidence sequence override applied with supplied reason.",
            })

    timestamp = datetime.utcnow().isoformat()
    summary = evidence_summary or EVIDENCE_DEFAULT_TEXT[action_type]
    evidence_type = EVIDENCE_TYPES.get(action_type, "operator_attestation")
    payload_data = payload or {}

    event = {
        "type": action_type,
        "evidence_type": evidence_type,
        "status": "recorded",
        "timestamp": timestamp,
        "actor": actor,
        "evidence_summary": summary,
        "payload": payload_data,
    }
    store.setdefault("evidence_actions", []).append(event)
    audit = {
        "time": timestamp,
        "event": f"Evidence action recorded: {action_type}",
        "actor": actor,
        "evidence_type": evidence_type,
        "evidence_summary": summary,
        "persistence": "evaluation-session",
    }
    store["audit"].append(audit)
    return {
        "action_status": "recorded",
        "timestamp": timestamp,
        "actor": actor,
        "evidence_type": evidence_type,
        "evidence_summary": summary,
        "updated_evidence_chain": get_evidence_chain(session_id)["evidence_chain"],
        "audit_event": audit,
    }
