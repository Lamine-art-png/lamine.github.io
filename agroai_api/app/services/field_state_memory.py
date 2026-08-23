"""Deterministic Field State projection and durable revision memory."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.intelligence_memory import FieldState, FieldStateRevision
from app.services.intelligence_grounding import EvidenceSignal, IntelligenceGroundingPacket
from app.services.intelligence_memory_lock import advisory_xact_lock


FIELD_STATE_SCHEMA_VERSION = "agroai-field-state/1.0.0"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parse_db_time(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _source_cutoff(packet: IntelligenceGroundingPacket) -> datetime | None:
    values: list[datetime] = []
    for signal in [*packet.observed_facts, *packet.derived_context]:
        if signal.observed_at:
            try:
                values.append(_parse_db_time(signal.observed_at))
            except (TypeError, ValueError):
                continue
    return max(values) if values else None


def _scope_block(packet: IntelligenceGroundingPacket) -> str | None:
    blocks = {
        str(signal.block_id).strip()
        for signal in [*packet.observed_facts, *packet.derived_context]
        if signal.block_id and str(signal.block_id).strip()
    }
    return next(iter(blocks)) if len(blocks) == 1 else None


def field_scope_key(packet: IntelligenceGroundingPacket) -> str:
    workspace = packet.workspace_id or "__organization__"
    field = packet.field_id or "__unscoped_field__"
    block = _scope_block(packet) or "__unscoped_block__"
    return f"workspace:{workspace}|field:{field}|block:{block}"


def _bucket(signal: EvidenceSignal) -> str:
    source = str(signal.source_type or "").casefold()
    text = f"{signal.title} {signal.statement}".casefold()
    if source in {"weather", "weather_observation"} or any(term in text for term in ("weather", "forecast", "eto", "et0", "rain", "precip")):
        return "weather"
    if any(term in text for term in ("irrigat", "water", "moisture", "vwc", "flow", "runtime", "depth", "root zone", "root-zone")):
        return "water"
    if any(term in text for term in ("valve", "pump", "controller", "equipment", "machine", "pressure", "motor")):
        return "equipment"
    if any(term in text for term in ("pest", "disease", "lesion", "stress", "canopy", "leaf", "crop health")):
        return "crop_health"
    if any(term in text for term in ("compliance", "assurance", "audit", "sgma", "regulator", "traceability")):
        return "compliance"
    if source == "field_observation":
        return "field_observations"
    return "other_evidence"


def _signal_entry(signal: EvidenceSignal) -> dict[str, Any]:
    return {
        "status": signal.information_class.lower(),
        "evidence_id": signal.evidence_id,
        "source_type": signal.source_type,
        "title": signal.title,
        "statement": signal.statement,
        "units": signal.units,
        "observed_at": signal.observed_at,
        "confidence": signal.confidence_score,
        "quality": signal.quality_score,
        "freshness": signal.freshness_score,
        "provider": signal.provider,
        "source_entity": signal.source_entity,
        "operational_eligible": signal.provenance.get("operational_eligible") is True,
        "provenance": signal.provenance,
    }


def build_field_state_projection(packet: IntelligenceGroundingPacket) -> dict[str, Any]:
    """Build a typed current-state projection without LLM inference or hidden defaults."""
    groups: dict[str, list[dict[str, Any]]] = {
        "weather": [],
        "water": [],
        "equipment": [],
        "crop_health": [],
        "compliance": [],
        "field_observations": [],
        "other_evidence": [],
    }
    for signal in packet.observed_facts:
        groups[_bucket(signal)].append(_signal_entry(signal))

    derived: dict[str, list[dict[str, Any]]] = {key: [] for key in groups}
    for signal in packet.derived_context:
        derived[_bucket(signal)].append(_signal_entry(signal))

    science: list[dict[str, Any]] = []
    for row in packet.science_checks:
        science.append(
            {
                "status": row.status,
                "rule_id": row.rule_id,
                "name": row.name,
                "value": row.value,
                "unit": row.unit,
                "inputs": row.inputs,
                "evidence_ids": row.evidence_ids,
                "confidence": row.confidence_score,
                "limitations": row.limitations,
                "provenance": row.provenance,
            }
        )

    conflict_metrics = {row.metric for row in packet.conflicts}
    return {
        "schema_version": FIELD_STATE_SCHEMA_VERSION,
        "identity": {
            "organization_id": packet.organization_id,
            "workspace_id": packet.workspace_id,
            "field_id": packet.field_id,
            "block_id": _scope_block(packet),
            "crop_type": packet.crop_type,
            "region": packet.region,
        },
        "observed": groups,
        "derived_context": derived,
        "science": science,
        "source_health": packet.source_health,
        "grounding_confidence": packet.grounding_confidence,
        "conflict_metrics": sorted(conflict_metrics),
        "decision_constraints": list(packet.decision_constraints),
    }


def _query_current(db: Session, organization_id: str, scope_key: str):
    query = db.query(FieldState).filter(
        FieldState.organization_id == organization_id,
        FieldState.scope_key == scope_key,
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name != "sqlite":
        query = query.with_for_update()
    return query.first()


def persist_field_state(
    db: Session,
    packet: IntelligenceGroundingPacket,
    *,
    intelligence_run_id: str | None = None,
) -> tuple[FieldState, FieldStateRevision, bool]:
    """Persist current Field State and append a revision only when semantic state changes.

    A PostgreSQL transaction advisory lock serializes both first creation and
    later updates for one logical field scope. Returns
    (current, revision, created_new_revision). Caller owns the transaction.
    """
    projection = build_field_state_projection(packet)
    unknowns = list(dict.fromkeys(packet.unknowns))
    conflicts = [row.model_dump(mode="python") for row in packet.conflicts]
    evidence_ids = sorted(
        {
            signal.evidence_id
            for signal in [*packet.observed_facts, *packet.derived_context]
            if signal.evidence_id
        }
        | {
            evidence_id
            for result in packet.science_checks
            for evidence_id in result.evidence_ids
        }
    )
    payload_for_hash = {
        "state": projection,
        "unknowns": unknowns,
        "conflicts": conflicts,
        "evidence_ids": evidence_ids,
    }
    state_hash = canonical_hash(payload_for_hash)
    scope_key = field_scope_key(packet)
    as_of_at = _parse_db_time(packet.generated_at)
    cutoff = _source_cutoff(packet)
    block_id = _scope_block(packet)

    advisory_xact_lock(db, "field-state", f"{packet.organization_id}:{scope_key}")
    current = _query_current(db, packet.organization_id, scope_key)
    if current is not None and current.state_hash == state_hash:
        revision = (
            db.query(FieldStateRevision)
            .filter(
                FieldStateRevision.field_state_id == current.id,
                FieldStateRevision.revision == current.revision,
            )
            .one()
        )
        return current, revision, False

    previous_hash = current.state_hash if current is not None else None
    next_revision = (current.revision + 1) if current is not None else 1
    if current is None:
        current = FieldState(
            organization_id=packet.organization_id,
            workspace_id=packet.workspace_id,
            field_id=packet.field_id,
            block_id=block_id,
            scope_key=scope_key,
            schema_version=FIELD_STATE_SCHEMA_VERSION,
            revision=next_revision,
            as_of_at=as_of_at,
            source_cutoff_at=cutoff,
            state_json=projection,
            unknowns_json=unknowns,
            conflicts_json=conflicts,
            evidence_ids_json=evidence_ids,
            state_hash=state_hash,
        )
        db.add(current)
        db.flush()
    else:
        current.workspace_id = packet.workspace_id
        current.field_id = packet.field_id
        current.block_id = block_id
        current.schema_version = FIELD_STATE_SCHEMA_VERSION
        current.revision = next_revision
        current.as_of_at = as_of_at
        current.source_cutoff_at = cutoff
        current.state_json = projection
        current.unknowns_json = unknowns
        current.conflicts_json = conflicts
        current.evidence_ids_json = evidence_ids
        current.state_hash = state_hash
        db.flush()

    revision = FieldStateRevision(
        field_state_id=current.id,
        organization_id=packet.organization_id,
        workspace_id=packet.workspace_id,
        field_id=packet.field_id,
        block_id=block_id,
        revision=next_revision,
        schema_version=FIELD_STATE_SCHEMA_VERSION,
        as_of_at=as_of_at,
        source_cutoff_at=cutoff,
        state_json=projection,
        unknowns_json=unknowns,
        conflicts_json=conflicts,
        evidence_ids_json=evidence_ids,
        state_hash=state_hash,
        previous_revision_hash=previous_hash,
        created_by_intelligence_run_id=intelligence_run_id,
    )
    db.add(revision)
    db.flush()
    return current, revision, True
