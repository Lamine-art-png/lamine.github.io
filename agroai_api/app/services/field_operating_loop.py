"""Deterministic field operating loop for AGRO-AI."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.block import Block
from app.models.operational_records import (
    ConnectorConnection,
    DataSource,
    EvidenceRecord,
    GeneratedArtifact,
    IngestionJob,
    IntelligenceRun,
)
from app.models.saas import Workspace
from app.services.operator_cockpit import (
    build_context,
    decision_workbench,
    exceptions,
    field_intelligence,
    readiness_summary,
    report_factory,
)

TASK_JOB_TYPE = "field_ops_task"
MESSAGE_JOB_TYPE = "field_ops_message"
AUTOPILOT_JOB_TYPE = "field_ops_autopilot_report"

SECRET_KEYS = ("secret", "token", "oauth", "api_key", "password", "credential", "client_secret")


@dataclass
class FieldOpsContext:
    db: Session
    organization_id: str
    workspace: Workspace | None
    cockpit: Any
    readiness: dict[str, Any]
    fields: list[dict[str, Any]]
    exceptions: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    sample_mode: bool

    @property
    def workspace_id(self) -> str | None:
        return self.workspace.id if self.workspace else None


def build_field_ops_context(db: Session, organization_id: str, workspace: Workspace | None = None) -> FieldOpsContext:
    cockpit = build_context(db, organization_id, workspace)
    readiness = readiness_summary(cockpit)
    fields = field_intelligence(cockpit).get("fields", [])
    exception_rows = exceptions(cockpit).get("exceptions", [])
    decisions = decision_workbench(cockpit).get("decisions", [])
    return FieldOpsContext(
        db=db,
        organization_id=organization_id,
        workspace=workspace,
        cockpit=cockpit,
        readiness=readiness,
        fields=fields,
        exceptions=exception_rows,
        decisions=decisions,
        sample_mode=bool(readiness.get("sample_mode")),
    )


def command_center(ctx: FieldOpsContext) -> dict[str, Any]:
    tasks = list_tasks(ctx)
    queue = field_queue(ctx, tasks)
    missing = missing_evidence(ctx)
    reports = reports_ready(ctx)
    recent = recent_signals(ctx)
    audit = audit_trail(ctx)
    priority = today_priority(ctx, queue, tasks)
    status = operating_status(queue, tasks, missing)
    return {
        "status": "ok",
        "workspace_id": ctx.workspace_id,
        "sample_mode": ctx.sample_mode,
        "operating_status": status,
        "today_priority": priority,
        "field_queue": queue,
        "operator_tasks": tasks,
        "missing_evidence": missing,
        "recent_signals": recent,
        "reports_ready": reports,
        "audit_events": audit,
    }


def list_tasks(ctx: FieldOpsContext) -> list[dict[str, Any]]:
    generated = {task["id"]: task for task in _generated_tasks(ctx)}
    jobs = (
        ctx.db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == ctx.organization_id,
            IngestionJob.job_type == TASK_JOB_TYPE,
        )
        .order_by(IngestionJob.created_at.desc())
        .all()
    )
    for job in jobs:
        task = _task_from_job(job)
        if ctx.workspace_id and task.get("workspace_id") not in {None, ctx.workspace_id}:
            continue
        generated[task["id"]] = {**generated.get(task["id"], {}), **task}
    tasks = list(generated.values())
    order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(key=lambda row: (order.get(row.get("priority", "low"), 9), row.get("title", "")))
    return tasks


def create_task(
    ctx: FieldOpsContext,
    *,
    title: str,
    field: str | None,
    block: str | None,
    priority: str,
    why: str,
    instructions: list[str],
    evidence_required: list[str],
    created_from: str,
    assigned_to: str | None = None,
    source_exception_id: str | None = None,
    source_decision_id: str | None = None,
) -> dict[str, Any]:
    job = IngestionJob(
        id=f"task_{uuid.uuid4().hex[:12]}",
        tenant_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        job_type=TASK_JOB_TYPE,
        status="open",
        input_json={
            "title": title,
            "field": field,
            "block": block,
            "assigned_to": assigned_to,
            "priority": priority,
            "why": why,
            "instructions": instructions,
            "evidence_required": evidence_required,
            "source_exception_id": source_exception_id,
            "source_decision_id": source_decision_id,
            "created_from": created_from,
            "customer_safe": True,
            "workspace_id": ctx.workspace_id,
        },
        output_json={},
    )
    ctx.db.add(job)
    ctx.db.commit()
    ctx.db.refresh(job)
    return _task_from_job(job)


def update_task_status(ctx: FieldOpsContext, task_id: str, status_value: str) -> dict[str, Any]:
    job = (
        ctx.db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == ctx.organization_id,
            IngestionJob.id == task_id,
            IngestionJob.job_type == TASK_JOB_TYPE,
        )
        .first()
    )
    if not job:
        generated = next((task for task in _generated_tasks(ctx) if task["id"] == task_id), None)
        if not generated:
            raise KeyError(task_id)
        job = IngestionJob(
            id=task_id,
            tenant_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            job_type=TASK_JOB_TYPE,
            status=status_value,
            input_json={**generated, "workspace_id": ctx.workspace_id},
            output_json={"updated_from": "generated_task"},
        )
        ctx.db.add(job)
    else:
        job.status = status_value
        job.output_json = {**(job.output_json or {}), "updated_at": _iso(datetime.utcnow())}
        if status_value == "done":
            job.completed_at = datetime.utcnow()
    ctx.db.commit()
    ctx.db.refresh(job)
    return _task_from_job(job)


def create_field_update(
    ctx: FieldOpsContext,
    *,
    field_id: str | None,
    field_name: str | None,
    block: str | None,
    crop: str | None,
    update_text: str,
    event_type: str,
    occurred_at: datetime | None = None,
    water_gallons: float | None = None,
    flow_gpm: float | None = None,
    duration_minutes: float | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    block_row = _resolve_block(ctx, field_id=field_id, field_name=field_name, block_name=block)
    effective_field_id = field_id or _slug(field_name or (block_row.name if block_row else "field-update"))
    effective_field_name = field_name or _display_field_name(block_row, effective_field_id)
    data_source = None
    if attachments:
        data_source = DataSource(
            id=f"source_{uuid.uuid4().hex[:12]}",
            tenant_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            source_type="field_update_attachment",
            provider="manual_csv",
            filename=(attachments[0] or {}).get("filename"),
            metadata_json={"attachments": sanitize_public(attachments), "source": "manual_field_update"},
            status="linked",
        )
        ctx.db.add(data_source)
        ctx.db.flush()
    evidence = EvidenceRecord(
        id=f"evidence_{uuid.uuid4().hex[:12]}",
        tenant_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        data_source_id=data_source.id if data_source else None,
        evidence_type=event_type,
        field_id=effective_field_id,
        block_id=block_row.id if block_row else None,
        occurred_at=occurred_at or datetime.utcnow(),
        title=f"{effective_field_name} {event_type.replace('_', ' ')}",
        summary=update_text,
        value_json=sanitize_public(
            {
                "field_name": effective_field_name,
                "block": block or (block_row.name if block_row else None),
                "crop": crop or (block_row.crop_type if block_row else None),
                "water_gallons": water_gallons,
                "flow_gpm": flow_gpm,
                "duration_minutes": duration_minutes,
                "attachments": attachments or [],
            }
        ),
        units="field_update",
        confidence=0.82,
        quality_status="usable",
        citation_label="Manual field update",
        metadata_json={
            "source": "manual_field_update",
            "field_name": effective_field_name,
            "block_name": block or (block_row.name if block_row else None),
            "crop": crop or (block_row.crop_type if block_row else None),
            "customer_safe": True,
        },
    )
    ctx.db.add(evidence)
    ctx.db.commit()
    next_action = _next_action_for_update(event_type, water_gallons=water_gallons, flow_gpm=flow_gpm, duration_minutes=duration_minutes)
    created_task = None
    if next_action.get("task_title"):
        created_task = create_task(
            ctx,
            title=next_action["task_title"],
            field=effective_field_name,
            block=block or (block_row.name if block_row else None),
            priority=next_action["priority"],
            why=next_action["why"],
            instructions=next_action["instructions"],
            evidence_required=next_action["evidence_required"],
            created_from="field_update",
        )
    return {
        "status": "ok",
        "sample_mode": ctx.sample_mode,
        "understood_summary": f"Recorded {event_type.replace('_', ' ')} for {effective_field_name}.",
        "created_evidence": [{
            "id": evidence.id,
            "title": evidence.title,
            "field_id": evidence.field_id,
            "block_id": evidence.block_id,
            "occurred_at": _iso(evidence.occurred_at),
        }],
        "created_tasks": [created_task] if created_task else [],
        "recommended_next_action": next_action["recommended_next_action"],
    }


def field_message(ctx: FieldOpsContext, *, message: str, sender_role: str, channel: str, field_hint: str | None = None) -> dict[str, Any]:
    parsed = _parse_message(message, field_hint=field_hint)
    update_result = create_field_update(
        ctx,
        field_id=parsed.get("field_id"),
        field_name=parsed.get("field_name"),
        block=parsed.get("block"),
        crop=parsed.get("crop"),
        update_text=message,
        event_type=parsed.get("event_type", "operator_note"),
        water_gallons=parsed.get("water_gallons"),
        flow_gpm=parsed.get("flow_gpm"),
        duration_minutes=parsed.get("duration_minutes"),
    )
    created_tasks = list(update_result.get("created_tasks", []))
    for follow_up in parsed.get("follow_up_tasks", []):
        created_tasks.append(
            create_task(
                ctx,
                title=follow_up["title"],
                field=parsed.get("field_name"),
                block=parsed.get("block"),
                priority=follow_up["priority"],
                why=follow_up["why"],
                instructions=follow_up["instructions"],
                evidence_required=follow_up["evidence_required"],
                created_from="missing_evidence",
            )
        )
    return {
        "status": "ok",
        "sample_mode": ctx.sample_mode,
        "understood_summary": parsed["understood_summary"],
        "extracted_fields": sanitize_public({**parsed, "sender_role": sender_role, "channel": channel}),
        "created_evidence": update_result["created_evidence"],
        "created_tasks": created_tasks,
        "recommended_next_action": update_result["recommended_next_action"],
    }


def autopilot_report(ctx: FieldOpsContext, *, audience: str, scope: str, field_id: str | None = None) -> dict[str, Any]:
    report_type = _report_type_for_scope(scope)
    report_payload = report_factory(ctx.cockpit, report_type=report_type, audience=audience, field_id=field_id).get("report", {})
    center = command_center(ctx)
    report_payload["open_tasks"] = [task for task in center["operator_tasks"] if task["status"] in {"open", "in_progress", "blocked", "needs_review"}]
    report_payload["missing_evidence"] = center["missing_evidence"]
    report_payload["recommended_decisions"] = ctx.decisions[:4]
    report_payload["command_center_state"] = {
        "operating_status": center["operating_status"],
        "today_priority": center["today_priority"],
        "field_queue": center["field_queue"][:5],
    }
    return {
        "status": "ok",
        "sample_mode": ctx.sample_mode,
        "report": sanitize_public(report_payload),
        "pdf_ready": True,
        "pdf_request": {
            "report_type": report_type,
            "workspace_id": ctx.workspace_id,
            "field_id": field_id,
            "audience": audience,
        },
    }


def audit_trail(ctx: FieldOpsContext) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for connection in ctx.cockpit.connections:
        if connection.last_sync_at:
            events.append({
                "event_type": "connector_sync",
                "timestamp": _iso(connection.last_sync_at),
                "title": f"{_display_provider(connection.provider)} sync recorded",
                "detail": f"Status: {connection.status}",
            })
    for source in ctx.cockpit.sources[:40]:
        events.append({
            "event_type": "upload",
            "timestamp": _iso(source.created_at),
            "title": source.filename or source.source_type,
            "detail": f"{_display_provider(source.provider)} source received",
        })
    for evidence in ctx.cockpit.evidence[:40]:
        events.append({
            "event_type": "field_update" if (evidence.metadata_json or {}).get("source") == "manual_field_update" else "evidence",
            "timestamp": _iso(evidence.occurred_at or evidence.created_at),
            "title": evidence.title,
            "detail": evidence.summary[:160],
        })
    for job in ctx.cockpit.jobs[:40]:
        events.append({
            "event_type": "task" if job.job_type == TASK_JOB_TYPE else "ingestion_job",
            "timestamp": _iso(job.completed_at or job.updated_at or job.created_at),
            "title": (job.input_json or {}).get("title") or job.job_type,
            "detail": f"Status: {job.status}",
        })
    artifacts = (
        ctx.db.query(GeneratedArtifact)
        .filter(GeneratedArtifact.tenant_id == ctx.organization_id)
        .order_by(GeneratedArtifact.created_at.desc())
        .limit(20)
        .all()
    )
    for artifact in artifacts:
        if ctx.workspace_id and artifact.workspace_id not in {None, ctx.workspace_id}:
            continue
        events.append({
            "event_type": "report",
            "timestamp": _iso(artifact.created_at),
            "title": artifact.title,
            "detail": artifact.artifact_type,
        })
    runs = (
        ctx.db.query(IntelligenceRun)
        .filter(IntelligenceRun.tenant_id == ctx.organization_id)
        .order_by(IntelligenceRun.created_at.desc())
        .limit(20)
        .all()
    )
    for run in runs:
        if ctx.workspace_id and run.workspace_id not in {None, ctx.workspace_id}:
            continue
        events.append({
            "event_type": "decision_run",
            "timestamp": _iso(run.created_at),
            "title": run.run_type.replace("_", " "),
            "detail": run.status,
        })
    events.sort(key=lambda row: row.get("timestamp") or "", reverse=True)
    return events[:50]


def field_queue(ctx: FieldOpsContext, tasks: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    tasks = tasks or list_tasks(ctx)
    exception_by_field = {}
    for row in ctx.exceptions:
        key = row.get("field_name") or row.get("field") or row.get("block") or "workspace"
        exception_by_field.setdefault(key, []).append(row)
    queue = []
    for field in ctx.fields:
        task = next((item for item in tasks if item.get("field") == field.get("field_name")), None)
        missing = list(field.get("missing_data") or [])
        flags = list(field.get("risk_flags") or [])
        issue = flags[0] if flags else (missing[0] if missing else "Field ready for review")
        priority = "high" if flags else "medium" if missing else "low"
        queue.append({
            "field_id": field.get("field_id"),
            "field_name": field.get("field_name"),
            "crop": field.get("crop"),
            "status": "needs_attention" if flags else "missing_evidence" if missing else "ready",
            "priority": priority,
            "issue": issue,
            "recommended_action": field.get("next_best_action") or (task or {}).get("why") or "Review field evidence.",
            "missing_evidence": missing,
            "latest_signal": _latest_signal(field),
            "next_operator_task": (task or {}).get("title") or field.get("next_best_action"),
        })
    if not queue:
        queue.append({
            "field_id": None,
            "field_name": ctx.workspace.name if ctx.workspace else "Workspace",
            "crop": ctx.workspace.crop if ctx.workspace else None,
            "status": "missing_evidence",
            "priority": "high",
            "issue": "No field evidence yet",
            "recommended_action": "Add a field update or connect a source.",
            "missing_evidence": missing_evidence(ctx),
            "latest_signal": "No recent field signals.",
            "next_operator_task": "Upload recent field context",
        })
    order = {"high": 0, "medium": 1, "low": 2}
    queue.sort(key=lambda row: (order.get(row["priority"], 9), row["field_name"] or ""))
    return queue


def missing_evidence(ctx: FieldOpsContext) -> list[dict[str, Any]]:
    rows = []
    for source_type in ctx.readiness.get("missing_source_types", []):
        rows.append({
            "item": source_type.replace("_", " "),
            "why_it_matters": _missing_reason(source_type),
            "action": _missing_action(source_type),
        })
    unresolved = [field for field in ctx.fields if field.get("missing_data")]
    for field in unresolved[:6]:
        for item in field.get("missing_data", []):
            rows.append({
                "item": item,
                "why_it_matters": f"{field.get('field_name')} needs this evidence for an operator-ready decision.",
                "action": "assign_task",
            })
    deduped: list[dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = (row["item"], row["action"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[:12]


def recent_signals(ctx: FieldOpsContext) -> list[dict[str, Any]]:
    signals = []
    for field in ctx.fields[:8]:
        if field.get("latest_irrigation_event"):
            signals.append({
                "field": field.get("field_name"),
                "signal": f"Irrigation event {field['latest_irrigation_event'].get('type')}",
                "at": field["latest_irrigation_event"].get("at"),
            })
        if field.get("latest_weather_context"):
            signals.append({
                "field": field.get("field_name"),
                "signal": f"Weather update {field['latest_weather_context'].get('type')}",
                "at": field["latest_weather_context"].get("at"),
            })
    if not signals:
        signals.append({"field": ctx.workspace.name if ctx.workspace else "Workspace", "signal": "No recent field signals", "at": None})
    return signals[:12]


def reports_ready(ctx: FieldOpsContext) -> list[dict[str, Any]]:
    artifacts = (
        ctx.db.query(GeneratedArtifact)
        .filter(GeneratedArtifact.tenant_id == ctx.organization_id)
        .order_by(GeneratedArtifact.created_at.desc())
        .limit(20)
        .all()
    )
    rows = []
    for artifact in artifacts:
        if ctx.workspace_id and artifact.workspace_id not in {None, ctx.workspace_id}:
            continue
        rows.append({
            "id": artifact.id,
            "title": artifact.title,
            "artifact_type": artifact.artifact_type,
            "filename": artifact.filename,
            "created_at": _iso(artifact.created_at),
        })
    return rows[:8]


def today_priority(ctx: FieldOpsContext, queue: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    first_task = next((task for task in tasks if task.get("priority") == "high" and task.get("status") != "done"), None)
    first_queue = queue[0] if queue else None
    if first_task:
        return {
            "title": first_task["title"],
            "reason": first_task["why"],
            "field": first_task.get("field"),
            "risk": first_task["priority"],
            "recommended_action": first_task["instructions"][0] if first_task.get("instructions") else first_task["title"],
        }
    if first_queue:
        return {
            "title": first_queue["issue"],
            "reason": first_queue["recommended_action"],
            "field": first_queue["field_name"],
            "risk": first_queue["priority"],
            "recommended_action": first_queue["next_operator_task"],
        }
    return {
        "title": "Monitor workspace",
        "reason": "No urgent issues are open.",
        "field": ctx.workspace.name if ctx.workspace else None,
        "risk": "low",
        "recommended_action": "Review recent evidence and generate a report.",
    }


def operating_status(queue: list[dict[str, Any]], tasks: list[dict[str, Any]], missing: list[dict[str, Any]]) -> str:
    if any(task["status"] == "blocked" for task in tasks):
        return "blocked"
    if any(row["priority"] == "high" for row in queue) or any(task["priority"] == "high" and task["status"] != "done" for task in tasks):
        return "needs_attention"
    if missing:
        return "monitoring"
    return "ready"


def sanitize_public(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if any(marker in key.lower() for marker in SECRET_KEYS):
                continue
            clean[key] = sanitize_public(item)
        return clean
    if isinstance(value, list):
        return [sanitize_public(item) for item in value]
    return value


def _generated_tasks(ctx: FieldOpsContext) -> list[dict[str, Any]]:
    tasks = []
    for item in missing_evidence(ctx):
        task_id = f"task_missing_{_slug(item['item'])}"
        tasks.append({
            "id": task_id,
            "title": f"Collect {item['item']}",
            "field": None,
            "block": None,
            "assigned_to": None,
            "priority": "high" if item["action"] in {"connect_source", "upload_file"} else "medium",
            "status": "open",
            "why": item["why_it_matters"],
            "instructions": [_instruction_for_action(item["action"], item["item"])],
            "evidence_required": [item["item"]],
            "source_exception_id": None,
            "source_decision_id": None,
            "created_from": "missing_evidence",
            "customer_safe": True,
            "workspace_id": ctx.workspace_id,
        })
    for row in ctx.exceptions[:8]:
        task_id = f"task_exception_{_slug(row['id'])}"
        tasks.append({
            "id": task_id,
            "title": row["title"],
            "field": row.get("field_name"),
            "block": row.get("block"),
            "assigned_to": None,
            "priority": row.get("severity", "medium"),
            "status": "open",
            "why": row.get("explanation"),
            "instructions": [row.get("recommended_action") or "Review the exception."],
            "evidence_required": row.get("evidence_refs") or [],
            "source_exception_id": row.get("id"),
            "source_decision_id": None,
            "created_from": "exception",
            "customer_safe": True,
            "workspace_id": ctx.workspace_id,
        })
    deduped = {}
    for task in tasks:
        deduped[task["id"]] = task
    return list(deduped.values())


def _task_from_job(job: IngestionJob) -> dict[str, Any]:
    payload = sanitize_public(job.input_json or {})
    return {
        "id": job.id,
        "title": payload.get("title", job.job_type),
        "field": payload.get("field"),
        "block": payload.get("block"),
        "assigned_to": payload.get("assigned_to"),
        "priority": payload.get("priority", "medium"),
        "status": job.status,
        "why": payload.get("why", ""),
        "instructions": payload.get("instructions", []),
        "evidence_required": payload.get("evidence_required", []),
        "source_exception_id": payload.get("source_exception_id"),
        "source_decision_id": payload.get("source_decision_id"),
        "created_from": payload.get("created_from", "manual"),
        "customer_safe": True,
        "workspace_id": payload.get("workspace_id"),
    }


def _resolve_block(ctx: FieldOpsContext, *, field_id: str | None, field_name: str | None, block_name: str | None) -> Block | None:
    blocks = ctx.cockpit.blocks
    for block in blocks:
        if field_id and block.id == field_id:
            return block
        if field_name and field_name.lower() in {block.name.lower(), _slug(block.name)}:
            return block
        if block_name and block_name.lower() == block.name.lower():
            return block
    return None


def _display_field_name(block_row: Block | None, fallback: str) -> str:
    return block_row.name if block_row else fallback.replace("-", " ").title()


def _parse_message(message: str, *, field_hint: str | None = None) -> dict[str, Any]:
    lower = message.lower()
    gallons = _float_match(r"([0-9][0-9,\.]*)\s*gallons?", lower)
    flow = _float_match(r"([0-9][0-9,\.]*)\s*gpm", lower)
    duration = _float_match(r"([0-9][0-9,\.]*)\s*minutes?", lower)
    block_match = re.search(r"\bblock\s+([a-z0-9-]+)", message, flags=re.IGNORECASE)
    field_match = re.search(r"\b(field|ranch|parcel)\s+([a-z0-9][a-z0-9\s-]+)", message, flags=re.IGNORECASE)
    crop = "Almonds" if "almond" in lower else "Pistachios" if "pistachio" in lower else None
    issue = None
    if "stress" in lower:
        issue = "Crop stress observed"
    elif "missing" in lower or "not working" in lower:
        issue = "Follow-up required"
    event_type = "operator_note"
    if gallons or duration:
        event_type = "irrigation_event"
    elif "meter" in lower:
        event_type = "meter_reading"
    elif "photo" in lower:
        event_type = "photo_note"
    elif "issue" in lower or "stressed" in lower:
        event_type = "issue"
    field_name = field_hint or (field_match.group(2).strip().title() if field_match else None)
    block = block_match.group(0).title() if block_match else None
    summary = f"AGRO-AI understood {event_type.replace('_', ' ')}"
    if field_name:
        summary += f" for {field_name}"
    if block:
        summary += f" at {block}"
    summary += "."
    follow_up_tasks = []
    if issue or "meter" in lower:
        follow_up_tasks.append({
            "title": "Verify field observation",
            "priority": "medium",
            "why": issue or "Meter detail should be verified against field evidence.",
            "instructions": ["Review the field update and attach any supporting file or photo."],
            "evidence_required": ["supporting field note"],
        })
    return {
        "field_id": _slug(field_name) if field_name else None,
        "field_name": field_name,
        "block": block,
        "crop": crop,
        "event_type": event_type,
        "water_gallons": gallons,
        "flow_gpm": flow,
        "duration_minutes": duration,
        "issue": issue,
        "understood_summary": summary,
        "follow_up_tasks": follow_up_tasks,
    }


def _float_match(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _report_type_for_scope(scope: str) -> str:
    return {
        "today": "grower_recommendation",
        "weekly": "executive_brief",
        "field": "water_use_summary",
        "compliance": "compliance_packet",
        "exceptions": "exception_report",
    }.get(scope, "executive_brief")


def _instruction_for_action(action: str, item: str) -> str:
    mapping = {
        "upload_file": f"Upload or attach {item}.",
        "connect_source": f"Connect a source that provides {item}.",
        "assign_task": f"Assign an operator task to collect {item}.",
    }
    return mapping.get(action, f"Review {item}.")


def _missing_reason(source_type: str) -> str:
    if source_type == "compliance_water_accounting":
        return "Compliance packets are weaker without meter and allocation support."
    if source_type == "irrigation_controller":
        return "Operator decisions need controller or irrigation runtime evidence."
    if source_type in {"weather", "et"}:
        return "Water decisions are weaker without weather and ET context."
    return "This evidence is part of the daily operating loop."


def _missing_action(source_type: str) -> str:
    if source_type in {"weather", "et", "irrigation_controller"}:
        return "connect_source"
    if source_type == "document_email_context":
        return "upload_file"
    return "assign_task"


def _next_action_for_update(event_type: str, *, water_gallons: float | None, flow_gpm: float | None, duration_minutes: float | None) -> dict[str, Any]:
    if event_type == "meter_reading":
        return {
            "recommended_next_action": "Compare the meter reading against the latest irrigation evidence.",
            "task_title": "Validate meter reading against field evidence",
            "priority": "medium",
            "why": "Meter records should be tied to a field and recent irrigation event.",
            "instructions": ["Attach the related field note or controller export.", "Confirm the field/block mapping."],
            "evidence_required": ["meter record", "field/block mapping"],
        }
    if water_gallons and water_gallons > 15000:
        return {
            "recommended_next_action": "Review the high water application before approving the next decision.",
            "task_title": "Review high irrigation event",
            "priority": "high",
            "why": "High applied water should be reviewed with field conditions and recent ET/weather context.",
            "instructions": ["Confirm the runtime and gallons applied.", "Add field conditions from the same day."],
            "evidence_required": ["runtime", "field conditions"],
        }
    if event_type == "issue":
        return {
            "recommended_next_action": "Collect supporting evidence and assign an operator follow-up.",
            "task_title": "Resolve reported field issue",
            "priority": "high",
            "why": "Field issues should move into an operator task with clear evidence requirements.",
            "instructions": ["Add a supporting field note or photo.", "Review nearby irrigation evidence."],
            "evidence_required": ["supporting field note", "recent irrigation evidence"],
        }
    return {
        "recommended_next_action": "Review the new field update in the command center.",
        "task_title": None,
        "priority": "low",
        "why": "",
        "instructions": [],
        "evidence_required": [],
    }


def _latest_signal(field: dict[str, Any]) -> str:
    for key in ("latest_irrigation_event", "latest_weather_context", "latest_et_context"):
        payload = field.get(key)
        if payload:
            return f"{payload.get('type')} at {payload.get('at') or 'recently'}"
    return "No recent signal"


def _display_provider(provider: str | None) -> str:
    if not provider:
        return "Source"
    return provider.replace("_", " ").title()


def _slug(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "item"


def _iso(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.isoformat()
