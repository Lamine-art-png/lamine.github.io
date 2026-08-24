"""Transactional orchestration for durable AGRO-AI decision memory."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.services.decision_lifecycle import create_decision_lifecycle
from app.services.decision_memory import decision_requires_human_approval, persist_decision_snapshot
from app.services.field_state_memory import persist_field_state
from app.services.intelligence_grounding import IntelligenceGroundingPacket


@dataclass(frozen=True)
class DecisionMemoryRefs:
    field_state_id: str
    field_state_revision_id: str
    field_state_revision: int
    decision_snapshot_id: str
    lifecycle_id: str
    lifecycle_state: str
    requires_human_approval: bool
    new_field_state_revision: bool
    new_decision_snapshot: bool
    new_lifecycle: bool

    def customer_safe_dict(self) -> dict[str, Any]:
        return {
            "field_state_id": self.field_state_id,
            "field_state_revision_id": self.field_state_revision_id,
            "field_state_revision": self.field_state_revision,
            "decision_snapshot_id": self.decision_snapshot_id,
            "lifecycle_id": self.lifecycle_id,
            "lifecycle_state": self.lifecycle_state,
            "requires_human_approval": self.requires_human_approval,
        }


def persist_grounded_decision_memory(
    db: Session,
    packet: IntelligenceGroundingPacket,
    decision: Any,
    *,
    request_id: str,
    task: str,
    question: str | None,
    user_id: str | None,
    model_provider: str | None,
    model_name: str | None,
    reasoning_effort: str | None,
) -> DecisionMemoryRefs:
    """Persist Field State, immutable decision, and lifecycle in one transaction.

    The caller owns the surrounding transaction. The request ID is the stable
    idempotency identity for retries of the same customer request.
    """
    request_key = str(request_id or "").strip()
    if not request_key:
        raise ValueError("request_id is required for durable decision memory")

    field_state, revision, new_revision = persist_field_state(db, packet)
    snapshot, new_snapshot = persist_decision_snapshot(
        db,
        packet,
        decision,
        idempotency_key=f"runtime:{request_key}",
        task=task,
        question=question,
        user_id=user_id,
        field_state_revision_id=revision.id,
        model_provider=model_provider,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
    )
    requires_approval = decision_requires_human_approval(decision)
    lifecycle, new_lifecycle = create_decision_lifecycle(
        db,
        snapshot,
        requires_human_approval=requires_approval,
        idempotency_key=f"runtime:{request_key}:lifecycle",
    )
    return DecisionMemoryRefs(
        field_state_id=field_state.id,
        field_state_revision_id=revision.id,
        field_state_revision=revision.revision,
        decision_snapshot_id=snapshot.id,
        lifecycle_id=lifecycle.id,
        lifecycle_state=lifecycle.state,
        requires_human_approval=requires_approval,
        new_field_state_revision=new_revision,
        new_decision_snapshot=new_snapshot,
        new_lifecycle=new_lifecycle,
    )
