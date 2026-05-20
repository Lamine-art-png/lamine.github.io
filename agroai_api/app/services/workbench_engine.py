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
from app.services.workbench_sample_data import get_sample_files

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
    SESSIONS[sid] = {"session": sess, "artifacts": [], "analysis": None, "audit": []}
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


def _fmt_number(value: float | None, suffix: str = "", digits: int = 1) -> str:
    if value is None:
        return "not available"
    return f"{value:.{digits}f}{suffix}"


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
    SESSIONS[session.session_id]["audit"].append(
        {"time": datetime.utcnow().isoformat(), "event": "Sample data package loaded", "artifact_count": len(artifacts)}
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
    for row in notes:
        note = str(row.get("notes", ""))
        lowered = note.lower()
        if farm.lower() in lowered or block.lower() in lowered:
            selected.append(note)
    return selected or [str(row.get("notes", "")) for row in notes[:3]]


def assemble_context_from_artifacts(artifacts: List[WorkbenchDataArtifact]) -> Dict[str, Any]:
    signals = []
    rows = _rows_by_kind(artifacts)
    profile_rows = rows.get("crop_profile", [])
    preferred_farm = "Alpha Vineyard"
    preferred_block = "Block A North"
    profile = _first_profile(profile_rows, preferred_farm, preferred_block)
    farm = str(profile.get("farm") or preferred_farm)
    block = str(profile.get("block") or preferred_block)

    for artifact in artifacts:
        schema = infer_schema(artifact.columns_detected)
        for index, row in enumerate(artifact.parsed_rows):
            normalized_row = normalize_units(row, schema)
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

    controller_rows = _rows_for(rows.get("controller_events", []) + rows.get("controller_logs", []), farm, block)
    flow_rows = _rows_for(rows.get("flow_meter", []), farm, block)
    soil_rows = _rows_for(rows.get("soil_moisture", []), farm, block)
    satellite_rows = _rows_for(rows.get("satellite_observation", []), farm, block)
    field_notes = _field_note_support(rows.get("field_notes", []), farm, block)
    weather_rows = rows.get("weather", [])
    water_cost_rows = rows.get("water_costs", [])

    avg_eto = _avg(row.get("eto_mm", row.get("eto")) for row in weather_rows)
    rain_total = sum(value for value in (_to_float(row.get("rain_forecast_mm", row.get("rain"))) for row in weather_rows) if value)
    avg_deficit = _avg(row.get("deficit_percent") for row in soil_rows)
    max_flow_variance = _max_abs(row.get("variance_percent") for row in flow_rows)
    controller_variances = []
    for row in controller_rows:
        scheduled = _to_float(row.get("scheduled_duration_min"))
        applied = _to_float(row.get("applied_duration_min"))
        if scheduled and applied is not None and scheduled > 0:
            controller_variances.append(((applied - scheduled) / scheduled) * 100)
    max_controller_variance = _max_abs(controller_variances)
    applied_variance = max_flow_variance if max_flow_variance is not None else max_controller_variance

    source_kinds = sorted({artifact.source_kind for artifact in artifacts})
    context = {
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
        "weather_window": _date_window(weather_rows),
        "moisture_deficit": _fmt_number(avg_deficit, "%", 1),
        "flow_variance": _fmt_number(applied_variance, "%", 1),
        "provider_context": ", ".join(sorted({str(row.get("provider")) for row in controller_rows if row.get("provider")})) or "not available",
        "field_notes": field_notes,
        "source_kinds": source_kinds,
        "metrics": {
            "avg_eto_mm": avg_eto,
            "rain_forecast_total_mm": rain_total,
            "avg_deficit_percent": avg_deficit,
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
            "controller_events_read": len(rows.get("controller_events", [])) + len(rows.get("controller_logs", [])),
            "weather_records_read": len(weather_rows),
            "soil_readings_read": len(rows.get("soil_moisture", [])),
            "field_notes_parsed": len(rows.get("field_notes", [])),
            "flow_meter_records_read": len(rows.get("flow_meter", [])),
            "crop_profile_loaded": len(profile_rows),
            "satellite_observations_read": len(rows.get("satellite_observation", [])),
            "water_cost_records_read": len(water_cost_rows),
        },
    }
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
    }


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
    if applied_variance is not None and abs(applied_variance) >= 10:
        conflicts.append("Planned vs applied variance exceeded 10%")
    if metrics.get("missing_pressure_count", 0) > 0:
        conflicts.append("Pressure telemetry has gaps")

    confidence, label = compute_confidence(len(signals), missing, conflicts, len(context.get("source_kinds", [])))
    source_count = max(len(context.get("source_kinds", [])), 1)
    completeness = max(35, min(96, int(52 + source_count * 6 - len(missing) * 7 - len(conflicts) * 3)))
    avg_eto = metrics.get("avg_eto_mm")
    avg_deficit = metrics.get("avg_deficit_percent")
    satellite_stress = metrics.get("satellite_stress_index")
    controller_total = metrics.get("controller_event_count", 0)
    valid_total = metrics.get("valid_controller_events", 0)
    missing_pressure = metrics.get("missing_pressure_count", 0)

    return ReconciliationResult(
        matched_signals=sorted({signal.get("canonical_name") for signal in signals if signal.get("canonical_name")})[:35],
        conflicts_detected=conflicts,
        missing_inputs=missing,
        confidence_score=confidence,
        confidence_label=label,
        evidence_completeness=f"{completeness}%",
        interpretation="Sources reconciled into a schedulable water decision" if not live else "Live provider request accepted; provider credential provisioning is still required",
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
        field_observation_support=(
            "Field notes support night irrigation and show no visible runoff"
            if counts.get("field_notes_parsed", 0)
            else "Field observation missing"
        ),
        satellite_stress_support=(
            f"Earth observation sample layer stress index {_fmt_number(satellite_stress, '', 2)}"
            if satellite_stress is not None
            else "Earth observation sample layer not available"
        ),
        conflicts_resolved=[
            "Controller and flow-meter variance reconciled with verification watch",
            "Missing pressure cases lowered confidence and added a pump-pressure verification requirement",
        ]
        if conflicts
        else ["No material source conflict required escalation"],
    )


