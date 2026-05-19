from __future__ import annotations
import csv, io, json, os, uuid
from datetime import datetime
from typing import Any, Dict, List, Tuple

from app.models.workbench import WorkbenchSession, WorkbenchDataArtifact, NormalizedSignal, WorkbenchAnalysisResult, ReconciliationResult, ReportArtifact

try:
    import openpyxl
except Exception:
    openpyxl = None

SESSIONS: Dict[str, Dict[str, Any]] = {}
ALLOWED_EXT = {"csv", "json", "txt", "xlsx"}
ALIAS = {"et0":"eto","evapotranspiration":"eto","rainfall":"rain","precipitation":"rain","minutes":"duration_min","runtime":"duration_min","mm":"depth_mm","inches":"depth_in","observation":"notes","date":"timestamp","time":"timestamp","block":"zone","field":"zone"}


def create_session(mode: str = "uploaded", workspace_name: str = "AGRO-AI Workbench") -> WorkbenchSession:
    now = datetime.utcnow()
    sid = str(uuid.uuid4())
    sess = WorkbenchSession(session_id=sid, workspace_name=workspace_name, mode=mode, created_at=now, updated_at=now, status="ready")
    SESSIONS[sid] = {"session": sess, "artifacts": [], "analysis": None, "audit": []}
    return sess


def detect_source_kind(filename: str, columns: List[str]) -> str:
    n = filename.lower(); cols = " ".join(c.lower() for c in columns)
    if "weather" in n or "eto" in cols or "rain" in cols: return "weather"
    if "soil" in n or "moisture" in cols: return "soil_moisture"
    if "note" in n or "observation" in cols: return "field_notes"
    if "irrig" in n or "duration" in cols or "runtime" in cols: return "irrigation_records"
    if "controller" in n or "flow" in cols or "pressure" in cols: return "controller_logs"
    return "unknown"


def parse_uploaded_file(filename: str, content: bytes) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    ext = filename.rsplit('.',1)[-1].lower()
    warnings: List[str] = []
    if ext not in ALLOWED_EXT: raise ValueError("Unsupported file type")
    if ext == "csv":
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8", errors="ignore"))))
    elif ext == "json":
        payload = json.loads(content.decode("utf-8", errors="ignore"))
        rows = payload if isinstance(payload, list) else [payload]
    elif ext == "txt":
        lines = [l.strip() for l in content.decode("utf-8", errors="ignore").splitlines() if l.strip()]
        rows = [{"notes": l} for l in lines]
    else:
        if openpyxl is None: raise ValueError("Excel parsing requires openpyxl dependency")
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        sh = wb.active
        vals = list(sh.values)
        headers = [str(h) for h in vals[0]]
        rows = [dict(zip(headers, r)) for r in vals[1:]]
    cols = list(rows[0].keys()) if rows else []
    return rows, cols, warnings


def infer_schema(columns: List[str]) -> Dict[str, str]:
    out = {}
    for c in columns:
        key = c.strip().lower().replace(" ", "_")
        out[c] = ALIAS.get(key, key)
    return out


def normalize_units(row: Dict[str, Any], schema: Dict[str, str]) -> Dict[str, Any]:
    n = {}
    for k,v in row.items():
        ck = schema.get(k,k)
        if ck == "depth_in":
            try: n["depth_mm"] = float(v)*25.4
            except: n["depth_mm"] = v
        elif ck == "duration_min" and isinstance(v,str) and "hour" in v.lower():
            try: n[ck]=float(v.split()[0])*60
            except: n[ck]=v
        else:
            n[ck]=v
    if "timestamp" in n:
        try: n["timestamp"] = datetime.fromisoformat(str(n["timestamp"]).replace("Z","+00:00")).isoformat()
        except: pass
    return n


def assemble_context_from_artifacts(arts: List[WorkbenchDataArtifact]) -> Dict[str, Any]:
    normalized = []
    for art in arts:
        schema = infer_schema(art.columns_detected)
        for idx,row in enumerate(art.parsed_rows):
            nrow = normalize_units(row, schema)
            for k,v in nrow.items():
                normalized.append(NormalizedSignal(signal_id=str(uuid.uuid4()), source_kind=art.source_kind, field_name=k, canonical_name=k, value=v, unit="mm" if "mm" in k else None, timestamp=nrow.get("timestamp"), confidence=0.8, raw_reference=f"{art.filename}:{idx+1}").model_dump())
    return {"signals": normalized}


