"""Immutable generalized Decision Memory for AGRO-AI."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.intelligence_memory import DecisionSnapshot, FieldStateRevision
from app.models.operational_records import IntelligenceRun
from app.services.field_state_memory import canonical_hash
from app.services.intelligence_grounding import IntelligenceGroundingPacket
from app.services.intelligence_memory_lock import advisory_xact_lock


DECISION_SNAPSHOT_SCHEMA_VERSION = "agroai-decision-snapshot/1.0.0"
DECISION_POLICY_VERSION = "agroai-decision-policy/1.0.0"
ACTION_POLICY_VERSION = "agroai-action-policy/1.0.0"
DECISION_DOMAINS = {"water", "crop_health", "equipment", "assurance", "reporting", "operations"}


class DecisionMemoryConflict(ValueError):
    pass


class DecisionMemoryScopeError(ValueError):
    pass


def _plain(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        result = value.model_dump(mode="python")
    elif isinstance(value, dict):
        result = value
    else:
        raise TypeError("Decision must be a Pydantic model or dictionary")
    if not isinstance(result, dict):
        raise TypeError("Decision payload must serialize to an object")
    return result


def _evidence_ids(packet: IntelligenceGroundingPacket) -> list[str]:
    values = {
        signal.evidence_id
        for signal in [*packet.observed_facts, *packet.derived_context]
        if signal.evidence_id
    }
    values.update(
        evidence_id
        for result in packet.science_checks
        for evidence_id in result.evidence_ids
        if evidence_id
    )
    return sorted(values)


def _scope_block(packet: IntelligenceGroundingPacket) -> str | None:
    blocks = {
        str(signal.block_id).strip()
        for signal in [*packet.observed_facts, *packet.derived_context]
        if signal.block_id and str(signal.block_id).strip()
    }
    return next(iter(blocks)) if len(blocks) == 1 else None


def decision_requires_human_approval(decision: Any) -> bool:
    payload = _plain(decision)
    recommendations = payload.get("recommendations") or []
    return any(
        isinstance(row, dict) and bool(row.get("requires_human_approval"))
        for row in recommendations
    )


def infer_decision_domain(*, task: str, question: str | None = None, decision: Any | None = None) -> str:
    text = f"{task} {question or ''}"
    if decision is not None:
        try:
            text += " " + str(_plain(decision))
        except (TypeError, ValueError):
            pass
    lowered = text.casefold()
    if any(term in lowered for term in ("irrigat", "water", "eto", "moisture", "flow")):
        return "water"
    if any(term in lowered for term in ("pest", "disease", "crop health", "leaf", "canopy", "stress")):
        return "crop_health"
    if any(term in lowered for term in ("equipment", "controller", "valve", "pump", "machine")):
        return "equipment"
    if any(term in lowered for term in ("compliance", "assurance", "audit", "traceability", "regulator")):
        return "assurance"
    if any(term in lowered for term in ("report", "summary", "export")):
        return "reporting"
    return "operations"


def persist_decision_snapshot(
    db: Session,
    packet: IntelligenceGroundingPacket,
    decision: Any,
    *,
    idempotency_key: str,
    task: str,
    domain: str | None = None,
    question: str | None = None,
    user_id: str | None = None,
    field_state_revision_id: str | None = None,
    intelligence_run_id: str | None = None,
    legacy_decision_run_id: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
) -> tuple[DecisionSnapshot, bool]:
    """Insert a content-addressed immutable decision snapshot idempotently.

    Same organization + idempotency key + identical content returns the existing
    row. Reusing the key for different content fails closed. PostgreSQL first
    writes are serialized with a transaction advisory lock. Caller owns commit.
    """
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required")
    selected_domain = domain or infer_decision_domain(task=task, question=question, decision=decision)
    if selected_domain not in DECISION_DOMAINS:
        raise ValueError(f"Unsupported decision domain: {selected_domain}")

    if field_state_revision_id:
        revision = db.query(FieldStateRevision).filter(FieldStateRevision.id == field_state_revision_id).first()
        if revision is None or revision.organization_id != packet.organization_id:
            raise DecisionMemoryScopeError("Field State revision is outside the active organization")
        if packet.workspace_id and revision.workspace_id and revision.workspace_id != packet.workspace_id:
            raise DecisionMemoryScopeError("Field State revision is outside the active workspace")
    if intelligence_run_id:
        run = db.query(IntelligenceRun).filter(IntelligenceRun.id == intelligence_run_id).first()
        if run is None or run.tenant_id != packet.organization_id:
            raise DecisionMemoryScopeError("Intelligence run is outside the active organization")
        if packet.workspace_id and run.workspace_id and run.workspace_id != packet.workspace_id:
            raise DecisionMemoryScopeError("Intelligence run is outside the active workspace")

    decision_json = _plain(decision)
    evidence_graph = packet.model_dump(mode="python")
    science_trace = [row.model_dump(mode="python") for row in packet.science_checks]
    evidence_ids = _evidence_ids(packet)
    snapshot_content = {
        "organization_id": packet.organization_id,
        "workspace_id": packet.workspace_id,
        "field_id": packet.field_id,
        "block_id": _scope_block(packet),
        "domain": selected_domain,
        "task": task,
        "question": question,
        "decision_schema_version": DECISION_SNAPSHOT_SCHEMA_VERSION,
        "grounding_schema_version": packet.schema_version,
        "science_ruleset_version": packet.science_ruleset_version,
        "evidence_graph": evidence_graph,
        "evidence_ids": evidence_ids,
        "science_trace": science_trace,
        "decision": decision_json,
        "grounding_confidence": packet.grounding_confidence,
        "model_provider": model_provider,
        "model_name": model_name,
        "reasoning_effort": reasoning_effort,
        "policy_version": DECISION_POLICY_VERSION,
        "action_policy_version": ACTION_POLICY_VERSION,
        "field_state_revision_id": field_state_revision_id,
        "intelligence_run_id": intelligence_run_id,
        "legacy_decision_run_id": legacy_decision_run_id,
    }
    snapshot_hash = canonical_hash(snapshot_content)

    advisory_xact_lock(db, "decision-snapshot", f"{packet.organization_id}:{key}")
    existing = db.query(DecisionSnapshot).filter(
        DecisionSnapshot.organization_id == packet.organization_id,
        DecisionSnapshot.idempotency_key == key,
    ).first()
    if existing is not None:
        if existing.snapshot_hash != snapshot_hash:
            raise DecisionMemoryConflict("Idempotency key was already used for a different decision snapshot")
        return existing, False

    snapshot = DecisionSnapshot(
        organization_id=packet.organization_id,
        workspace_id=packet.workspace_id,
        user_id=user_id,
        field_state_revision_id=field_state_revision_id,
        intelligence_run_id=intelligence_run_id,
        legacy_decision_run_id=legacy_decision_run_id,
        field_id=packet.field_id,
        block_id=_scope_block(packet),
        domain=selected_domain,
        task=task,
        question=question,
        decision_schema_version=DECISION_SNAPSHOT_SCHEMA_VERSION,
        grounding_schema_version=packet.schema_version,
        science_ruleset_version=packet.science_ruleset_version,
        evidence_graph_json=evidence_graph,
        evidence_ids_json=evidence_ids,
        science_trace_json=science_trace,
        decision_json=decision_json,
        grounding_confidence=packet.grounding_confidence,
        model_provider=model_provider,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        policy_version=DECISION_POLICY_VERSION,
        action_policy_version=ACTION_POLICY_VERSION,
        snapshot_hash=snapshot_hash,
        idempotency_key=key,
    )
    db.add(snapshot)
    db.flush()
    return snapshot, True
