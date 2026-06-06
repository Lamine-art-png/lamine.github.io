"""FCGMA Water Intelligence Copilot — API endpoints.

Namespace: /v1/fcgma-demo/

This is an isolated demo namespace. It does not affect existing routes.
All data is demonstration-only unless explicitly stated otherwise.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fcgma-demo", tags=["fcgma-demo"])

# ─────────────────────────────────────────────
# Lazy init: inject scenarios on first use
# ─────────────────────────────────────────────
_initialized = False

def _ensure_initialized() -> None:
    global _initialized
    if not _initialized:
        from app.services.fcgma.scenarios import inject_all_scenarios
        inject_all_scenarios()
        _initialized = True


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class CopilotQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    record_id: Optional[str] = None
    tool_override: Optional[str] = None
    preset_key: Optional[str] = None


class TerrisQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    record_id: Optional[str] = None
    tool_override: Optional[str] = None


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    initial_context: Optional[dict] = None


class ConversationMessage(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    context_hint: Optional[dict] = None


class ResolveException(BaseModel):
    resolution: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field(default="reviewer")


class ReviewStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None
    actor: str = Field(default="reviewer")


class AMIRow(BaseModel):
    well_id: str
    meter_id: str
    event_timestamp: str
    cumulative_volume: float
    interval_volume: Optional[float] = None
    unit: str = "acre-feet"
    multiplier: float = 1.0
    combcode: Optional[str] = None
    parcel_ids: Optional[List[str]] = None


class ScenarioInjectRequest(BaseModel):
    scenario_set: str = "all"


class ReportRequest(BaseModel):
    report_type: str = "full"
    reporting_period: str = "2026-Q1"


# ─────────────────────────────────────────────
# Status and dashboard
# ─────────────────────────────────────────────

@router.get("/status")
def get_status() -> dict[str, Any]:
    """Health and source connection status."""
    _ensure_initialized()
    from app.services.fcgma.ledger import ledger_stats, PROVIDER_REGISTRY
    from app.services.fcgma.cimis_adapter import get_status as cimis_status
    import os

    stats = ledger_stats()
    cimis = cimis_status()

    providers_status: list[dict[str, Any]] = []
    for pid, preg in PROVIDER_REGISTRY.items():
        missing = [e for e in preg["requires_env"] if not os.getenv(e, "").strip()]
        if preg["status"] == "disabled":
            st = "disabled"
            msg = preg.get("note", "Disabled.")
        elif missing:
            st = "unavailable"
            msg = f"Live source unavailable — configure authorized access. Missing: {', '.join(missing)}"
        else:
            st = "connected"
            msg = "Adapter configured."
        providers_status.append({"id": pid, "label": preg["label"], "status": st, "message": msg})

    return {
        "environment": "illustrative_workspace",
        "product": "AGRO-AI Applied Water Intelligence",
        "subtitle": "Water Governance Command Center — Fox Canyon Groundwater Management Agency",
        "truthfulness_statement": (
            "Illustrative workspace. "
            "Authorized telemetry where connected. "
            "Public contextual sources. "
            "Clearly labeled injected scenarios. "
            "Not an official Fox Canyon reporting system."
        ),
        "providers": providers_status,
        "cimis": cimis,
        "ledger_stats": stats,
        "reporting_period": "2026-Q1",
        "calculation_version": "fcgma-calc-v0.1",
        "rule_pack_version": "0.1.0",
        "rule_pack_status": "provisional — not validated by Fox Canyon GMA",
    }


@router.get("/dashboard")
def get_dashboard() -> dict[str, Any]:
    """Executive dashboard summary."""
    _ensure_initialized()
    from app.services.fcgma.ledger import ledger_stats, list_records
    from app.services.fcgma.copilot import get_executive_summary

    stats = ledger_stats()
    exec_summary = get_executive_summary()
    records = list_records()

    recent_exceptions: list[dict[str, Any]] = []
    for r in records:
        for e in r.get("exceptions", []):
            if e.get("status") != "resolved":
                recent_exceptions.append({
                    "record_id": r["id"],
                    "well_id": r["well_id"],
                    "exception_type": e["exception_type"],
                    "severity": e["severity"],
                    "detail": e["detail"][:120],
                })
    recent_exceptions = sorted(recent_exceptions, key=lambda x: x.get("severity", "low") == "high", reverse=True)[:5]

    return {
        "executive_summary": exec_summary,
        "stats": stats,
        "recent_priority_exceptions": recent_exceptions,
        "reporting_period": "2026-Q1",
        "last_refresh": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "truthfulness_banner": {
            "environment": "Demonstration environment",
            "telemetry": "Authorized telemetry where connected",
            "public_data": "Public contextual sources",
            "scenarios": "Clearly labeled injected scenarios",
            "disclaimer": "Not an official Fox Canyon reporting system",
        },
    }


@router.get("/source-health")
def get_source_health() -> dict[str, Any]:
    """Provider health and data lineage summary."""
    _ensure_initialized()
    from app.services.fcgma.copilot import compare_provider_health
    from app.services.fcgma.rule_pack import PACK_METADATA
    return {
        "provider_health": compare_provider_health(),
        "rule_pack": PACK_METADATA,
    }


# ─────────────────────────────────────────────
# Review queue
# ─────────────────────────────────────────────

@router.get("/review-queue")
def get_review_queue(
    filter: Optional[str] = Query(default=None),
    evidence_class: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """Priority review queue with filters."""
    _ensure_initialized()
    from app.services.fcgma.ledger import list_records

    review_status_filter = None
    exception_type_filter = None

    filter_map = {
        "ready": "ready_for_export",
        "review_required": "requires_attention",
        "requires_attention": "requires_attention",
        "reviewer_approved": "reviewer_approved",
    }

    exception_map = {
        "missing_mapping": "unresolved_combcode",
        "meter_gap": "missing_telemetry_interval",
        "possible_reset": "meter_reset_detected",
        "pump_without_meter": "pump_activity_without_meter_movement",
        "reverse_flow": "reverse_flow",
        "source_stale": "stale_source",
        "duplicate": "duplicate_record",
        "unit_change": "unit_change",
        "multiplier_change": "multiplier_change",
        "backup_estimate": "backup_estimate_required",
    }

    if filter in filter_map:
        review_status_filter = filter_map[filter]
    elif filter in exception_map:
        exception_type_filter = exception_map[filter]

    records = list_records(
        evidence_class=evidence_class,
        provider=provider,
        review_status=review_status_filter,
    )

    if exception_type_filter:
        records = [
            r for r in records
            if any(e["exception_type"] == exception_type_filter for e in r.get("exceptions", []))
        ]

    # Build summary rows for queue
    rows = []
    for r in records:
        open_excs = [e for e in r.get("exceptions", []) if e.get("status") != "resolved"]
        rows.append({
            "id": r["id"],
            "well_id": r["well_id"],
            "meter_id": r["meter_id"],
            "evidence_class": r["evidence_class"],
            "provider": r["provider"],
            "reporting_period": r["reporting_period"],
            "event_timestamp": r["event_timestamp"],
            "combcode": r.get("combcode"),
            "combcode_status": "resolved" if r.get("combcode") else "unresolved",
            "parcel_ids": r.get("parcel_ids", []),
            "parcel_status": "mapped" if r.get("parcel_ids") else "unmapped",
            "interval_volume_af": r.get("interval_volume"),
            "provisional_applied_water_af": r.get("provisional_applied_water_af"),
            "attribution_provisional": r.get("attribution_provisional"),
            "source_quality": r.get("source_quality", "ok"),
            "review_status": r["review_status"],
            "open_exception_count": len(open_excs),
            "open_exceptions": [{"type": e["exception_type"], "severity": e["severity"]} for e in open_excs],
            "scenario_injected": r["scenario_injected"],
            "scenario_label": r.get("scenario_label"),
            "last_updated": r["updated_at"],
        })

    return {
        "total": len(rows),
        "filter_applied": filter,
        "records": rows,
    }


# ─────────────────────────────────────────────
# Record detail
# ─────────────────────────────────────────────

@router.get("/records/{record_id}")
def get_record_detail(record_id: str) -> dict[str, Any]:
    _ensure_initialized()
    from app.services.fcgma.ledger import get_record
    from app.services.fcgma.calculation_engine import get_calculation_explanation

    r = get_record(record_id)
    if not r:
        raise HTTPException(404, f"Record '{record_id}' not found")

    explanation = get_calculation_explanation(r)
    return {**r, "calculation_explanation": explanation}


@router.get("/records/{record_id}/ledger")
def get_record_ledger(record_id: str) -> dict[str, Any]:
    _ensure_initialized()
    from app.services.fcgma.ledger import get_record
    from app.services.fcgma.calculation_engine import get_calculation_explanation

    r = get_record(record_id)
    if not r:
        raise HTTPException(404, f"Record '{record_id}' not found")

    return {
        "record": r,
        "calculation_explanation": get_calculation_explanation(r),
        "disclaimer": (
            "All quantities are from demonstration scenarios. "
            "No authorized Fox Canyon extraction data is included."
        ),
    }


@router.get("/records/{record_id}/audit")
def get_record_audit(record_id: str) -> dict[str, Any]:
    _ensure_initialized()
    from app.services.fcgma.ledger import get_record

    r = get_record(record_id)
    if not r:
        raise HTTPException(404, f"Record '{record_id}' not found")

    return {
        "record_id": record_id,
        "audit_events": r.get("audit_events", []),
        "exceptions": r.get("exceptions", []),
        "review_status": r["review_status"],
        "reviewer_notes": r.get("reviewer_notes"),
        "scenario_injected": r["scenario_injected"],
        "scenario_label": r.get("scenario_label"),
        "calculation_version": r.get("calculation_version"),
    }


@router.post("/records/{record_id}/recompute")
def recompute_record(record_id: str) -> dict[str, Any]:
    _ensure_initialized()
    from app.services.fcgma.calculation_engine import recompute_record as do_recompute

    r = do_recompute(record_id)
    if not r:
        raise HTTPException(404, f"Record '{record_id}' not found")
    return r


@router.patch("/records/{record_id}/review")
def update_review_status(record_id: str, payload: ReviewStatusUpdate) -> dict[str, Any]:
    _ensure_initialized()
    from app.services.fcgma.ledger import update_review_status as do_update, REVIEW_STATUSES

    if payload.status not in REVIEW_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {sorted(REVIEW_STATUSES)}")

    r = do_update(record_id, payload.status, actor=payload.actor, notes=payload.notes)
    if not r:
        raise HTTPException(404, f"Record '{record_id}' not found")
    return r


# ─────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────

@router.post("/exceptions/{exception_id}/resolve")
def resolve_exception(exception_id: str, payload: ResolveException) -> dict[str, Any]:
    _ensure_initialized()
    from app.services.fcgma.ledger import resolve_exception as do_resolve

    exc = do_resolve(exception_id, payload.resolution, payload.actor)
    if not exc:
        raise HTTPException(404, f"Exception '{exception_id}' not found")
    return exc


@router.get("/exceptions")
def list_all_exceptions() -> dict[str, Any]:
    _ensure_initialized()
    from app.services.fcgma.ledger import list_exceptions

    exceptions = list_exceptions()
    open_excs = [e for e in exceptions if e.get("status") != "resolved"]
    return {
        "total": len(exceptions),
        "open": len(open_excs),
        "resolved": len(exceptions) - len(open_excs),
        "exceptions": open_excs,
    }


# ─────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────

@router.post("/imports/ami-csv")
async def import_ami_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    """
    Import a generic AMI CSV file.

    Expected columns (flexible, extra columns ignored):
    well_id, meter_id, event_timestamp, cumulative_volume, unit,
    interval_volume, multiplier, combcode, parcel_ids
    """
    _ensure_initialized()
    from app.services.fcgma.ledger import make_record, upsert_record
    from app.services.fcgma.calculation_engine import recompute_record

    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are accepted for AMI import.")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "File exceeds 5 MB limit.")

    try:
        text = content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as exc:
        raise HTTPException(400, f"CSV parse error: {exc}")

    if not rows:
        raise HTTPException(400, "CSV file contains no data rows.")

    imported_ids: list[str] = []
    errors: list[str] = []

    for i, row in enumerate(rows[:1000]):
        try:
            well_id = row.get("well_id", "").strip()
            meter_id = row.get("meter_id", "").strip()
            ts = row.get("event_timestamp", "").strip()
            cv_raw = row.get("cumulative_volume", "").strip()

            if not well_id or not meter_id or not ts:
                errors.append(f"Row {i+2}: missing required fields (well_id, meter_id, event_timestamp)")
                continue

            cv = float(cv_raw) if cv_raw else None
            iv_raw = row.get("interval_volume", "").strip()
            iv = float(iv_raw) if iv_raw else None
            mult = float(row.get("multiplier", "1") or "1")
            unit = row.get("unit", "acre-feet").strip() or "acre-feet"
            combcode = row.get("combcode", "").strip() or None
            parcel_raw = row.get("parcel_ids", "").strip()
            parcel_ids = [p.strip() for p in parcel_raw.split("|") if p.strip()] if parcel_raw else []

            r = make_record(
                evidence_class="groundwater_meter_reading",
                provider="fcgma_generic_ami_csv",
                external_source_id=f"import-{file.filename}-row-{i+2}",
                event_timestamp=ts,
                reporting_period="2026-Q1",
                well_id=well_id,
                meter_id=meter_id,
                combcode=combcode,
                parcel_ids=parcel_ids,
                cumulative_volume=cv,
                interval_volume=iv,
                unit=unit,
                unit_original=unit,
                multiplier=mult,
                source_quality="ok",
                scenario_injected=False,
                source_lineage={
                    "provider": "fcgma_generic_ami_csv",
                    "source_file": file.filename,
                    "row_index": i + 2,
                    "retrieval_method": "ami_csv_import",
                },
            )
            upsert_record(r)
            recompute_record(r["id"])
            imported_ids.append(r["id"])
        except Exception as exc:
            errors.append(f"Row {i+2}: {exc}")

    return {
        "imported_count": len(imported_ids),
        "error_count": len(errors),
        "imported_record_ids": imported_ids,
        "errors": errors[:20],
        "note": "Imported records are NOT Fox Canyon authorized data. They are treated as generic AMI CSV imports and remain provisional until CombCode and parcel mapping are confirmed.",
    }


# ─────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────

@router.post("/scenarios/reset")
def reset_scenarios() -> dict[str, Any]:
    """Clear all records and re-inject the standard demonstration dataset."""
    from app.services.fcgma.scenarios import inject_all_scenarios
    global _initialized
    result = inject_all_scenarios()
    _initialized = True
    return {
        "message": "Demonstration dataset reset and re-injected.",
        "result": result,
        "disclaimer": "All records are demonstration scenarios. No authorized Fox Canyon data was modified.",
    }


@router.post("/scenarios/inject")
def inject_scenarios(payload: ScenarioInjectRequest) -> dict[str, Any]:
    """Inject a fresh demonstration dataset (alias for reset with explicit intent)."""
    from app.services.fcgma.scenarios import inject_all_scenarios
    global _initialized
    result = inject_all_scenarios()
    _initialized = True
    return {
        "message": "Demonstration scenarios injected.",
        "scenario_set": payload.scenario_set,
        "result": result,
        "disclaimer": "Demonstration scenario injected to illustrate exception handling.",
    }


# ─────────────────────────────────────────────
# Copilot
# ─────────────────────────────────────────────

@router.post("/copilot/query")
def copilot_query(payload: CopilotQuery) -> dict[str, Any]:
    """
    Answer an operational question using grounded AI backend tools.

    Answers are grounded in deterministic ledger data.
    The AI may not generate quantities beyond what the tools return.
    """
    _ensure_initialized()
    from app.services.fcgma.copilot import query_copilot

    tool = payload.tool_override or payload.preset_key
    result = query_copilot(
        query=payload.query,
        record_id=payload.record_id,
        tool_override=tool,
    )
    return result


@router.get("/copilot/preset-questions")
def get_preset_questions() -> dict[str, Any]:
    return {
        "questions": [
            {"key": "attention", "label": "What requires my attention today?", "tool": "list_records_requiring_attention"},
            {"key": "why_provisional", "label": "Why is this record provisional?", "tool": "explain_record"},
            {"key": "reporting", "label": "Which records are ready for reporting?", "tool": "generate_reporting_summary"},
            {"key": "pump_without_meter", "label": "Show pump activity without corresponding extraction movement.", "tool": "generate_exception_report"},
            {"key": "applied_water_calculation", "label": "Explain how this applied-water quantity was calculated.", "tool": "run_applied_water_scenario"},
            {"key": "provider_health", "label": "Compare provider-feed health.", "tool": "compare_provider_health"},
            {"key": "reporting_summary", "label": "Generate a reporting-ready summary.", "tool": "generate_reporting_summary"},
            {"key": "fox_canyon_data", "label": "What data would Fox Canyon need to provide to refine this calculation?", "tool": "list_unvalidated_assumptions"},
            {"key": "assumptions", "label": "Which assumptions still require agency validation?", "tool": "list_unvalidated_assumptions"},
        ]
    }


# ─────────────────────────────────────────────
# Terris — Water Intelligence Agent
# ─────────────────────────────────────────────

@router.post("/terris/query")
def terris_query(payload: TerrisQuery) -> dict[str, Any]:
    """
    Submit a query to Terris, the AGRO-AI Water Intelligence Agent.

    Terris runs a multi-stage investigation grounded in deterministic backend tools.
    Returns a structured response: Direct Answer, Why It Matters, Evidence Reviewed,
    Recommended Action, Remaining Uncertainty, Available Actions.
    """
    _ensure_initialized()
    from app.services.fcgma.terris import run_terris_investigation
    return run_terris_investigation(
        query=payload.query,
        record_id=payload.record_id,
        tool_override=payload.tool_override,
    )


@router.get("/terris/preset-questions")
def get_terris_preset_questions() -> dict[str, Any]:
    from app.services.fcgma.terris import TERRIS_PRESET_QUESTIONS, AGENT_NAME, AGENT_DESCRIPTION
    return {
        "agent": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "questions": TERRIS_PRESET_QUESTIONS,
    }


@router.get("/terris/reporting-cycle")
def get_reporting_cycle() -> dict[str, Any]:
    """Reporting cycle status and readiness."""
    _ensure_initialized()
    from app.services.fcgma.terris import get_reporting_cycle_status
    return get_reporting_cycle_status()


@router.get("/terris/priority-actions")
def get_priority_actions() -> dict[str, Any]:
    """Ranked action queue for the current reporting cycle."""
    _ensure_initialized()
    from app.services.fcgma.terris import list_priority_actions
    return list_priority_actions()


@router.get("/terris/blocking-records")
def get_blocking_records() -> dict[str, Any]:
    """Records blocking the current reporting cycle."""
    _ensure_initialized()
    from app.services.fcgma.terris import list_records_blocking_reporting
    return list_records_blocking_reporting()


@router.get("/terris/cases")
def get_review_cases(
    reporting_period: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """List ReviewCases — exceptions grouped by well and reporting period."""
    _ensure_initialized()
    from app.services.fcgma.cases import build_cases
    cases = build_cases(reporting_period=reporting_period)
    return {
        "cases": cases,
        "total": len(cases),
        "reporting_period": reporting_period or "all",
    }


@router.get("/terris/cycle-gates")
def get_cycle_gates() -> dict[str, Any]:
    """Five reporting-cycle gates with status, what remains, and next actions."""
    _ensure_initialized()
    from app.services.fcgma.gates import compute_all_gates
    return compute_all_gates()


@router.get("/terris/briefing")
def get_terris_briefing() -> dict[str, Any]:
    """Proactive Terris briefing generated from current evidence."""
    _ensure_initialized()
    from app.services.fcgma.briefing import generate_terris_briefing
    return generate_terris_briefing()


# ── Conversational Terris ──────────────────────────────────────────────────

@router.post("/terris/conversation")
def create_conversation(payload: ConversationCreate) -> dict[str, Any]:
    """Create a new Terris conversation thread."""
    _ensure_initialized()
    from app.services.fcgma.conversation import create_conversation as do_create
    return do_create(title=payload.title, initial_context=payload.initial_context)


@router.post("/terris/conversation/{thread_id}/message")
def send_message(thread_id: str, payload: ConversationMessage) -> dict[str, Any]:
    """Send a message to Terris in an existing conversation thread."""
    _ensure_initialized()
    from app.services.fcgma.conversation import add_message, get_conversation
    conv = get_conversation(thread_id)
    if not conv:
        raise HTTPException(404, f"Conversation '{thread_id}' not found. Create a conversation first.")
    result = add_message(thread_id, payload.query, context_hint=payload.context_hint)
    if not result:
        raise HTTPException(500, "Failed to generate response.")
    return result


@router.get("/terris/conversation/{thread_id}")
def get_conversation_history(thread_id: str) -> dict[str, Any]:
    """Get the full conversation history for a thread."""
    _ensure_initialized()
    from app.services.fcgma.conversation import get_conversation, get_history
    conv = get_conversation(thread_id)
    if not conv:
        raise HTTPException(404, f"Conversation '{thread_id}' not found.")
    return {
        "thread_id": thread_id,
        "title": conv.get("title"),
        "created_at": conv.get("created_at"),
        "updated_at": conv.get("updated_at"),
        "message_count": conv.get("message_count", 0),
        "llm_mode": conv.get("llm_mode", "structured_safe"),
        "turns": get_history(thread_id),
    }


@router.get("/terris/conversations")
def list_conversations() -> dict[str, Any]:
    """List all Terris conversation threads in this session."""
    from app.services.fcgma.conversation import list_conversations as do_list
    convs = do_list()
    return {"conversations": convs, "total": len(convs)}


@router.post("/terris/conversation/{thread_id}/message-start")
def start_message_stream(thread_id: str, payload: ConversationMessage) -> dict[str, Any]:
    """Start an async investigation job. Returns job_id for polling."""
    _ensure_initialized()
    from app.services.fcgma.conversation import start_message_job, get_conversation
    conv = get_conversation(thread_id)
    if not conv:
        raise HTTPException(404, f"Conversation '{thread_id}' not found.")
    jid = start_message_job(thread_id, payload.query, context_hint=payload.context_hint)
    if not jid:
        raise HTTPException(500, "Failed to start investigation.")
    return {"job_id": jid, "thread_id": thread_id, "status": "running"}


@router.get("/terris/job/{job_id}")
def poll_job(job_id: str, since: int = Query(default=0)) -> dict[str, Any]:
    """Poll an async investigation job for progress events and result."""
    _ensure_initialized()
    from app.services.fcgma.conversation import poll_job as do_poll
    result = do_poll(job_id, since_index=since)
    if not result:
        raise HTTPException(404, f"Job '{job_id}' not found.")
    return result


# ─────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────

@router.get("/reports")
def list_reports() -> dict[str, Any]:
    """List all generated reports in this session (newest first)."""
    from app.services.fcgma.reports import list_reports as do_list
    reports = do_list()
    return {"reports": reports, "total": len(reports)}


@router.post("/reports/generate")
def generate_report(payload: ReportRequest) -> dict[str, Any]:
    """Generate a full report bundle (PDF, CSV, audit JSON, lineage manifest, ZIP)."""
    _ensure_initialized()
    from app.services.fcgma.reports import generate_report as do_generate
    return do_generate(report_type=payload.report_type)


@router.get("/reports/{report_id}")
def get_report(report_id: str) -> dict[str, Any]:
    from app.services.fcgma.reports import get_report_meta

    meta = get_report_meta(report_id)
    if not meta:
        raise HTTPException(404, f"Report '{report_id}' not found. Generate a report first.")

    return {k: v for k, v in meta.items() if not k.startswith("_")}


@router.get("/reports/{report_id}/bundle")
def download_bundle(report_id: str) -> Response:
    """Download the complete ZIP bundle for a report."""
    from app.services.fcgma.reports import get_report_artifact

    result = get_report_artifact(report_id, "bundle")
    if not result:
        raise HTTPException(404, f"Report '{report_id}' bundle not found.")
    data, content_type = result
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={report_id}_bundle.zip"},
    )


@router.get("/reports/{report_id}/pdf")
def download_pdf(report_id: str) -> Response:
    from app.services.fcgma.reports import get_report_artifact

    result = get_report_artifact(report_id, "pdf")
    if not result:
        raise HTTPException(404, f"Report PDF for '{report_id}' not found.")
    data, content_type = result
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f"inline; filename={report_id}_executive_report.pdf"},
    )


@router.get("/reports/{report_id}/csv")
def download_csv(report_id: str, type: str = Query(default="records")) -> Response:
    from app.services.fcgma.reports import get_report_artifact

    artifact = "exceptions_csv" if type == "exceptions" else "records_csv"
    result = get_report_artifact(report_id, artifact.replace("_csv", "_csv") if "_csv" in artifact else artifact)
    # Fix mapping
    artifact_key = "exceptions_csv" if type == "exceptions" else "records_csv"
    result = get_report_artifact(report_id, "exceptions_csv" if type == "exceptions" else "records_csv")
    if not result:
        raise HTTPException(404, f"Report CSV for '{report_id}' not found.")
    data, content_type = result
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={report_id}_{type}.csv"},
    )


# ─────────────────────────────────────────────
# CIMIS weather context
# ─────────────────────────────────────────────

@router.get("/weather/cimis")
async def get_cimis_weather(days: int = Query(default=7, le=30)) -> dict[str, Any]:
    """Fetch CIMIS weather context. Requires CIMIS_APP_KEY env var."""
    _ensure_initialized()
    from app.services.fcgma.cimis_adapter import fetch_daily_data
    return await fetch_daily_data(days=days)


# ─────────────────────────────────────────────
# Rule pack
# ─────────────────────────────────────────────

@router.get("/rules")
def get_rule_pack() -> dict[str, Any]:
    from app.services.fcgma.rule_pack import PACK_METADATA, get_rules
    return {
        "metadata": PACK_METADATA,
        "rules": get_rules(),
        "rule_pack": PACK_METADATA,  # alias for compatibility
    }
