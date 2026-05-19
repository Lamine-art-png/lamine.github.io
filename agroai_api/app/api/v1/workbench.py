from __future__ import annotations
import uuid
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.models.workbench import WorkbenchAnalysisRequest
from app.services import workbench_engine as engine

router = APIRouter(prefix="/workbench", tags=["workbench"])
MAX_FILE = 10 * 1024 * 1024

class SessionCreate(BaseModel):
    mode: str = "uploaded"
    workspace_name: str = "AGRO-AI Workbench"

@router.post("/sessions")
def create_session(payload: SessionCreate):
    return engine.create_session(payload.mode, payload.workspace_name)

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
        return engine.analyze_session(session_id, payload.mode, payload.live_source, payload.live_entity_id)
    except Exception as e:
        raise HTTPException(400, f"Live source unavailable. Uploaded-data analysis remains available. {e}")

@router.post('/analyze-live')
def analyze_live(payload: dict):
    session = engine.create_session(mode="live", workspace_name="Live Workbench")
    return engine.analyze_session(session.session_id, "live", payload.get("source","wiseconn"), str(payload.get("entity_id","162803")))

@router.get('/sessions/{session_id}/report')
def get_report(session_id: str):
    store = engine.SESSIONS.get(session_id)
    if not store or not store.get("analysis"):
        raise HTTPException(404, "Report not available")
    return store["analysis"].report_summary

@router.get('/schema')
def schema():
    return {"supported_file_types": sorted(list(engine.ALLOWED_EXT)), "expected_fields": ["timestamp","zone","duration_min","depth_mm","eto","rain","soil_moisture","notes"], "alias_map": engine.ALIAS, "output_schema": ["reconciliation","recommendation","verification_plan","report_summary"]}
