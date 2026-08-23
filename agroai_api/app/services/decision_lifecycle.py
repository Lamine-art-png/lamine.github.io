"""Deterministic lifecycle state machine for generalized AGRO-AI decisions."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.intelligence_memory import DecisionLifecycle, DecisionLifecycleEvent, DecisionSnapshot
from app.services.intelligence_memory_lock import advisory_xact_lock


LIFECYCLE_POLICY_VERSION = "agroai-decision-lifecycle/1.0.0"
TERMINAL_STATES = {"rejected", "verified", "failed", "expired", "cancelled"}
ALLOWED_TRANSITIONS = {
    "proposed": {"awaiting_approval", "approved", "cancelled", "expired"},
    "awaiting_approval": {"approved", "rejected", "cancelled", "expired"},
    "approved": {"execution_pending", "executed", "cancelled", "expired"},
    "execution_pending": {"executed", "failed", "cancelled", "expired"},
    "executed": {"verification_pending", "verified", "failed"},
    "verification_pending": {"verified", "failed"},
    "rejected": set(),
    "verified": set(),
    "failed": set(),
    "expired": set(),
    "cancelled": set(),
}
ACTOR_TYPES = {"user", "system", "provider"}


class LifecycleTransitionError(ValueError):
    pass


class LifecycleScopeError(ValueError):
    pass


class LifecycleIdempotencyConflict(ValueError):
    pass


def _lock_lifecycle(db: Session, lifecycle_id: str) -> DecisionLifecycle | None:
    query = db.query(DecisionLifecycle).filter(DecisionLifecycle.id == lifecycle_id)
    bind = db.get_bind()
    if bind is not None and bind.dialect.name != "sqlite":
        query = query.with_for_update()
    return query.first()


def _existing_event(db: Session, organization_id: str, idempotency_key: str) -> DecisionLifecycleEvent | None:
    return db.query(DecisionLifecycleEvent).filter(
        DecisionLifecycleEvent.organization_id == organization_id,
        DecisionLifecycleEvent.idempotency_key == idempotency_key,
    ).first()


def _event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {"lifecycle_policy_version": LIFECYCLE_POLICY_VERSION, **payload}


def _append_event(
    db: Session,
    lifecycle: DecisionLifecycle,
    *,
    from_state: str | None,
    to_state: str,
    event_type: str,
    actor_type: str,
    actor_user_id: str | None,
    idempotency_key: str,
    payload: dict[str, Any],
    sequence: int,
) -> DecisionLifecycleEvent:
    event = DecisionLifecycleEvent(
        lifecycle_id=lifecycle.id,
        organization_id=lifecycle.organization_id,
        workspace_id=lifecycle.workspace_id,
        sequence=sequence,
        from_state=from_state,
        to_state=to_state,
        event_type=event_type,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        payload_json=_event_payload(payload),
        idempotency_key=idempotency_key,
    )
    db.add(event)
    db.flush()
    return event


def _normalize_evidence_list(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key) or []
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _validate_transition(
    lifecycle: DecisionLifecycle,
    *,
    to_state: str,
    actor_type: str,
    actor_user_id: str | None,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    if actor_type not in ACTOR_TYPES:
        raise LifecycleTransitionError(f"Unsupported actor_type: {actor_type}")
    if lifecycle.state in TERMINAL_STATES:
        raise LifecycleTransitionError(f"Decision lifecycle is terminal: {lifecycle.state}")
    if to_state not in ALLOWED_TRANSITIONS.get(lifecycle.state, set()):
        raise LifecycleTransitionError(f"Transition {lifecycle.state} -> {to_state} is not allowed")
    if lifecycle.expires_at is not None and now > lifecycle.expires_at and to_state != "expired":
        raise LifecycleTransitionError("Decision has expired and cannot advance")

    if to_state == "awaiting_approval" and not lifecycle.requires_human_approval:
        raise LifecycleTransitionError("Human approval is not required for this decision")
    if to_state == "approved" and lifecycle.requires_human_approval:
        if actor_type != "user" or not actor_user_id:
            raise LifecycleTransitionError("Human-approved decisions require an authenticated user actor")
    if to_state == "rejected":
        if actor_type != "user" or not actor_user_id:
            raise LifecycleTransitionError("Decision rejection requires an authenticated user actor")
        if not str(payload.get("reason") or "").strip():
            raise LifecycleTransitionError("Decision rejection requires a reason")
    if to_state in {"execution_pending", "executed"} and lifecycle.requires_human_approval and lifecycle.approved_at is None:
        raise LifecycleTransitionError("Physical or external execution cannot begin before human approval")
    if to_state == "executed":
        execution_evidence = _normalize_evidence_list(payload, "execution_evidence_ids")
        provider_event_id = str(payload.get("provider_event_id") or "").strip()
        if not execution_evidence and not provider_event_id:
            raise LifecycleTransitionError("Executed state requires execution evidence or a provider event ID")
    if to_state == "verified":
        verification_evidence = _normalize_evidence_list(payload, "verification_evidence_ids")
        outcome = str(payload.get("outcome") or "").strip()
        if not verification_evidence:
            raise LifecycleTransitionError("Verified state requires verification evidence")
        if not outcome:
            raise LifecycleTransitionError("Verified state requires an outcome")


def transition_decision_lifecycle(
    db: Session,
    lifecycle_id: str,
    *,
    to_state: str,
    event_type: str,
    actor_type: str,
    idempotency_key: str,
    actor_user_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[DecisionLifecycle, DecisionLifecycleEvent, bool]:
    """Apply one state transition and append its immutable event atomically.

    Returns (lifecycle, event, created_new_event). Reusing an idempotency key
    with a different actor, payload, event type, or target state fails closed.
    A successful verification also materializes historical outcome evidence in
    this same transaction, so VERIFIED never exists without its learning record.
    Caller owns the transaction.
    """
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required")
    payload = dict(payload or {})
    lifecycle = _lock_lifecycle(db, lifecycle_id)
    if lifecycle is None:
        raise LifecycleTransitionError("Decision lifecycle not found")

    existing = _existing_event(db, lifecycle.organization_id, key)
    if existing is not None:
        same_request = (
            existing.lifecycle_id == lifecycle.id
            and existing.to_state == to_state
            and existing.event_type == event_type
            and existing.actor_type == actor_type
            and existing.actor_user_id == actor_user_id
            and (existing.payload_json or {}) == _event_payload(payload)
        )
        if not same_request:
            raise LifecycleIdempotencyConflict("Lifecycle event idempotency key was reused for a different transition")
        return lifecycle, existing, False

    now = datetime.utcnow()
    _validate_transition(
        lifecycle,
        to_state=to_state,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        payload=payload,
        now=now,
    )
    previous = lifecycle.state
    lifecycle.version += 1
    lifecycle.state = to_state

    if to_state == "approved":
        lifecycle.approved_at = now
        lifecycle.approved_by_user_id = actor_user_id
    elif to_state == "rejected":
        lifecycle.rejected_at = now
        lifecycle.rejection_reason = str(payload.get("reason") or "").strip()
    elif to_state == "executed":
        lifecycle.executed_at = now
    elif to_state == "verification_pending":
        lifecycle.verification_status = str(payload.get("verification_status") or "pending")
    elif to_state == "verified":
        lifecycle.verified_at = now
        lifecycle.verification_status = str(payload.get("verification_status") or "complete")
        lifecycle.outcome = str(payload.get("outcome") or "").strip()
        if payload.get("legacy_execution_verification_id"):
            lifecycle.legacy_execution_verification_id = str(payload["legacy_execution_verification_id"])
    elif to_state == "failed":
        lifecycle.verification_status = str(payload.get("verification_status") or "failed")
        lifecycle.outcome = str(payload.get("outcome") or "failed")

    event = _append_event(
        db,
        lifecycle,
        from_state=previous,
        to_state=to_state,
        event_type=event_type,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        idempotency_key=key,
        payload=payload,
        sequence=lifecycle.version,
    )
    db.flush()

    if to_state == "verified":
        # Local import avoids coupling the outcome service back into lifecycle
        # module import order while keeping verification + learning one DB tx.
        from app.services.outcome_learning import materialize_verified_outcome_evidence

        materialize_verified_outcome_evidence(
            db,
            organization_id=lifecycle.organization_id,
            lifecycle_id=lifecycle.id,
        )
        db.flush()

    return lifecycle, event, True


def create_decision_lifecycle(
    db: Session,
    snapshot: DecisionSnapshot,
    *,
    requires_human_approval: bool,
    idempotency_key: str,
    expires_at: datetime | None = None,
) -> tuple[DecisionLifecycle, bool]:
    """Create lifecycle and move it to its first policy state deterministically."""
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required")
    advisory_xact_lock(db, "decision-lifecycle", snapshot.id)
    existing = db.query(DecisionLifecycle).filter(DecisionLifecycle.decision_snapshot_id == snapshot.id).first()
    if existing is not None:
        if bool(existing.requires_human_approval) != bool(requires_human_approval):
            raise LifecycleIdempotencyConflict("Existing decision lifecycle has a different approval policy")
        return existing, False

    lifecycle = DecisionLifecycle(
        decision_snapshot_id=snapshot.id,
        organization_id=snapshot.organization_id,
        workspace_id=snapshot.workspace_id,
        state="proposed",
        version=1,
        requires_human_approval=requires_human_approval,
        expires_at=expires_at,
    )
    db.add(lifecycle)
    db.flush()
    _append_event(
        db,
        lifecycle,
        from_state=None,
        to_state="proposed",
        event_type="decision_created",
        actor_type="system",
        actor_user_id=None,
        idempotency_key=f"{key}:created",
        payload={"requires_human_approval": requires_human_approval},
        sequence=1,
    )

    if expires_at is not None and datetime.utcnow() > expires_at:
        transition_decision_lifecycle(
            db,
            lifecycle.id,
            to_state="expired",
            event_type="decision_expired_before_activation",
            actor_type="system",
            idempotency_key=f"{key}:expired",
            payload={"reason": "decision_validity_window_elapsed"},
        )
    elif requires_human_approval:
        transition_decision_lifecycle(
            db,
            lifecycle.id,
            to_state="awaiting_approval",
            event_type="approval_requested",
            actor_type="system",
            idempotency_key=f"{key}:awaiting_approval",
            payload={},
        )
    else:
        transition_decision_lifecycle(
            db,
            lifecycle.id,
            to_state="approved",
            event_type="auto_approved_side_effect_free",
            actor_type="system",
            idempotency_key=f"{key}:auto_approved",
            payload={},
        )
    return lifecycle, True


def create_lifecycle_for_snapshot(
    db: Session,
    snapshot_id: str,
    *,
    requires_human_approval: bool,
    idempotency_key: str,
    expires_at: datetime | None = None,
) -> tuple[DecisionLifecycle, bool]:
    snapshot = db.query(DecisionSnapshot).filter(DecisionSnapshot.id == snapshot_id).first()
    if snapshot is None:
        raise LifecycleTransitionError("Decision snapshot not found")
    return create_decision_lifecycle(
        db,
        snapshot,
        requires_human_approval=requires_human_approval,
        idempotency_key=idempotency_key,
        expires_at=expires_at,
    )
