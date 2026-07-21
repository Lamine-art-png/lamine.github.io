"""Correlate a completed field observation with AGRO-AI telemetry and evidence.

This is the core differentiator: a raw field note becomes operational context by
being tied to nearby evidence, connectors and signals — with honest provenance.

Two orthogonal axes are reported and never conflated:
* ``source_mode``  — where the evidence came from: ``live`` (connected controller
  sync), ``sample`` (seeded/demo), or ``uploaded`` (operator/document import).
* ``freshness``    — how recent it is relative to the observation: ``fresh``,
  ``stale`` or ``unavailable``.

We never label a record "live" merely because it is recent, and we never
fabricate live connector data.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.field_intelligence import FieldObservation
from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord, IngestionJob

FRESH_WINDOW = timedelta(hours=48)
LOOKBACK_WINDOW = timedelta(days=14)
TASK_JOB_TYPE = "field_ops_task"

# Telemetry types folded into the weather/water context section.
_WEATHER_ET_TYPES = ("et0", "eto", "weather", "precipitation", "temperature")
_SOIL_TYPES = ("soil_vwc", "soil_moisture")
_SATELLITE_MARKERS = ("satellite", "ndvi", "imagery", "openet")


def _telemetry_context(db: Session, observation: FieldObservation, window_start: datetime,
                       reference: datetime) -> dict:
    """Weather / ET / soil telemetry near the observation, honestly windowed.

    Telemetry rows are real synced signals (Telemetry model); nothing here is
    fabricated — an empty section means no signal existed in the window.
    """
    from app.models import Block, Telemetry

    block = None
    if observation.block_name or observation.field_name:
        candidates = (
            db.query(Block)
            .filter(Block.tenant_id == observation.tenant_id)
            .limit(200)
            .all()
        )
        wanted = {(observation.block_name or "").strip().lower(), (observation.field_name or "").strip().lower()}
        for row in candidates:
            if (row.name or "").strip().lower() in wanted:
                block = row
                break

    query = (
        db.query(Telemetry)
        .filter(Telemetry.tenant_id == observation.tenant_id)
        .filter(Telemetry.timestamp >= window_start)
        .filter(Telemetry.timestamp <= reference + FRESH_WINDOW)
    )
    if block is not None:
        query = query.filter(Telemetry.block_id == block.id)
    rows = query.order_by(Telemetry.timestamp.desc()).limit(200).all()

    def summarize(types: tuple[str, ...]) -> dict:
        matched = [r for r in rows if (r.type or "").lower().startswith(types)]
        if not matched:
            return {"available": False, "freshness": "unavailable", "points": 0}
        newest = matched[0]
        return {
            "available": True,
            "points": len(matched),
            "latest_value": newest.value,
            "unit": newest.unit,
            "latest_at": newest.timestamp.isoformat() if newest.timestamp else None,
            "freshness": _freshness(reference, newest.timestamp),
            "source": newest.source,
        }

    geometry = None
    if block is not None and block.latitude is not None and block.longitude is not None:
        geometry = {
            "block_id": block.id,
            "block_name": block.name,
            "latitude": block.latitude,
            "longitude": block.longitude,
            "area_ha": getattr(block, "area_ha", None),
        }
    return {
        "weather_et": summarize(_WEATHER_ET_TYPES),
        "soil": summarize(_SOIL_TYPES),
        "block_geometry": geometry,
    }


def _decision_context(db: Session, observation: FieldObservation, window_start: datetime) -> list[dict]:
    """Recent decisions/recommendations for the tenant inside the window."""
    from app.models import Recommendation

    rows = (
        db.query(Recommendation)
        .filter(Recommendation.tenant_id == observation.tenant_id)
        .filter(Recommendation.created_at >= window_start)
        .order_by(Recommendation.created_at.desc())
        .limit(5)
        .all()
    )
    return [
        {
            "recommendation_id": row.id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "status": getattr(row, "status", None),
            "block_id": getattr(row, "block_id", None),
        }
        for row in rows
    ]


def _missing_evidence(observation: FieldObservation) -> list[str]:
    """Evidence the extraction asked for that no attached asset satisfies."""
    structured = observation.structured_json or {}
    required = [str(item).strip().lower() for item in structured.get("evidence_requirements") or []]
    if not required:
        return []
    attached_kinds = set()
    for asset in getattr(observation, "assets", []) or []:
        attached_kinds.add((getattr(asset, "kind", "") or "").lower())
    satisfied = {"photo": "photo" in attached_kinds, "meter_reading": False, "video": "video" in attached_kinds}
    return sorted({item for item in required if not satisfied.get(item, False)})


def _freshness(reference: datetime, source_time: datetime | None) -> str:
    if source_time is None:
        return "unavailable"
    return "fresh" if abs(reference - source_time) <= FRESH_WINDOW else "stale"


def _evidence_source_mode(db: Session, row: EvidenceRecord) -> str:
    """Classify how a piece of evidence entered the system (not its recency)."""
    if row.connector_connection_id:
        connection = db.get(ConnectorConnection, row.connector_connection_id)
        if connection and (connection.status or "") == "connected" and connection.mode not in {"manual_upload"}:
            return "live"
        if connection and connection.mode == "manual_upload":
            return "uploaded"
    if row.data_source_id:
        source = db.get(DataSource, row.data_source_id)
        if source and source.source_type in {"chat_upload", "manual_csv", "document"}:
            return "uploaded"
    meta = row.metadata_json or {}
    if meta.get("sample") or meta.get("demo"):
        return "sample"
    if meta.get("source_mode"):
        return str(meta["source_mode"])
    return "uploaded"


def correlate_observation(db: Session, observation: FieldObservation) -> dict:
    tenant_id = observation.tenant_id
    workspace_id = observation.workspace_id
    reference = observation.occurred_at or observation.observed_at or datetime.utcnow()
    window_start = reference - LOOKBACK_WINDOW
    window_end = reference + FRESH_WINDOW

    evidence_query = (
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.tenant_id == tenant_id)
        .filter(EvidenceRecord.occurred_at.isnot(None))
        .filter(EvidenceRecord.occurred_at >= window_start)
        .filter(EvidenceRecord.occurred_at <= window_end)
        # Unusable evidence (e.g. blank/untranscribed captures) must never feed
        # correlation for other observations.
        .filter(or_(EvidenceRecord.quality_status.is_(None), EvidenceRecord.quality_status != "unusable"))
    )
    if workspace_id:
        evidence_query = evidence_query.filter(
            (EvidenceRecord.workspace_id == workspace_id) | (EvidenceRecord.workspace_id.is_(None))
        )
    if observation.field_id:
        evidence_query = evidence_query.filter(
            (EvidenceRecord.field_id == observation.field_id) | (EvidenceRecord.field_id.is_(None))
        )

    evidence_rows = evidence_query.order_by(EvidenceRecord.occurred_at.desc()).limit(30).all()

    related_evidence: list[dict] = []
    providers: set[str] = set()
    for row in evidence_rows:
        if row.id == observation.id or (row.metadata_json or {}).get("observation_id") == observation.id:
            continue  # don't correlate an observation with its own evidence row
        source_mode = _evidence_source_mode(db, row)
        freshness = _freshness(reference, row.occurred_at)
        provider = _evidence_provider(db, row)
        providers.add(provider)
        related_evidence.append(
            {
                "evidence_id": row.id,
                "evidence_type": row.evidence_type,
                "title": row.title,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                "provider": provider,
                "source_mode": source_mode,
                "freshness": freshness,
                "confidence": row.confidence,
                "units": row.units,
            }
        )

    connectors = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == tenant_id).all()
    connector_summary: list[dict] = []
    for connection in connectors:
        if workspace_id and connection.workspace_id and connection.workspace_id != workspace_id:
            continue
        conn_status = connection.status or "not_configured"
        if conn_status == "connected":
            source_mode = "live"
            freshness = _freshness(reference, connection.last_sync_at)
        elif conn_status in {"not_configured", "needs_credentials"}:
            # Not configured is neither uploaded nor sample data — it is simply
            # unavailable as an evidence source.
            source_mode = "unavailable"
            freshness = "unavailable"
        elif conn_status in {"sample", "demo"}:
            source_mode = "sample"
            freshness = "unavailable"
        else:
            # error/disconnected/unknown states: don't imply data exists.
            source_mode = "unknown"
            freshness = "unavailable"
        connector_summary.append(
            {
                "provider": connection.provider,
                "status": conn_status,
                "source_mode": source_mode,
                "freshness": freshness,
                "last_sync_at": connection.last_sync_at.isoformat() if connection.last_sync_at else None,
            }
        )
        providers.add(connection.provider)

    # Recent prior observations on the same field + open operator tasks, scoped
    # to the active workspace (null-workspace rows are shared/platform scope).
    recent_q = (
        db.query(FieldObservation)
        .filter(FieldObservation.tenant_id == tenant_id)
        .filter(FieldObservation.id != observation.id)
        .filter(FieldObservation.status.notin_(["deleted"]))
        .filter(FieldObservation.field_id == observation.field_id)
    )
    if workspace_id:
        recent_q = recent_q.filter(
            (FieldObservation.workspace_id == workspace_id) | (FieldObservation.workspace_id.is_(None))
        )
    recent_observations = recent_q.order_by(FieldObservation.occurred_at.desc()).limit(5).all() if observation.field_id else []

    tasks_q = (
        db.query(IngestionJob)
        .filter(IngestionJob.tenant_id == tenant_id)
        .filter(IngestionJob.job_type == TASK_JOB_TYPE)
        .filter(IngestionJob.status.in_(["open", "in_progress"]))
    )
    if workspace_id:
        tasks_q = tasks_q.filter(
            (IngestionJob.workspace_id == workspace_id) | (IngestionJob.workspace_id.is_(None))
        )
    open_tasks = tasks_q.limit(10).all()

    completed_tasks = (
        db.query(IngestionJob)
        .filter(IngestionJob.tenant_id == tenant_id)
        .filter(IngestionJob.job_type == TASK_JOB_TYPE)
        .filter(IngestionJob.status == "completed")
        .filter(IngestionJob.completed_at.isnot(None))
        .filter(IngestionJob.completed_at >= window_start)
        .order_by(IngestionJob.completed_at.desc())
        .limit(5)
        .all()
    )
    telemetry = _telemetry_context(db, observation, window_start, reference)
    decisions = _decision_context(db, observation, window_start)
    missing_evidence = _missing_evidence(observation)
    satellite_evidence = [
        e for e in related_evidence
        if any(marker in (e.get("evidence_type") or "").lower() for marker in _SATELLITE_MARKERS)
    ]

    fresh_live = sum(1 for e in related_evidence if e["source_mode"] == "live" and e["freshness"] == "fresh")
    severity = (observation.severity or "info").lower()
    should_create_task = severity in {"high", "critical"}
    uncertain = observation.uncertain_fields_json or []
    additional_evidence_required = bool(uncertain or (severity in {"high", "critical"} and not related_evidence))

    confidence = round(min(0.4 + 0.1 * fresh_live + (0.2 if related_evidence else 0.0), 0.95), 2)
    explanation = _build_explanation(len(related_evidence), fresh_live, sorted(providers), severity)

    recommended_action = observation.recommended_action or "Confirm the observation against the correlated evidence and log any change."
    if should_create_task and not observation.recommended_action:
        recommended_action = "Create a follow-up task and verify with a field check."

    verification_required = additional_evidence_required or bool(missing_evidence)

    return {
        "schema_version": "field-observation-correlation/1.2.0",
        "reference_time": reference.isoformat(),
        "time_window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "relevant_evidence_ids": [e["evidence_id"] for e in related_evidence],
        "related_evidence": related_evidence,
        "connectors": connector_summary,
        "telemetry": telemetry,
        "satellite_evidence_ids": [e["evidence_id"] for e in satellite_evidence],
        "recent_decisions": decisions,
        "missing_evidence": missing_evidence,
        "verification_required": verification_required,
        "recent_observations": [
            {"observation_id": o.id, "event_type": o.event_type, "severity": o.severity,
             "occurred_at": o.occurred_at.isoformat() if o.occurred_at else None}
            for o in recent_observations
        ],
        "open_tasks": [{"task_id": t.id, "title": (t.input_json or {}).get("title")} for t in open_tasks],
        "recently_completed_tasks": [
            {"task_id": t.id, "title": (t.input_json or {}).get("title"),
             "completed_at": t.completed_at.isoformat() if t.completed_at else None}
            for t in completed_tasks
        ],
        "source_providers": sorted(providers),
        "source_mode_summary": _count_modes(related_evidence),
        "connector_mode_summary": _count_modes(connector_summary),
        "freshness_summary": {
            "fresh": sum(1 for e in related_evidence if e["freshness"] == "fresh"),
            "stale": sum(1 for e in related_evidence if e["freshness"] == "stale"),
            "unavailable": sum(1 for c in connector_summary if c["freshness"] == "unavailable"),
        },
        "confidence": confidence,
        "explanation": explanation,
        "recommended_next_action": recommended_action,
        "should_create_task": should_create_task,
        "additional_evidence_required": additional_evidence_required,
    }


# Every source mode the system can report, so summaries are explicit and stable.
SOURCE_MODES = ("live", "sample", "uploaded", "field_capture", "unavailable", "unknown")


def _count_modes(rows: list[dict]) -> dict:
    counts = {mode: 0 for mode in SOURCE_MODES}
    for row in rows:
        mode = row.get("source_mode", "unknown")
        counts[mode] = counts.get(mode, 0) + 1
    return counts


def _evidence_provider(db: Session, row: EvidenceRecord) -> str:
    if row.connector_connection_id:
        connection = db.get(ConnectorConnection, row.connector_connection_id)
        if connection:
            return connection.provider
    return row.evidence_type.split("_")[0] if row.evidence_type else "unknown"


def _build_explanation(related_count: int, fresh_live: int, providers: list[str], severity: str) -> str:
    if related_count == 0:
        return (
            "No correlated evidence was found in the observation window. "
            "Treat this observation as unverified until supporting evidence is available."
        )
    provider_text = ", ".join(providers[:4]) if providers else "field records"
    freshness_note = f"{fresh_live} fresh live signal(s)" if fresh_live else "no fresh live signals"
    return (
        f"Correlated with {related_count} evidence record(s) from {provider_text} ({freshness_note}). "
        f"Observation severity is '{severity}'."
    )