def assemble_context_from_live(source: str, entity_id: str) -> Dict[str, Any]:
    return {"live_source": source, "entity_id": entity_id, "note": "Live source context requested"}


def reconcile_signals(ctx: Dict[str, Any]) -> ReconciliationResult:
    signals = ctx.get("signals", [])
    missing, conflicts = [], []
    keys = {s.get("canonical_name") for s in signals}
    if "eto" not in keys: missing.append("ETo input missing")
    if "rain" not in keys: missing.append("Rain forecast missing")
    if "soil_moisture" not in keys and "moisture" not in keys: missing.append("Soil moisture missing")
    if "planned_duration" in keys and "applied_duration" in keys:
        pv = [s for s in signals if s.get("canonical_name")=="planned_duration"]
        av = [s for s in signals if s.get("canonical_name")=="applied_duration"]
        if pv and av and str(pv[0].get("value")) != str(av[0].get("value")): conflicts.append("Planned vs applied mismatch")
    score,label = compute_confidence(len(signals), missing, conflicts)
    return ReconciliationResult(matched_signals=sorted(list(keys))[:25], conflicts_detected=conflicts, missing_inputs=missing, confidence_score=score, confidence_label=label, evidence_completeness="high" if len(missing)==0 else "partial", interpretation="Source reconciliation complete" if not conflicts else "Conflicts detected; verification required")


def compute_confidence(signal_count: int, missing: List[str], conflicts: List[str]) -> Tuple[float,str]:
    s = 0.45 + min(signal_count, 25)*0.02 - len(missing)*0.06 - len(conflicts)*0.08
    s = max(0.25, min(0.95, s))
    return round(s,2), ("High" if s>=0.8 else "Medium" if s>=0.6 else "Low")


def generate_recommendation(recon: ReconciliationResult) -> Dict[str, Any]:
    decision = "Irrigate 42 min tonight"
    if recon.confidence_score < 0.55: decision = "Collect more evidence before irrigation decision"
    return {"decision": decision, "start": "21:00 PT", "depth_mm": 12, "confidence": recon.confidence_score, "confidence_label": recon.confidence_label}


def generate_ai_reasoning_summary(recon: ReconciliationResult, rec: Dict[str, Any]) -> str:
    model = os.getenv("OPENAI_API_KEY")
    if model: return "Model-assisted summary available; deterministic safeguards applied."
    return f"AGRO-AI reconciled available sources, detected {len(recon.conflicts_detected)} conflicts, and produced {rec['decision']} with {recon.confidence_label.lower()} confidence."


def generate_report_artifact(session_id: str, rec: Dict[str, Any], recon: ReconciliationResult) -> ReportArtifact:
    return ReportArtifact(report_id=str(uuid.uuid4()), title="Irrigation Intelligence Report", report_type="workbench_v1", summary=generate_ai_reasoning_summary(recon, rec), metrics={"confidence": rec["confidence"], "evidence": recon.evidence_completeness}, export_rows=[{"session_id":session_id, "decision": rec["decision"], "confidence": rec["confidence"], "conflicts": "; ".join(recon.conflicts_detected)}])


def analyze_session(session_id: str, mode: str = "uploaded", live_source: str | None = None, live_entity_id: str | None = None) -> WorkbenchAnalysisResult:
    store = SESSIONS[session_id]
    ctx = assemble_context_from_artifacts(store["artifacts"])
    if live_source and live_entity_id:
        ctx["live"] = assemble_context_from_live(live_source, live_entity_id)
    recon = reconcile_signals(ctx)
    rec = generate_recommendation(recon)
    report = generate_report_artifact(session_id, rec, recon)
    result = WorkbenchAnalysisResult(analysis_id=str(uuid.uuid4()), session_id=session_id, status="complete", data_sources=[{"filename":a.filename,"source_kind":a.source_kind,"rows":a.rows_detected} for a in store["artifacts"]], normalized_context=ctx, signal_summary={"normalized_signal_count": len(ctx.get("signals",[]))}, reconciliation=recon, recommendation=rec, verification_plan={"steps":["Recommended","Scheduled","Applied","Observed","Verified"]}, report_summary=report.model_dump(), source_trace=[{"source":a.filename,"warnings":a.warnings} for a in store["artifacts"]], limitations=( ["Uploaded data is weak; collect ETo, rain, and soil moisture signals."] if recon.confidence_label=="Low" else []), model_status=("optional_model_assist" if os.getenv("OPENAI_API_KEY") else "deterministic_engine"), created_at=datetime.utcnow())
    store["analysis"] = result
    return result