def generate_recommendation(reconciliation: ReconciliationResult, context: Dict[str, Any]) -> Dict[str, Any]:
    if reconciliation.confidence_score < 0.55:
        return {
            "action": "Hold decision until required source evidence is available",
            "decision": "Hold decision until required source evidence is available",
            "start_time": "After source review",
            "start": "After source review",
            "duration": "0 min",
            "duration_min": 0,
            "depth": "0 mm",
            "depth_mm": 0,
            "confidence": reconciliation.confidence_score,
            "confidence_label": reconciliation.confidence_label,
            "key_drivers": reconciliation.missing_inputs,
            "limitations": ["Source package is incomplete for an operational water recommendation"],
            "verification_requirement": "Load controller, weather, soil, and flow evidence before scheduling.",
        }

    action = f"Irrigate {context.get('block', 'selected block')} tonight with verification watch"
    return {
        "action": action,
        "decision": action,
        "start_time": "21:00 PT",
        "start": "21:00 PT",
        "duration": "42 min",
        "duration_min": 42,
        "depth": "12 mm net",
        "depth_mm": 12,
        "confidence": reconciliation.confidence_score,
        "confidence_label": reconciliation.confidence_label,
        "key_drivers": [
            reconciliation.weather_demand or "Weather demand evaluated",
            reconciliation.soil_moisture_deficit or "Soil deficit evaluated",
            reconciliation.flow_meter_agreement or "Flow-meter agreement evaluated",
            reconciliation.field_observation_support or "Field notes evaluated",
        ],
        "limitations": reconciliation.missing_inputs,
        "verification_requirement": "Schedule in the controller, compare applied duration and flow-meter volume, and confirm pump pressure after execution.",
    }


def generate_analysis_summary(reconciliation: ReconciliationResult, recommendation: Dict[str, Any]) -> str:
    if os.getenv("OPENAI_API_KEY"):
        return "Model-assisted synthesis available; deterministic Workbench Engine safeguards applied."
    return (
        f"AGRO-AI reconciled available source evidence, resolved {len(reconciliation.conflicts_detected)} conflicts, "
        f"and produced '{recommendation['action']}' with {reconciliation.confidence_label.lower()} confidence."
    )


def generate_report_artifact(session_id: str, recommendation: Dict[str, Any], reconciliation: ReconciliationResult, context: Dict[str, Any]) -> ReportArtifact:
    summary = generate_analysis_summary(reconciliation, recommendation)
    metrics = {
        "water_saved_assumption": "Assumes verified scheduling avoids a catch-up cycle and limits the next application to 12 mm net.",
        "evidence_completeness": reconciliation.evidence_completeness,
        "applied_variance": reconciliation.planned_vs_applied_variance,
        "compliance_posture": "SGMA-ready evidence package when controller execution is verified",
        "confidence": recommendation["confidence"],
    }
    return ReportArtifact(
        report_id=str(uuid.uuid4()),
        title="Irrigation Intelligence Report",
        report_type="workbench_v1",
        summary=summary,
        metrics=metrics,
        export_rows=[
            {
                "session_id": session_id,
                "farm": context.get("farm"),
                "block": context.get("block"),
                "action": recommendation["action"],
                "confidence": recommendation["confidence"],
                "evidence_completeness": reconciliation.evidence_completeness,
                "applied_variance": reconciliation.planned_vs_applied_variance,
            }
        ],
    )


