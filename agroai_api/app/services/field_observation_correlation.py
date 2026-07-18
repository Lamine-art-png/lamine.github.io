"""Correlate a completed field observation with AGRO-AI telemetry and evidence.

This is the core differentiator: a raw field note becomes operational context by
being tied to nearby evidence, connectors and irrigation signals — with honest
provenance. We never fabricate live connector data; every correlated source is
labelled ``live``, ``stale``, ``sample`` or ``unavailable``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.operational_records import ConnectorConnection, EvidenceRecord

# A source older than this (relative to the observation) is context but stale.
FRESH_WINDOW = timedelta(hours=48)
LOOKBACK_WINDOW = timedelta(days=14)


def _freshness(reference: datetime, source_time: datetime | None) -> str:
    if source_time is None:
        return "unavailable"
    delta = abs(reference - source_time)
    if delta <= FRESH_WINDOW:
        return "live"
    if delta <= LOOKBACK_WINDOW:
        return "stale"
    return "stale"


def correlate_observation(db: Session, observation: Any) -> dict:
    """Return a provenance-bearing correlation result for an observation.

    Only tenant + workspace scoped rows are considered. The result records the
    time window used, the source providers, freshness, a confidence score, an
    explanation, and whether a task or additional evidence is warranted.
    """
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
    )
    if workspace_id:
        evidence_query = evidence_query.filter(
            (EvidenceRecord.workspace_id == workspace_id) | (EvidenceRecord.workspace_id.is_(None))
        )
    if observation.field_id:
        evidence_query = evidence_query.filter(
            (EvidenceRecord.field_id == observation.field_id) | (EvidenceRecord.field_id.is_(None))
        )

    evidence_rows = evidence_query.order_by(EvidenceRecord.occurred_at.desc()).limit(25).all()

    related_evidence: list[dict] = []
    providers: set[str] = set()
    for row in evidence_rows:
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
                "freshness": freshness,
                "confidence": row.confidence,
                "units": row.units,
            }
        )

    connectors = (
        db.query(ConnectorConnection)
        .filter(ConnectorConnection.tenant_id == tenant_id)
        .all()
    )
    connector_summary: list[dict] = []
    for connection in connectors:
        if workspace_id and connection.workspace_id and connection.workspace_id != workspace_id:
            continue
        status = connection.status or "not_configured"
        if status == "connected" and connection.last_sync_at:
            evidence_state = _freshness(reference, connection.last_sync_at)
        elif status == "connected":
            evidence_state = "live"
        elif status in {"not_configured", "needs_credentials"}:
            evidence_state = "unavailable"
        else:
            evidence_state = "sample"
        connector_summary.append(
            {
                "provider": connection.provider,
                "status": status,
                "evidence_state": evidence_state,
                "last_sync_at": connection.last_sync_at.isoformat() if connection.last_sync_at else None,
            }
        )
        providers.add(connection.provider)

    live_count = sum(1 for item in related_evidence if item["freshness"] == "live")
    severity = (observation.severity or "info").lower()
    should_create_task = severity in {"high", "critical"}
    additional_evidence_required = bool(
        (observation.uncertain_fields_json or []) or (severity in {"high", "critical"} and not related_evidence)
    )

    confidence = round(min(0.4 + 0.1 * live_count + (0.2 if related_evidence else 0.0), 0.95), 2)

    explanation = _build_explanation(
        related_count=len(related_evidence),
        live_count=live_count,
        providers=sorted(providers),
        severity=severity,
    )

    recommended_action = observation.recommended_action or (
        "Confirm the observation against the correlated evidence and log any change."
    )
    if should_create_task and not observation.recommended_action:
        recommended_action = "Create a follow-up task and verify with a field check."

    return {
        "schema_version": "field-observation-correlation/1.0.0",
        "reference_time": reference.isoformat(),
        "time_window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "relevant_evidence_ids": [item["evidence_id"] for item in related_evidence],
        "related_evidence": related_evidence,
        "connectors": connector_summary,
        "source_providers": sorted(providers),
        "freshness_summary": {
            "live": live_count,
            "stale": sum(1 for item in related_evidence if item["freshness"] == "stale"),
            "unavailable": sum(1 for item in connector_summary if item["evidence_state"] == "unavailable"),
        },
        "confidence": confidence,
        "explanation": explanation,
        "recommended_next_action": recommended_action,
        "should_create_task": should_create_task,
        "additional_evidence_required": additional_evidence_required,
    }


def _evidence_provider(db: Session, row: EvidenceRecord) -> str:
    if row.connector_connection_id:
        connection = db.get(ConnectorConnection, row.connector_connection_id)
        if connection:
            return connection.provider
    return row.evidence_type.split("_")[0] if row.evidence_type else "unknown"


def _build_explanation(*, related_count: int, live_count: int, providers: list[str], severity: str) -> str:
    if related_count == 0:
        return (
            "No correlated evidence was found in the observation window. "
            "Treat this observation as unverified until supporting evidence is available."
        )
    provider_text = ", ".join(providers[:4]) if providers else "field records"
    freshness_note = (
        f"{live_count} live signal(s)" if live_count else "only older context"
    )
    return (
        f"Correlated with {related_count} evidence record(s) from {provider_text} ({freshness_note}). "
        f"Observation severity is '{severity}'."
    )
