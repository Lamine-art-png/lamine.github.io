"""Governed outcome learning from immutable Decision Memory.

Learning here means preserving verified outcomes as future evidence and exposing
cohort-level calibration review signals. This service never changes scientific
parameters, crop coefficients, thresholds, policies, or controller settings.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.intelligence_memory import DecisionLifecycle, DecisionLifecycleEvent, DecisionSnapshot
from app.models.operational_records import EvidenceRecord
from app.services.intelligence_memory_lock import advisory_xact_lock


LEARNING_POLICY_VERSION = "agroai-outcome-learning/1.0.0"
VERIFIED_OUTCOME_EVIDENCE_TYPE = "verified_decision_outcome"


class OutcomeLearningError(ValueError):
    pass


@dataclass(frozen=True)
class MaterializedOutcome:
    evidence_id: str
    created: bool


def _science_rule_ids(snapshot: DecisionSnapshot) -> list[str]:
    return sorted(
        {
            str(row.get("rule_id")).strip()
            for row in (snapshot.science_trace_json or [])
            if isinstance(row, dict) and str(row.get("rule_id") or "").strip()
        }
    )


def _verification_event(db: Session, lifecycle: DecisionLifecycle) -> DecisionLifecycleEvent | None:
    return (
        db.query(DecisionLifecycleEvent)
        .filter(
            DecisionLifecycleEvent.lifecycle_id == lifecycle.id,
            DecisionLifecycleEvent.organization_id == lifecycle.organization_id,
            DecisionLifecycleEvent.to_state == "verified",
        )
        .order_by(DecisionLifecycleEvent.sequence.desc())
        .first()
    )


def _existing_outcome_record(db: Session, lifecycle: DecisionLifecycle) -> EvidenceRecord | None:
    rows = (
        db.query(EvidenceRecord)
        .filter(
            EvidenceRecord.tenant_id == lifecycle.organization_id,
            EvidenceRecord.evidence_type == VERIFIED_OUTCOME_EVIDENCE_TYPE,
        )
        .order_by(EvidenceRecord.created_at.desc())
        .limit(500)
        .all()
    )
    for row in rows:
        metadata = row.metadata_json or {}
        if metadata.get("decision_lifecycle_id") == lifecycle.id:
            return row
    return None


def materialize_verified_outcome_evidence(
    db: Session,
    *,
    organization_id: str,
    lifecycle_id: str,
) -> MaterializedOutcome:
    """Persist one verified lifecycle as reusable organization-scoped evidence.

    Caller owns commit/rollback. Repeated calls are idempotent per lifecycle.
    """
    advisory_xact_lock(db, "verified-outcome-learning", organization_id, lifecycle_id)
    lifecycle = (
        db.query(DecisionLifecycle)
        .filter(
            DecisionLifecycle.id == lifecycle_id,
            DecisionLifecycle.organization_id == organization_id,
        )
        .first()
    )
    if lifecycle is None:
        raise OutcomeLearningError("Decision lifecycle not found in the active organization")
    if lifecycle.state != "verified" or lifecycle.verified_at is None or not lifecycle.outcome:
        raise OutcomeLearningError("Only a completed verified lifecycle can become learning evidence")
    snapshot = (
        db.query(DecisionSnapshot)
        .filter(
            DecisionSnapshot.id == lifecycle.decision_snapshot_id,
            DecisionSnapshot.organization_id == organization_id,
        )
        .first()
    )
    if snapshot is None:
        raise OutcomeLearningError("Decision snapshot is missing from durable memory")

    existing = _existing_outcome_record(db, lifecycle)
    if existing is not None:
        return MaterializedOutcome(evidence_id=existing.id, created=False)

    verification_event = _verification_event(db, lifecycle)
    verification_payload = verification_event.payload_json if verification_event is not None else {}
    verification_evidence_ids = [
        str(value).strip()
        for value in (verification_payload or {}).get("verification_evidence_ids", [])
        if str(value).strip()
    ]
    science_rule_ids = _science_rule_ids(snapshot)
    decision = snapshot.decision_json or {}
    recommendations = decision.get("recommendations") if isinstance(decision, dict) else []
    recommendation_count = len(recommendations) if isinstance(recommendations, list) else 0

    value = {
        "decision_snapshot_id": snapshot.id,
        "decision_lifecycle_id": lifecycle.id,
        "field_state_revision_id": snapshot.field_state_revision_id,
        "domain": snapshot.domain,
        "task": snapshot.task,
        "outcome": lifecycle.outcome,
        "verification_status": lifecycle.verification_status,
        "verification_evidence_ids": verification_evidence_ids,
        "science_rule_ids": science_rule_ids,
        "requires_human_approval": lifecycle.requires_human_approval,
        "recommendation_count": recommendation_count,
        "decision_snapshot_hash": snapshot.snapshot_hash,
    }
    record = EvidenceRecord(
        tenant_id=organization_id,
        workspace_id=snapshot.workspace_id,
        evidence_type=VERIFIED_OUTCOME_EVIDENCE_TYPE,
        field_id=snapshot.field_id,
        block_id=snapshot.block_id,
        occurred_at=lifecycle.verified_at,
        source_updated_at=lifecycle.verified_at,
        title=f"Verified {snapshot.domain} decision outcome",
        summary=(
            f"A governed AGRO-AI {snapshot.domain} decision reached verified outcome "
            f"'{lifecycle.outcome}'. This is historical outcome evidence, not a new recommendation."
        ),
        value_json=value,
        confidence=min(1.0, max(0.0, float(snapshot.grounding_confidence or 0.0))),
        quality_status="verified",
        citation_label="Verified AGRO-AI decision outcome",
        source_excerpt=None,
        metadata_json={
            "learning_policy_version": LEARNING_POLICY_VERSION,
            "source": "decision_memory",
            "decision_lifecycle_id": lifecycle.id,
            "decision_snapshot_id": snapshot.id,
            "immutable_source_hash": snapshot.snapshot_hash,
            "operational_eligible": False,
            "requires_human_review_for_calibration": True,
        },
    )
    db.add(record)
    db.flush()
    return MaterializedOutcome(evidence_id=record.id, created=True)


def materialize_missing_verified_outcomes(
    db: Session,
    *,
    organization_id: str,
    limit: int = 200,
) -> dict[str, int]:
    lifecycles = (
        db.query(DecisionLifecycle)
        .filter(
            DecisionLifecycle.organization_id == organization_id,
            DecisionLifecycle.state == "verified",
        )
        .order_by(DecisionLifecycle.verified_at.asc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    created = 0
    existing = 0
    for lifecycle in lifecycles:
        outcome = materialize_verified_outcome_evidence(
            db,
            organization_id=organization_id,
            lifecycle_id=lifecycle.id,
        )
        created += int(outcome.created)
        existing += int(not outcome.created)
    return {"verified_lifecycles": len(lifecycles), "created": created, "existing": existing}


def build_outcome_learning_summary(
    db: Session,
    *,
    organization_id: str,
    workspace_id: str | None = None,
    field_id: str | None = None,
    domain: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Build a tenant-isolated outcome cohort and calibration-review queue."""
    query = (
        db.query(DecisionLifecycle, DecisionSnapshot)
        .join(DecisionSnapshot, DecisionSnapshot.id == DecisionLifecycle.decision_snapshot_id)
        .filter(
            DecisionLifecycle.organization_id == organization_id,
            DecisionSnapshot.organization_id == organization_id,
        )
    )
    if workspace_id:
        query = query.filter(DecisionSnapshot.workspace_id == workspace_id)
    if field_id:
        query = query.filter(DecisionSnapshot.field_id == field_id)
    if domain:
        query = query.filter(DecisionSnapshot.domain == domain)
    rows = query.order_by(DecisionLifecycle.updated_at.desc()).limit(max(1, min(limit, 2000))).all()

    state_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    rule_outcomes: dict[str, Counter[str]] = defaultdict(Counter)
    rule_verified_counts: Counter[str] = Counter()
    verified = 0
    human_rejected = 0
    verified_items: list[dict[str, Any]] = []

    for lifecycle, snapshot in rows:
        state_counts[str(lifecycle.state)] += 1
        domain_counts[str(snapshot.domain)] += 1
        if lifecycle.state == "rejected":
            human_rejected += 1
        if lifecycle.state != "verified" or not lifecycle.outcome:
            continue
        verified += 1
        outcome = str(lifecycle.outcome)
        outcome_counts[outcome] += 1
        rules = _science_rule_ids(snapshot)
        for rule_id in rules:
            rule_verified_counts[rule_id] += 1
            rule_outcomes[rule_id][outcome] += 1
        verified_items.append(
            {
                "decision_snapshot_id": snapshot.id,
                "lifecycle_id": lifecycle.id,
                "field_state_revision_id": snapshot.field_state_revision_id,
                "workspace_id": snapshot.workspace_id,
                "field_id": snapshot.field_id,
                "block_id": snapshot.block_id,
                "domain": snapshot.domain,
                "outcome": outcome,
                "verified_at": lifecycle.verified_at.isoformat() if lifecycle.verified_at else None,
                "science_rule_ids": rules,
            }
        )

    calibration_review = [
        {
            "rule_id": rule_id,
            "verified_decisions": count,
            "outcome_distribution": dict(sorted(rule_outcomes[rule_id].items())),
            "status": "human_review_required",
            "proposed_parameter_change": None,
            "reason": (
                "Verified outcomes exist for this deterministic rule. Review the field-scoped evidence and calibration history "
                "before proposing any parameter or policy change. AGRO-AI does not auto-tune scientific parameters."
            ),
        }
        for rule_id, count in sorted(rule_verified_counts.items())
    ]

    total = len(rows)
    return {
        "learning_policy_version": LEARNING_POLICY_VERSION,
        "scope": {
            "organization_id": organization_id,
            "workspace_id": workspace_id,
            "field_id": field_id,
            "domain": domain,
        },
        "decision_count": total,
        "verified_count": verified,
        "verification_completion_rate": round(verified / total, 4) if total else 0.0,
        "human_rejection_count": human_rejected,
        "state_distribution": dict(sorted(state_counts.items())),
        "domain_distribution": dict(sorted(domain_counts.items())),
        "verified_outcome_distribution": dict(sorted(outcome_counts.items())),
        "calibration_review": calibration_review,
        "verified_items": verified_items[:200],
        "automatic_parameter_updates": False,
        "automatic_policy_updates": False,
    }
