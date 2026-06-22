from __future__ import annotations
import hashlib
import uuid
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.assurance.repository import AssuranceRepository
from app.db.base import get_db
from app.models.workbench import WorkbenchActionRequest, WorkbenchAnalysisRequest, WorkbenchLiveAnalysisRequest
from app.services.api_key_service import APIKeyService
from app.services import workbench_engine as engine
from app.services import workbench_repository
from app.services.workbench_engine import EvidenceOrderViolation

router = APIRouter(prefix="/workbench", tags=["workbench"])
MAX_FILE = 10 * 1024 * 1024

class SessionCreate(BaseModel):
    mode: str = "uploaded"
    workspace_name: str = "Water Command Center"
    assurance_passport_id: str | None = None


def _tenant_from_api_key(db: Session, api_key: str | None) -> str | None:
    if not api_key:
        return None
    key = APIKeyService.verify_api_key(db, api_key)
    if not key:
        raise HTTPException(401, "Invalid API key")
    return str(key.tenant_id)


def _load_store(db: Session, session_id: str):
    store = workbench_repository.load_store(db, session_id)
    if not store:
        store = engine.SESSIONS.get(session_id)
        if store:
            workbench_repository.save_store(db, store)
    if not store:
        raise HTTPException(404, "Session not found")
    engine.SESSIONS[session_id] = store
    return store


def _save_store(db: Session, session_id: str, tenant_id: str | None = None, assurance_passport_id: str | None = None):
    workbench_repository.save_store(
        db,
        engine.SESSIONS[session_id],
        tenant_id=tenant_id,
        assurance_passport_id=assurance_passport_id,
    )

