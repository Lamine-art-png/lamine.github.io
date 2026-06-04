from __future__ import annotations
import uuid
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.models.workbench import WorkbenchActionRequest, WorkbenchAnalysisRequest, WorkbenchLiveAnalysisRequest
from app.services import workbench_engine as engine
from app.services.workbench_engine import EvidenceOrderViolation, SchedulingNotAllowed

router = APIRouter(prefix="/workbench", tags=["workbench"])
MAX_FILE = 10 * 1024 * 1024

class SessionCreate(BaseModel):
    mode: str = "uploaded"
    workspace_name: str = "Water Command Center"

class SamplePackageCreate(BaseModel):
    scenario: str = "validated_operating_block"

@router.post("/sessions")
def create_session(payload: SessionCreate):
    return engine.create_session(payload.mode, payload.workspace_name)

@router.post("/sample-package")
def create_sample_package(payload: SamplePackageCreate = SamplePackageCreate()):
    if payload.scenario == "incomplete_evidence_review":
        return engine.create_incomplete_evidence_session()
    return engine.create_sample_package_session()

@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    store = engine.SESSIONS.get(session_id)
    if not store:
        raise HTTPException(404, "Session not found")
    return {"session": store["session"], "artifacts": store["artifacts"], "latest_analysis": store["analysis"], "audit_trail": store["audit"]}

@router.post("/sessions/{session_id}/upload")
async def upload_file(session_id: str, file: UploadFile = File(...)):
    if session_id not in engine.SESSIONS:
        raise HTTPException(404, "Session not found")
    ext = file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else ''
    if ext not in engine.ALLOWED_EXT:
        raise HTTPException(400, "Unsupported file type")
    content = await file.read()
    if len(content) > MAX_FILE:
        raise HTTPException(413, "File exceeds 10 MB")
    rows, cols, warnings = engine.parse_uploaded_file(file.filename, content)
    src = engine.detect_source_kind(file.filename, cols)
    art = {"artifact_id": str(uuid.uuid4()), "session_id": session_id, "filename": file.filename, "content_type": file.content_type or "application/octet-stream", "source_kind": src, "rows_detected": len(rows), "columns_detected": cols, "parse_status": "parsed", "warnings": warnings, "parsed_rows": rows}
    artifact = engine.WorkbenchDataArtifact(**art)
    engine.SESSIONS[session_id]["artifacts"].append(artifact)
    return artifact

@router.post("/sessions/{session_id}/analyze")
def analyze_session(session_id: str, payload: WorkbenchAnalysisRequest):
    if session_id not in engine.SESSIONS:
        raise HTTPException(404, "Session not found")
    try:
        _ROUTING_KEYS = {"session_id", "mode", "live_source", "live_entity_id", "historical_evaluation", "evidence_reference_time", "selected_farm", "selected_block"}
        return engine.analyze_session(
            session_id,
            payload.mode,
            payload.live_source,
            payload.live_entity_id,
            historical_evaluation=payload.historical_evaluation,
            evidence_reference_time=payload.evidence_reference_time,
            selected_farm=payload.selected_farm,
            selected_block=payload.selected_block,
            manual_overrides=payload.model_dump(exclude=_ROUTING_KEYS, exclude_none=True),
        )
    except Exception as e:
        raise HTTPException(400, f"Live source unavailable. Uploaded-data analysis remains available. {e}")

@router.post('/analyze-live')
async def analyze_live(payload: WorkbenchLiveAnalysisRequest):
    source = payload.source
    entity_id = str(payload.entity_id)
    session = engine.create_session(mode="live", workspace_name="Water Command Center")
    # Use the real LiveFieldContextAssembler; it degrades safely (truthful
    # warnings, no fabricated telemetry) so this route always returns a result.
    live_context = await engine.assemble_live_context(source, entity_id)
    return engine.analyze_session(
        session.session_id,
        "live",
        live_source=source,
        live_entity_id=entity_id,
        live_context=live_context,
        manual_overrides=payload.model_dump(exclude={"source", "entity_id"}, exclude_none=True),
    )

@router.get('/sessions/{session_id}/report')
def get_report(session_id: str):
    store = engine.SESSIONS.get(session_id)
    if not store or not store.get("analysis"):
        raise HTTPException(404, "Report not available")
    return store["analysis"].report_summary


def _record_action(session_id: str, action_type: str, payload: WorkbenchActionRequest):
    try:
        return engine.record_evidence_action(
            session_id, action_type, payload.actor,
            payload.evidence_summary, payload.payload,
            override_reason=payload.override_reason,
        )
    except KeyError:
        raise HTTPException(404, "Session not found")
    except EvidenceOrderViolation as exc:
        raise HTTPException(
            409,
            f"{exc} Supply override_reason in the request body to record this step out of order.",
        )
    except SchedulingNotAllowed as exc:
        raise HTTPException(
            409,
            f"Scheduling not allowed: {'; '.join(exc.reasons)}. The recommendation does not meet the scheduling gate and cannot be scheduled.",
        )


@router.post('/sessions/{session_id}/actions/schedule')
def schedule_action(session_id: str, payload: WorkbenchActionRequest):
    return _record_action(session_id, "scheduled", payload)


@router.post('/sessions/{session_id}/actions/applied')
def applied_action(session_id: str, payload: WorkbenchActionRequest):
    return _record_action(session_id, "applied", payload)


@router.post('/sessions/{session_id}/actions/observe')
def observe_action(session_id: str, payload: WorkbenchActionRequest):
    return _record_action(session_id, "observed", payload)


@router.post('/sessions/{session_id}/actions/verify')
def verify_action(session_id: str, payload: WorkbenchActionRequest):
    return _record_action(session_id, "verified", payload)


@router.get('/sessions/{session_id}/evidence-chain')
def evidence_chain(session_id: str):
    try:
        return engine.get_evidence_chain(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")

@router.get('/schema')
def schema():
    return {
        "supported_file_types": sorted(list(engine.ALLOWED_EXT)),
        "expected_fields": {
            "controller_events.csv": ["timestamp", "farm", "block", "zone", "provider", "event_type", "scheduled_duration_min", "applied_duration_min", "flow_m3h", "pressure_kpa", "status"],
            "weather_summary.csv": ["timestamp", "region", "eto_mm", "rain_forecast_mm", "temperature_c", "humidity_pct", "wind_kph"],
            "soil_moisture.csv": ["timestamp", "farm", "block", "depth_cm", "moisture_percent", "deficit_percent", "sensor_health"],
            "field_notes.txt": ["free-text field observations"],
            "flow_meter.csv": ["timestamp", "farm", "block", "meter_id", "planned_m3", "actual_m3", "variance_percent"],
            "crop_profile.json": ["farm", "block", "crop", "variety", "soil_type", "irrigation_method", "root_zone_depth_cm", "growth_stage", "management_goal"],
            "water_costs.csv": ["region", "water_source", "cost_per_acre_ft", "allocation_status", "compliance_context"],
            "satellite_observation.csv": ["timestamp", "farm", "block", "ndvi", "canopy_temperature_c", "vegetation_stress_index", "source_label"],
        },
        "alias_map": engine.ALIAS,
        "output_schema": ["data_sources", "normalized_context", "signal_summary", "reconciliation", "recommendation", "verification_plan", "report_summary", "analysis_trace"],
    }
