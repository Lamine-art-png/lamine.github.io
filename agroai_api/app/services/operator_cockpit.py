"""Deterministic operating cockpit rules for AGRO-AI.

The cockpit intentionally starts with rules and database evidence. It does not
call an LLM and it does not invent live integrations.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.block import Block
from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord, IngestionJob
from app.models.recommendation import Recommendation
from app.models.saas import Workspace
from app.models.telemetry import Telemetry


REQUIRED_SOURCE_TYPES = [
    "field_context",
    "irrigation_controller",
    "weather",
    "et",
    "document_email_context",
    "compliance_water_accounting",
]

SOURCE_KEYWORDS = {
    "field_context": ("field", "block", "ranch", "farm", "parcel", "boundary", "crop", "soil"),
    "irrigation_controller": ("wiseconn", "talgil", "controller", "irrigation", "flow", "valve", "runtime"),
    "weather": ("weather", "rain", "precip", "temperature", "forecast", "humidity"),
    "et": ("openet", "et0", "eto", "etc", "evapotranspiration", "et "),
    "document_email_context": ("gmail", "outlook", "drive", "dropbox", "box", "pdf", "csv", "email", "document", "file"),
    "compliance_water_accounting": ("compliance", "allocation", "meter", "water accounting", "gsa", "district", "report"),
}

DISPLAY_NAMES = {
    "gmail": "Gmail",
    "outlook": "Outlook",
    "google_drive": "Google Drive",
    "dropbox": "Dropbox",
    "box": "Box",
    "slack": "Slack",
    "salesforce": "Salesforce",
    "google_earth_engine": "Google Earth Engine",
    "wiseconn": "WiseConn",
    "talgil": "Talgil",
    "openet": "OpenET",
    "weather": "Weather",
    "manual_csv": "Manual upload",
}


@dataclass
class CockpitContext:
    db: Session
    organization_id: str
    workspace: Workspace | None
    connections: list[ConnectorConnection]
    sources: list[DataSource]
    evidence: list[EvidenceRecord]
    jobs: list[IngestionJob]
    blocks: list[Block]
    telemetry: list[Telemetry]
    recommendations: list[Recommendation]

    @property
    def workspace_id(self) -> str | None:
        return self.workspace.id if self.workspace else None

    @property
    def has_data(self) -> bool:
        return bool(
            self.connections
            or self.sources
            or self.evidence
            or self.jobs
            or self.blocks
            or self.telemetry
            or self.recommendations
        )


def build_context(db: Session, organization_id: str, workspace: Workspace | None = None) -> CockpitContext:
    workspace_id = workspace.id if workspace else None
    connection_query = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == organization_id)
    source_query = db.query(DataSource).filter(DataSource.tenant_id == organization_id)
    evidence_query = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == organization_id)
    job_query = db.query(IngestionJob).filter(IngestionJob.tenant_id == organization_id)
    if workspace_id:
        connection_query = connection_query.filter(or_(ConnectorConnection.workspace_id == workspace_id, ConnectorConnection.workspace_id.is_(None)))
        source_query = source_query.filter(or_(DataSource.workspace_id == workspace_id, DataSource.workspace_id.is_(None)))
        evidence_query = evidence_query.filter(or_(EvidenceRecord.workspace_id == workspace_id, EvidenceRecord.workspace_id.is_(None)))
        job_query = job_query.filter(or_(IngestionJob.workspace_id == workspace_id, IngestionJob.workspace_id.is_(None)))

    blocks = db.query(Block).filter(Block.tenant_id == organization_id).order_by(Block.created_at.asc()).all()
    if workspace_id:
        blocks = [
            block
            for block in blocks
            if not isinstance(block.config, dict) or block.config.get("workspace_id") in {None, workspace_id}
        ]
    block_ids = [block.id for block in blocks]

    telemetry: list[Telemetry] = []
    recommendations: list[Recommendation] = []
    if block_ids:
        telemetry = (
            db.query(Telemetry)
            .filter(Telemetry.tenant_id == organization_id, Telemetry.block_id.in_(block_ids))
            .order_by(Telemetry.timestamp.desc())
            .limit(500)
            .all()
        )
        recommendations = (
            db.query(Recommendation)
            .filter(Recommendation.tenant_id == organization_id, Recommendation.block_id.in_(block_ids))
            .order_by(Recommendation.created_at.desc())
            .limit(100)
            .all()
        )

    return CockpitContext(
        db=db,
        organization_id=organization_id,
        workspace=workspace,
        connections=connection_query.order_by(ConnectorConnection.updated_at.desc()).limit(200).all(),
        sources=source_query.order_by(DataSource.created_at.desc()).limit(500).all(),
        evidence=evidence_query.order_by(EvidenceRecord.created_at.desc()).limit(1000).all(),
        jobs=job_query.order_by(IngestionJob.created_at.desc()).limit(500).all(),
        blocks=blocks,
        telemetry=telemetry,
        recommendations=recommendations,
    )


def readiness_summary(ctx: CockpitContext) -> dict[str, Any]:
    if not ctx.has_data:
        return _sample_readiness(ctx)

    present = _present_source_types(ctx)
    missing = [item for item in REQUIRED_SOURCE_TYPES if item not in present]
    stale = _stale_sources(ctx)
    connector_health = [_connector_health(row) for row in ctx.connections]
    provider_breakdown = _provider_breakdown(ctx)

    score = 20
    score += min(len(ctx.evidence), 20)
    score += 10 if ctx.blocks else 0
    score += 10 if ctx.telemetry else 0
    score += 6 * len(present)
    score += min(len([c for c in ctx.connections if c.status in {"connected", "ready", "synced"}]) * 4, 16)
    score -= len(missing) * 8
    score -= len(stale) * 8
    score -= len([job for job in ctx.jobs if "fail" in (job.status or "").lower()]) * 10
    if ctx.sources and not ctx.evidence:
        score -= 12
    score = max(0, min(100, score))

    return {
        "status": "ok",
        "sample_mode": False,
        "workspace_id": ctx.workspace_id,
        "readiness_score": score,
        "readiness_level": _readiness_level(score),
        "connected_sources": len([c for c in ctx.connections if c.status in {"connected", "ready", "synced"}]),
        "uploaded_files": len([s for s in ctx.sources if s.filename]),
        "data_sources": len(ctx.sources),
        "evidence_records": len(ctx.evidence),
        "last_import_at": _iso(max([s.created_at for s in ctx.sources] + [j.completed_at for j in ctx.jobs if j.completed_at], default=None)),
        "required_source_types": REQUIRED_SOURCE_TYPES,
        "present_source_types": present,
        "missing_source_types": missing,
        "stale_sources": stale,
        "connector_health": connector_health,
        "provider_breakdown": provider_breakdown,
        "recommendations": _readiness_recommendations(missing, stale, ctx),
    }


def field_intelligence(ctx: CockpitContext) -> dict[str, Any]:
    if not ctx.has_data:
        return {"status": "ok", "sample_mode": True, "fields": [_sample_field(ctx)]}

    grouped: dict[str, dict[str, Any]] = {}
    block_by_id = {block.id: block for block in ctx.blocks}
    for block in ctx.blocks:
        grouped[block.id] = _base_field(block.id, block.name, block.crop_type)
        grouped[block.id]["blocks"].append(block.name)

    for record in ctx.evidence:
        key, name, crop = _field_from_evidence(record)
        if key not in grouped:
            grouped[key] = _base_field(key, name, crop)
        grouped[key]["evidence_count"] += 1
        grouped[key]["connected_providers"].add(record.metadata_json.get("provider") if isinstance(record.metadata_json, dict) else None)
        grouped[key]["connected_providers"].add(_provider_for_source(ctx, record.data_source_id, record.connector_connection_id))
        grouped[key]["evidence_refs"].append(_evidence_ref(record))
        grouped[key]["latest_event_at"] = _max_iso(grouped[key].get("latest_event_at"), record.occurred_at or record.created_at)

    for source in ctx.sources:
        key, name, crop = _field_from_source(source)
        if key not in grouped:
            grouped[key] = _base_field(key, name, crop)
        grouped[key]["connected_providers"].add(source.provider)
        grouped[key]["latest_event_at"] = _max_iso(grouped[key].get("latest_event_at"), source.created_at)

    for item in ctx.telemetry:
        block = block_by_id.get(item.block_id)
        key = item.block_id or "unknown-field"
        if key not in grouped:
            grouped[key] = _base_field(key, block.name if block else "Unresolved field", block.crop_type if block else None)
        grouped[key]["connected_providers"].add(item.source or "telemetry")
        grouped[key]["latest_event_at"] = _max_iso(grouped[key].get("latest_event_at"), item.timestamp)
        payload = {"type": item.type, "value": item.value, "unit": item.unit, "at": _iso(item.timestamp), "source": item.source}
        if _matches(item.type, SOURCE_KEYWORDS["irrigation_controller"]):
            grouped[key]["latest_irrigation_event"] = grouped[key].get("latest_irrigation_event") or payload
        if _matches(item.type, SOURCE_KEYWORDS["et"]):
            grouped[key]["latest_et_context"] = grouped[key].get("latest_et_context") or payload
        if _matches(item.type, SOURCE_KEYWORDS["weather"]):
            grouped[key]["latest_weather_context"] = grouped[key].get("latest_weather_context") or payload

    fields = []
    for item in grouped.values():
        providers = sorted({p for p in item.pop("connected_providers") if p})
        item["connected_providers"] = providers
        missing = _field_missing_data(item)
        item["missing_data"] = missing
        item["risk_flags"] = _field_risk_flags(item)
        item["confidence"] = round(max(0.1, min(0.95, 0.35 + (0.08 * len(providers)) + (0.03 * item["evidence_count"]) - (0.08 * len(missing)))), 2)
        item["next_best_action"] = _field_next_action(missing)
        fields.append(item)

    fields.sort(key=lambda row: (len(row["risk_flags"]), row["evidence_count"]), reverse=True)
    return {"status": "ok", "sample_mode": False, "fields": fields}


def exceptions(ctx: CockpitContext) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if not ctx.has_data:
        rows.append(_exception("no_data", "high", "data_quality", "No workspace evidence yet", "Connect a source or upload field evidence before relying on operational decisions.", None, None, None, [], "Upload a recent controller export or connect a source.", "upload_file"))
    for connection in ctx.connections:
        health = _connector_health(connection)
        if health["health"] in {"stale", "setup_required", "failed", "pending"}:
            rows.append(_exception(f"connector_{connection.id}", "high" if health["health"] == "failed" else "medium", "connector", f"{health['display_name']} needs attention", health["reason"], connection.provider, None, None, [], health["next_action"], "connect_source" if health["health"] == "setup_required" else "sync_connector"))
    evidence_by_source = Counter(row.data_source_id for row in ctx.evidence if row.data_source_id)
    for source in ctx.sources:
        if evidence_by_source.get(source.id, 0) == 0:
            rows.append(_exception(f"source_no_evidence_{source.id}", "medium", "data_quality", "Uploaded source has no evidence records", f"{source.filename or source.source_type} was imported but did not produce usable evidence records.", source.provider, None, source.id, [], "Review mapping or upload a cleaner export.", "review_data"))
    for job in ctx.jobs:
        if "fail" in (job.status or "").lower() or job.error:
            rows.append(_exception(f"job_failed_{job.id}", "high", "connector", "Ingestion job failed", job.error or f"Job status is {job.status}.", None, None, job.data_source_id, [], "Review connector credentials or source format.", "review_data"))
    present = _present_source_types(ctx)
    for missing in ["weather", "et"]:
        if missing not in present:
            rows.append(_exception(f"missing_{missing}", "medium", "field_risk", f"Missing {missing.upper()} context", f"Field recommendations are weaker without {missing} evidence.", None, None, None, [], f"Connect or upload a {missing} source.", "connect_source"))
    unresolved = [row for row in ctx.evidence if not row.field_id and not row.block_id]
    if unresolved:
        rows.append(_exception("unresolved_field_evidence", "low", "data_quality", "Evidence cannot resolve field", f"{len(unresolved)} evidence records are not tied to a field or block.", None, "Unresolved", None, [_evidence_ref(row) for row in unresolved[:5]], "Map evidence to field/block before report generation.", "review_data"))
    if ctx.sources and len(ctx.sources) != len({(s.provider, s.filename, s.created_at.date() if s.created_at else None) for s in ctx.sources}):
        rows.append(_exception("duplicate_sources", "low", "data_quality", "Duplicate-looking source files", "Some uploaded source files look similar by provider, filename, and import date.", None, None, None, [], "Review source list before generating owner reports.", "review_data"))
    if not ctx.sources and not ctx.telemetry:
        rows.append(_exception("no_recent_data", "high", "field_risk", "No recent operational data", "The workspace has no recent source imports or telemetry records.", None, None, None, [], "Sync a connector or upload recent field records.", "sync_connector"))

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows.sort(key=lambda row: (order.get(row["severity"], 9), row["title"]))
    counts = Counter(row["severity"] for row in rows)
    return {"status": "ok", "exceptions": rows, "counts_by_severity": dict(counts)}


def decision_workbench(ctx: CockpitContext, mode: str = "daily", field_id: str | None = None) -> dict[str, Any]:
    fields = field_intelligence(ctx)["fields"]
    if field_id:
        fields = [row for row in fields if row["field_id"] == field_id]
    exception_rows = exceptions(ctx)["exceptions"]
    decisions = [_decision_for_field(row, exception_rows, mode) for row in fields[:6]]
    if not decisions:
        decisions = [_collect_data_decision(exception_rows, mode)]
    return {"status": "ok", "sample_mode": not ctx.has_data, "decisions": decisions}


def report_factory(ctx: CockpitContext, report_type: str, audience: str | None = None, field_id: str | None = None) -> dict[str, Any]:
    summary = readiness_summary(ctx)
    field_payload = field_intelligence(ctx)
    fields = field_payload["fields"]
    if field_id:
        fields = [row for row in fields if row["field_id"] == field_id]
    exception_payload = exceptions(ctx)
    decisions = decision_workbench(ctx, field_id=field_id)["decisions"]
    missing = summary["missing_source_types"]
    title = _report_title(report_type, audience)
    report = {
        "title": title,
        "report_type": report_type,
        "audience": audience or "owner",
        "generated_at": _iso(datetime.utcnow()),
        "executive_summary": _report_summary(summary, report_type),
        "key_findings": _key_findings(summary, fields, exception_payload["exceptions"]),
        "field_summary": fields,
        "exceptions": exception_payload["exceptions"],
        "decisions": decisions,
        "missing_evidence": missing,
        "evidence_appendix": _evidence_appendix(ctx),
        "recommended_next_actions": summary["recommendations"][:6],
    }
    return {"status": "ok", "sample_mode": not ctx.has_data, "report": report}


def _sample_readiness(ctx: CockpitContext) -> dict[str, Any]:
    return {
        "status": "ok",
        "sample_mode": True,
        "workspace_id": ctx.workspace_id,
        "readiness_score": 18,
        "readiness_level": "blocked",
        "connected_sources": 0,
        "uploaded_files": 0,
        "data_sources": 0,
        "evidence_records": 0,
        "last_import_at": None,
        "required_source_types": REQUIRED_SOURCE_TYPES,
        "present_source_types": [],
        "missing_source_types": REQUIRED_SOURCE_TYPES,
        "stale_sources": [],
        "connector_health": [],
        "provider_breakdown": [],
        "recommendations": [
            "Upload a recent controller export or field log.",
            "Connect an ET/weather source before relying on irrigation recommendations.",
            "Add compliance or water accounting evidence before generating agency-ready reports.",
        ],
    }


def _sample_field(ctx: CockpitContext) -> dict[str, Any]:
    return {
        "field_id": "sample-field",
        "field_name": "Sample Field",
        "blocks": ["Sample Block"],
        "crop": ctx.workspace.crop if ctx.workspace and ctx.workspace.crop else "Crop pending",
        "evidence_count": 0,
        "latest_event_at": None,
        "latest_irrigation_event": None,
        "latest_et_context": None,
        "latest_weather_context": None,
        "connected_providers": [],
        "missing_data": ["field boundary", "irrigation log", "ET source", "weather", "water accounting evidence"],
        "risk_flags": [
            {
                "severity": "high",
                "type": "missing_operational_context",
                "title": "No field evidence available",
                "explanation": "The cockpit needs at least one uploaded or connected source before making operational recommendations.",
            }
        ],
        "confidence": 0.1,
        "next_best_action": "Upload a controller export or connect a field source.",
    }


def _base_field(field_id: str, field_name: str | None, crop: str | None) -> dict[str, Any]:
    return {
        "field_id": field_id,
        "field_name": field_name or "Unresolved field",
        "blocks": [],
        "crop": crop or "Crop pending",
        "evidence_count": 0,
        "latest_event_at": None,
        "latest_irrigation_event": None,
        "latest_et_context": None,
        "latest_weather_context": None,
        "connected_providers": set(),
        "missing_data": [],
        "risk_flags": [],
        "confidence": 0,
        "next_best_action": "",
        "evidence_refs": [],
    }


def _present_source_types(ctx: CockpitContext) -> list[str]:
    haystack: list[str] = []
    haystack.extend([row.provider or "" for row in ctx.connections])
    haystack.extend([row.status or "" for row in ctx.connections])
    haystack.extend([row.source_type or "" for row in ctx.sources])
    haystack.extend([row.provider or "" for row in ctx.sources])
    haystack.extend([row.filename or "" for row in ctx.sources])
    haystack.extend([row.raw_text or "" for row in ctx.sources[:20]])
    haystack.extend([row.evidence_type or "" for row in ctx.evidence])
    haystack.extend([row.title or "" for row in ctx.evidence])
    haystack.extend([row.summary or "" for row in ctx.evidence])
    haystack.extend([row.type or "" for row in ctx.telemetry])
    haystack.extend([row.source or "" for row in ctx.telemetry])
    haystack.extend([block.name or "" for block in ctx.blocks])
    haystack.extend([block.crop_type or "" for block in ctx.blocks])
    text = " ".join(haystack).lower()
    present = [name for name, keywords in SOURCE_KEYWORDS.items() if _matches(text, keywords)]
    if ctx.blocks and "field_context" not in present:
        present.append("field_context")
    if ctx.sources and "document_email_context" not in present:
        present.append("document_email_context")
    return present


def _connector_health(row: ConnectorConnection) -> dict[str, Any]:
    now = datetime.utcnow()
    status = (row.status or "").lower()
    if status in {"failed", "error"} or row.last_error:
        health = "failed"
        reason = row.last_error or "Connector reported a failed state."
        next_action = "Review connector credentials and run a test sync."
    elif status in {"needs_credentials", "not_configured", "setup_required"}:
        health = "setup_required"
        reason = "Connector exists but is not fully authorized."
        next_action = "Complete connector setup."
    elif status in {"oauth_started", "pending", "pending_token_exchange"}:
        health = "pending"
        reason = "OAuth authorization is pending token exchange."
        next_action = "Complete authorization and token exchange."
    elif row.last_sync_at and row.last_sync_at < now - timedelta(days=7):
        health = "stale"
        reason = "Connector has not synced in more than seven days."
        next_action = "Run a connector sync."
    else:
        health = "healthy"
        reason = "Connector is ready or recently active."
        next_action = "Keep monitoring source freshness."
    return {
        "provider": row.provider,
        "display_name": DISPLAY_NAMES.get(row.provider, row.display_name),
        "status": row.status,
        "last_sync_at": _iso(row.last_sync_at),
        "health": health,
        "reason": reason,
        "next_action": next_action,
    }


def _provider_breakdown(ctx: CockpitContext) -> list[dict[str, Any]]:
    providers = sorted({row.provider for row in ctx.connections + ctx.sources if row.provider})
    output = []
    for provider in providers:
        output.append(
            {
                "provider": provider,
                "connections": len([row for row in ctx.connections if row.provider == provider]),
                "data_sources": len([row for row in ctx.sources if row.provider == provider]),
                "evidence_records": len([row for row in ctx.evidence if _provider_for_source(ctx, row.data_source_id, row.connector_connection_id) == provider]),
                "last_seen_at": _iso(
                    max(
                        [row.updated_at for row in ctx.connections if row.provider == provider]
                        + [row.created_at for row in ctx.sources if row.provider == provider],
                        default=None,
                    )
                ),
            }
        )
    if ctx.telemetry and "telemetry" not in providers:
        output.append(
            {
                "provider": "telemetry",
                "connections": 0,
                "data_sources": 0,
                "evidence_records": len(ctx.telemetry),
                "last_seen_at": _iso(max([row.timestamp for row in ctx.telemetry], default=None)),
            }
        )
    return output


def _readiness_recommendations(missing: list[str], stale: list[dict[str, Any]], ctx: CockpitContext) -> list[str]:
    recs: list[str] = []
    if "et" in missing or "weather" in missing:
        recs.append("Connect ET/weather source before relying on irrigation recommendations.")
    if "irrigation_controller" in missing:
        recs.append("Upload or sync controller logs for the highest-priority field.")
    if "compliance_water_accounting" in missing:
        recs.append("Add water accounting, allocation, or compliance evidence before agency reporting.")
    if stale:
        recs.append("Refresh stale connectors before generating owner or lender reports.")
    if ctx.sources and not ctx.evidence:
        recs.append("Review source mappings because uploaded files have not produced evidence records.")
    if not recs:
        recs.append("Review exceptions and approve operator follow-up for the highest-risk field.")
    return recs


def _field_missing_data(item: dict[str, Any]) -> list[str]:
    missing = []
    providers = set(item.get("connected_providers") or [])
    text = " ".join(providers).lower()
    if not item.get("blocks"):
        missing.append("field boundary")
    if not item.get("latest_irrigation_event") and not _matches(text, SOURCE_KEYWORDS["irrigation_controller"]):
        missing.append("irrigation log")
    if not item.get("latest_et_context") and "openet" not in text:
        missing.append("ET source")
    if not item.get("latest_weather_context") and "weather" not in text:
        missing.append("weather")
    return missing


def _field_risk_flags(item: dict[str, Any]) -> list[dict[str, str]]:
    flags = []
    for missing in item["missing_data"]:
        severity = "medium" if missing in {"ET source", "weather"} else "high"
        flags.append(
            {
                "severity": severity,
                "type": "missing_" + re.sub(r"[^a-z0-9]+", "_", missing.lower()).strip("_"),
                "title": f"Missing {missing}",
                "explanation": f"Operational confidence is lower without {missing}.",
            }
        )
    return flags


def _decision_for_field(field: dict[str, Any], exception_rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    missing = field.get("missing_data", [])
    if missing:
        recommendation = "Collect missing data first before approving field action."
        why = f"{field['field_name']} is missing {', '.join(missing[:3])}."
        risk = "high" if len(missing) >= 3 else "medium"
    else:
        recommendation = "Review evidence and approve operator follow-up."
        why = f"{field['field_name']} has enough field context for a reviewed operational decision."
        risk = "medium"
    return {
        "id": f"decision_{_slug(field['field_id'])}_{mode}",
        "field_name": field["field_name"],
        "recommendation": recommendation,
        "why": why,
        "risk_level": risk,
        "confidence": field.get("confidence", 0.25),
        "evidence_used": field.get("evidence_refs", [])[:8],
        "missing_evidence": missing,
        "expected_impact": {
            "water": "Improves water decision reliability once missing irrigation/ET evidence is resolved.",
            "crop": "Reduces crop-risk ambiguity by tying action to field-specific evidence.",
            "compliance": "Improves audit trail if evidence is mapped to field and source.",
        },
        "operator_instructions": _operator_instructions(field),
        "approval_status": "needs_review",
        "next_action": "Review evidence and approve operator follow-up",
        "exceptions": [row for row in exception_rows if row.get("affected_field") in {None, field["field_name"], "Unresolved"}][:5],
    }


def _collect_data_decision(exception_rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    return {
        "id": f"decision_collect_missing_data_{mode}",
        "field_name": "Workspace",
        "recommendation": "Collect missing data first.",
        "why": "The cockpit does not have enough field, irrigation, ET/weather, or compliance evidence to make an operational recommendation.",
        "risk_level": "high",
        "confidence": 0.1,
        "evidence_used": [],
        "missing_evidence": REQUIRED_SOURCE_TYPES,
        "expected_impact": {"water": "Pending", "crop": "Pending", "compliance": "Pending"},
        "operator_instructions": ["Upload a controller export.", "Connect ET/weather context.", "Map evidence to field/block."],
        "approval_status": "needs_review",
        "next_action": "Upload or connect evidence",
        "exceptions": exception_rows[:5],
    }


def _operator_instructions(field: dict[str, Any]) -> list[str]:
    instructions = []
    if "irrigation log" in field.get("missing_data", []):
        instructions.append("Upload latest controller or flow meter reading.")
    if "ET source" in field.get("missing_data", []):
        instructions.append("Connect OpenET or upload recent ET export.")
    if "field boundary" in field.get("missing_data", []):
        instructions.append("Map records to the correct field/block.")
    if not instructions:
        instructions.append("Review evidence citations and approve the next operator task.")
    return instructions


def _report_summary(summary: dict[str, Any], report_type: str) -> str:
    if summary["sample_mode"]:
        return "This report is based on an empty workspace. Connect or upload evidence before sending an operational packet."
    return (
        f"{report_type.replace('_', ' ').title()} generated from {summary['evidence_records']} evidence records, "
        f"{summary['data_sources']} data sources, and {summary['connected_sources']} connected sources. "
        f"Readiness is {summary['readiness_level']} at {summary['readiness_score']}%."
    )


def _key_findings(summary: dict[str, Any], fields: list[dict[str, Any]], exception_rows: list[dict[str, Any]]) -> list[str]:
    return [
        f"Readiness level: {summary['readiness_level']} ({summary['readiness_score']}%).",
        f"Tracked fields: {len(fields)}.",
        f"Open exceptions: {len(exception_rows)}.",
        f"Missing source types: {', '.join(summary['missing_source_types']) or 'none'}.",
    ]


def _evidence_appendix(ctx: CockpitContext) -> list[dict[str, Any]]:
    records = [_evidence_ref(row) for row in ctx.evidence[:50]]
    if not records and ctx.telemetry:
        records = [
            {
                "id": row.id,
                "label": f"{row.type} telemetry",
                "source": row.source or "telemetry",
                "occurred_at": _iso(row.timestamp),
            }
            for row in ctx.telemetry[:50]
        ]
    return records


def _exception(identifier: str, severity: str, category: str, title: str, explanation: str, provider: str | None, field: str | None, source_id: str | None, refs: list[Any], action: str, action_type: str) -> dict[str, Any]:
    return {
        "id": f"exception_{identifier}",
        "severity": severity,
        "category": category,
        "title": title,
        "explanation": explanation,
        "affected_provider": provider,
        "affected_field": field,
        "affected_source_id": source_id,
        "evidence_refs": refs,
        "recommended_action": action,
        "action_type": action_type,
        "created_from": "deterministic_rule",
    }


def _field_from_evidence(row: EvidenceRecord) -> tuple[str, str, str | None]:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    display_field = metadata.get("field") or metadata.get("field_name") or metadata.get("ranch")
    display_block = metadata.get("block") or metadata.get("block_name")
    field = row.field_id or display_field
    block = row.block_id or display_block
    crop = metadata.get("crop")
    name = display_field or display_block or field or block or _extract_field_text(" ".join([row.title or "", row.summary or "", row.source_excerpt or ""]))
    key = _slug(field or block or name or "unknown-field")
    return key, name or "Unresolved field", crop


def _field_from_source(row: DataSource) -> tuple[str, str, str | None]:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    name = metadata.get("field") or metadata.get("field_name") or metadata.get("block") or _extract_field_text(" ".join([row.filename or "", row.raw_text or ""]))
    return _slug(name or "unknown-field"), name or "Unresolved field", metadata.get("crop")


def _extract_field_text(text: str) -> str | None:
    match = re.search(r"\b(?:field|block|ranch|parcel)\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9 _.-]{1,40})", text, re.I)
    return match.group(1).strip() if match else None


def _provider_for_source(ctx: CockpitContext, source_id: str | None, connection_id: str | None) -> str | None:
    if source_id:
        for source in ctx.sources:
            if source.id == source_id:
                return source.provider
    if connection_id:
        for connection in ctx.connections:
            if connection.id == connection_id:
                return connection.provider
    return None


def _evidence_ref(row: EvidenceRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.citation_label,
        "title": row.title,
        "type": row.evidence_type,
        "occurred_at": _iso(row.occurred_at or row.created_at),
    }


def _stale_sources(ctx: CockpitContext) -> list[dict[str, Any]]:
    rows = []
    cutoff = datetime.utcnow() - timedelta(days=7)
    for connection in ctx.connections:
        if connection.last_sync_at and connection.last_sync_at < cutoff:
            rows.append({"provider": connection.provider, "display_name": connection.display_name, "last_sync_at": _iso(connection.last_sync_at)})
    return rows


def _field_next_action(missing: list[str]) -> str:
    if "irrigation log" in missing:
        return "Upload or sync controller logs for this field."
    if "ET source" in missing:
        return "Connect OpenET or upload ET export for this field."
    if "field boundary" in missing:
        return "Map source records to a field/block."
    return "Review evidence and approve operator follow-up."


def _readiness_level(score: int) -> str:
    if score >= 85:
        return "excellent"
    if score >= 65:
        return "good"
    if score >= 35:
        return "partial"
    return "blocked"


def _report_title(report_type: str, audience: str | None) -> str:
    audience_label = (audience or "owner").replace("_", " ").title()
    return f"AGRO-AI {report_type.replace('_', ' ').title()} for {audience_label}"


def _matches(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "unknown").lower()).strip("-") or "unknown"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _max_iso(current: str | None, candidate: datetime | None) -> str | None:
    if candidate is None:
        return current
    if current is None:
        return _iso(candidate)
    try:
        current_dt = datetime.fromisoformat(current)
    except ValueError:
        return _iso(candidate)
    return _iso(max(current_dt, candidate))