@router.post("/sessions")
def create_session(
    payload: SessionCreate,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_from_api_key(db, x_api_key) if payload.assurance_passport_id else _tenant_from_api_key(db, x_api_key)
    session = engine.create_session(payload.mode, payload.workspace_name)
    _save_store(db, session.session_id, tenant_id=tenant_id, assurance_passport_id=payload.assurance_passport_id)
    return session

@router.post("/sample-package")
def create_sample_package(db: Session = Depends(get_db)):
    package = engine.create_sample_package_session()
    workbench_repository.save_store(db, engine.SESSIONS[package["session"].session_id])
    return package

@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    store = _load_store(db, session_id)
    return {"session": store["session"], "artifacts": store["artifacts"], "latest_analysis": store["analysis"], "audit_trail": store["audit"]}

@router.post("/sessions/{session_id}/upload")
async def upload_file(
    session_id: str,
    file: UploadFile = File(...),
    assurance_passport_id: str | None = Form(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    store = _load_store(db, session_id)
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
    target_passport_id = assurance_passport_id or store.get("assurance_passport_id")
    tenant_id = store.get("tenant_id")
    if target_passport_id:
        tenant_id = tenant_id or _tenant_from_api_key(db, x_api_key)
        if not tenant_id:
            raise HTTPException(403, "Attaching workbench evidence to an Assurance Passport requires an API key")
        try:
            AssuranceRepository(db, tenant_id).add_evidence(target_passport_id, {
                "evidence_type": "water_measurement" if src in {"flow_meter", "controller_events", "irrigation_records"} else "farm_boundary" if src == "crop_profile" else "risk_context" if src == "water_costs" else "workbench_upload",
                "proof_domain": "water_proof" if src in {"flow_meter", "controller_events", "irrigation_records"} else "farm_summary",
                "file_ref": f"workbench://sessions/{session_id}/artifacts/{artifact.artifact_id}",
                "filename": artifact.filename,
                "content_type": artifact.content_type,
                "checksum": hashlib.sha256(content).hexdigest(),
                "truth_label": "reported",
                "review_status": "pending_review",
                "source_system": "workbench_upload",
                "workbench_artifact_id": artifact.artifact_id,
                "metadata": {
                    "source_kind": artifact.source_kind,
                    "rows_detected": artifact.rows_detected,
                    "columns_detected": artifact.columns_detected,
                    "warnings": artifact.warnings,
                },
            }, commit=False)
            engine.SESSIONS[session_id]["assurance_passport_id"] = target_passport_id
            engine.SESSIONS[session_id]["tenant_id"] = tenant_id
        except KeyError as exc:
            raise HTTPException(404, "Assurance Passport not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    _save_store(db, session_id, tenant_id=tenant_id, assurance_passport_id=target_passport_id)
    return artifact

@router.post("/sessions/{session_id}/analyze")
def analyze_session(session_id: str, payload: WorkbenchAnalysisRequest, db: Session = Depends(get_db)):
    _load_store(db, session_id)
    try:
        _ROUTING_KEYS = {"session_id", "mode", "live_source", "live_entity_id", "historical_evaluation", "evidence_reference_time"}
        result = engine.analyze_session(
            session_id,
            payload.mode,
            payload.live_source,
            payload.live_entity_id,
            historical_evaluation=payload.historical_evaluation,
            evidence_reference_time=payload.evidence_reference_time,
            manual_overrides=payload.model_dump(exclude=_ROUTING_KEYS, exclude_none=True),
        )
        _save_store(db, session_id)
        return result
    except Exception as e:
        raise HTTPException(400, f"Live source unavailable. Uploaded-data analysis remains available. {e}")

@router.post('/analyze-live')
async def analyze_live(payload: WorkbenchLiveAnalysisRequest, db: Session = Depends(get_db)):
    source = payload.source
    entity_id = str(payload.entity_id)
    session = engine.create_session(mode="live", workspace_name="Water Command Center")
    # Use the real LiveFieldContextAssembler; it degrades safely (truthful
    # warnings, no fabricated telemetry) so this route always returns a result.
    live_context = await engine.assemble_live_context(source, entity_id)
    result = engine.analyze_session(
        session.session_id,
        "live",
        live_source=source,
        live_entity_id=entity_id,
        live_context=live_context,
        manual_overrides=payload.model_dump(exclude={"source", "entity_id"}, exclude_none=True),
    )
    _save_store(db, session.session_id)
    return result

@router.get('/sessions/{session_id}/report')
def get_report(session_id: str, db: Session = Depends(get_db)):
    store = _load_store(db, session_id)
    if not store or not store.get("analysis"):
        raise HTTPException(404, "Report not available")
    return store["analysis"].report_summary


def _record_action(session_id: str, action_type: str, payload: WorkbenchActionRequest, db: Session):
    _load_store(db, session_id)
    try:
        result = engine.record_evidence_action(
            session_id, action_type, payload.actor,
            payload.evidence_summary, payload.payload,
            override_reason=payload.override_reason,
        )
        _save_store(db, session_id)
        return result
    except KeyError:
        raise HTTPException(404, "Session not found")
    except EvidenceOrderViolation as exc:
        raise HTTPException(
            409,
            f"{exc} Supply override_reason in the request body to record this step out of order.",
        )


@router.post('/sessions/{session_id}/actions/schedule')
def schedule_action(session_id: str, payload: WorkbenchActionRequest, db: Session = Depends(get_db)):
    return _record_action(session_id, "scheduled", payload, db)


@router.post('/sessions/{session_id}/actions/applied')
def applied_action(session_id: str, payload: WorkbenchActionRequest, db: Session = Depends(get_db)):
    return _record_action(session_id, "applied", payload, db)


@router.post('/sessions/{session_id}/actions/observe')
def observe_action(session_id: str, payload: WorkbenchActionRequest, db: Session = Depends(get_db)):
    return _record_action(session_id, "observed", payload, db)


@router.post('/sessions/{session_id}/actions/verify')
def verify_action(session_id: str, payload: WorkbenchActionRequest, db: Session = Depends(get_db)):
    return _record_action(session_id, "verified", payload, db)


@router.get('/sessions/{session_id}/evidence-chain')
def evidence_chain(session_id: str, db: Session = Depends(get_db)):
    _load_store(db, session_id)
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