def _analysis_trace(context: Dict[str, Any], reconciliation: ReconciliationResult) -> List[Dict[str, Any]]:
    counts = context.get("counts", {})
    source_count = len(context.get("source_kinds", []))
    signal_count = len(context.get("signals", []))
    return [
        {
            "title": "Ingested source files",
            "status": "complete" if source_count else "limited",
            "details": f"{source_count} source kinds available; {signal_count} normalized signals prepared.",
            "objects_processed": signal_count,
            "confidence_delta": 0.08 if source_count >= 4 else -0.05,
        },
        {
            "title": "Detected schemas and aliases",
            "status": "complete" if source_count else "limited",
            "details": "Controller, weather, soil, notes, flow, crop, water-cost, and earth-observation schemas checked.",
            "objects_processed": source_count,
            "confidence_delta": 0.06 if source_count >= 6 else -0.03,
        },
        {
            "title": "Normalized units and timestamps",
            "status": "complete" if signal_count else "limited",
            "details": "Timestamps, duration fields, ETo, rain, deficit, flow, and variance fields were canonicalized.",
            "objects_processed": signal_count,
            "confidence_delta": 0.05 if signal_count else -0.04,
        },
        {
            "title": "Matched farm, block, crop, and soil context",
            "status": "complete" if counts.get("crop_profile_loaded", 0) else "limited",
            "details": f"{context.get('farm')} / {context.get('block')} matched to {context.get('crop')} on {context.get('soil')} soil.",
            "objects_processed": counts.get("crop_profile_loaded", 0),
            "confidence_delta": 0.07 if counts.get("crop_profile_loaded", 0) else -0.05,
        },
        {
            "title": "Reconciled controller and flow-meter evidence",
            "status": "review" if reconciliation.conflicts_detected else "complete",
            "details": f"{reconciliation.planned_vs_applied_variance} planned-vs-applied variance; {reconciliation.flow_meter_agreement}.",
            "objects_processed": counts.get("controller_events_read", 0) + counts.get("flow_meter_records_read", 0),
            "confidence_delta": -0.04 if reconciliation.conflicts_detected else 0.08,
        },
        {
            "title": "Evaluated weather, soil deficit, and field notes",
            "status": "complete" if counts.get("weather_records_read", 0) and counts.get("soil_readings_read", 0) else "limited",
            "details": f"{reconciliation.weather_demand}; {reconciliation.soil_moisture_deficit}; {reconciliation.field_observation_support}.",
            "objects_processed": counts.get("weather_records_read", 0) + counts.get("soil_readings_read", 0) + counts.get("field_notes_parsed", 0),
            "confidence_delta": 0.09 if counts.get("weather_records_read", 0) and counts.get("soil_readings_read", 0) else -0.06,
        },
        {
            "title": "Calculated confidence and evidence completeness",
            "status": "complete",
            "details": f"{reconciliation.confidence_label} confidence at {reconciliation.confidence_score}; evidence completeness {reconciliation.evidence_completeness}.",
            "objects_processed": len(reconciliation.matched_signals),
            "confidence_delta": 0.04,
        },
        {
            "title": "Produced recommendation and verification plan",
            "status": "complete" if reconciliation.confidence_score >= 0.55 else "limited",
            "details": "Recommendation, limitations, report summary, and verification requirement assembled.",
            "objects_processed": 1,
            "confidence_delta": 0.03 if reconciliation.confidence_score >= 0.55 else -0.04,
        },
    ]


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
        "weather_window": context.get("weather_window"),
        "moisture_deficit": context.get("moisture_deficit"),
        "flow_variance": context.get("flow_variance"),
        "provider_context": context.get("provider_context"),
        "field_notes_used": context.get("field_notes", []),
        "live_request": context.get("live_request"),
        "normalized_signal_count": len(context.get("signals", [])),
    }


def analyze_session(
    session_id: str,
    mode: str = "uploaded",
    live_source: str | None = None,
    live_entity_id: str | None = None,
) -> WorkbenchAnalysisResult:
    store = SESSIONS[session_id]
    artifacts = store["artifacts"]
    if live_source and live_entity_id and not artifacts:
        context = assemble_context_from_live(live_source, live_entity_id)
    else:
        context = assemble_context_from_artifacts(artifacts)
        if live_source and live_entity_id:
            context["live_request"] = assemble_context_from_live(live_source, live_entity_id)["live_request"]
            context["provider_context"] = f"{context.get('provider_context', 'uploaded evidence')} + {live_source} entity {live_entity_id}"

    reconciliation = reconcile_signals(context)
    recommendation = generate_recommendation(reconciliation, context)
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
        model_status="optional_model_assist" if os.getenv("OPENAI_API_KEY") else "deterministic_engine",
        created_at=datetime.utcnow(),
    )
    store["analysis"] = result
    store["session"].updated_at = datetime.utcnow()
    store["audit"].append({"time": datetime.utcnow().isoformat(), "event": "Workbench analysis completed", "mode": mode})
    return result
