from __future__ import annotations

from datetime import datetime

import pytest

from app.models.autonomy import AutonomyEvent
from app.models.operational_records import IngestionJob
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.services.autonomy_runtime import (
    approve_step,
    autonomy_summary,
    complete_step,
    create_custom_procedure,
    list_procedures,
    start_run,
    upsert_policy,
)


def _scope(db, suffix: str = "one"):
    user = User(
        id=f"user-autonomy-{suffix}",
        email=f"autonomy-{suffix}@example.com",
        name="Autonomy Operator",
        password_hash="test",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    org = Organization(
        id=f"org-autonomy-{suffix}",
        name="Autonomy Farms",
        slug=f"autonomy-{suffix}",
        owner_user_id=user.id,
        plan="enterprise",
        subscription_status="active",
    )
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(
        id=f"workspace-autonomy-{suffix}",
        organization_id=org.id,
        name="Autonomous Operations",
        crop="Almonds",
        region="California",
        mode="live",
    )
    db.add_all([user, org, membership, workspace])
    db.commit()
    return user, org, workspace


def test_policy_governance_records_actor_and_before_after_state(db):
    user, org, workspace = _scope(db, "governance")
    first = upsert_policy(
        db, org.id, workspace_id=workspace.id, autonomy_level="A3", actor_user_id=user.id
    )
    second = upsert_policy(
        db, org.id, workspace_id=workspace.id, autonomy_level="A4", actor_user_id=user.id
    )
    events = (
        db.query(AutonomyEvent)
        .filter(
            AutonomyEvent.organization_id == org.id,
            AutonomyEvent.event_type == "autonomy_policy_updated",
        )
        .order_by(AutonomyEvent.created_at.asc())
        .all()
    )
    assert len(events) == 2
    assert all(event.actor == user.id for event in events)
    assert events[0].payload_json["previous"] is None
    assert events[0].payload_json["current"]["autonomy_level"] == "A3"
    assert events[1].payload_json["previous"]["autonomy_level"] == "A3"
    assert events[1].payload_json["current"]["autonomy_level"] == "A4"
    assert first["id"] == second["id"]


def test_trigger_ref_is_idempotent_across_replays(db):
    user, org, workspace = _scope(db, "replay")
    first = start_run(
        db, org.id,
        procedure_key="field_issue_resolution",
        workspace_id=workspace.id,
        trigger_type="field_observation",
        trigger_ref="observation-replayed",
        context={"summary": "Inspect row 7"},
        actor=user.id,
    )
    second = start_run(
        db, org.id,
        procedure_key="field_issue_resolution",
        workspace_id=workspace.id,
        trigger_type="field_observation",
        trigger_ref="observation-replayed",
        context={"summary": "Inspect row 7"},
        actor=user.id,
    )
    assert first["id"] == second["id"]


def test_system_procedures_are_one_runtime_not_separate_products(db):
    _, org, _ = _scope(db)
    procedures = list_procedures(db, org.id)
    keys = {row["procedure_key"] for row in procedures}
    assert {
        "field_issue_resolution",
        "assurance_gap_resolution",
        "irrigation_operations",
        "harvest_operations",
        "finance_procurement_operations",
    }.issubset(keys)


def test_field_issue_links_existing_task_and_closes_only_after_verification(db):
    user, org, workspace = _scope(db)
    task = IngestionJob(
        id="task-existing-field-intelligence",
        tenant_id=org.id,
        workspace_id=workspace.id,
        job_type="field_ops_task",
        status="open",
        input_json={"title": "Inspect leaking emitter", "workspace_id": workspace.id},
        output_json={},
    )
    db.add(task)
    db.commit()

    run = start_run(
        db,
        org.id,
        procedure_key="field_issue_resolution",
        workspace_id=workspace.id,
        trigger_type="field_observation",
        trigger_ref="observation-123",
        context={
            "existing_task_id": task.id,
            "observation_id": "observation-123",
            "summary": "Leak detected in Block A",
        },
        actor=user.id,
    )
    assert run["status"] == "waiting_verification"
    assert run["human_decision_count"] == 0
    db.refresh(task)
    assert task.input_json["autonomy_run_id"] == run["id"]

    verification = run["current_step"]
    closed = complete_step(
        db,
        org.id,
        run["id"],
        verification["id"],
        actor=user.id,
        result={"verified": True, "verification_status": "verified", "evidence_id": "photo-after-repair"},
    )
    assert closed["status"] == "completed"
    assert closed["outcome_status"] == "verified_complete"
    assert closed["verification_status"] == "verified"

    summary = autonomy_summary(db, org.id, workspace.id)
    assert summary["autonomous_completion_rate"] == 100.0
    assert summary["verified_completion_rate"] == 100.0


def test_physical_action_requires_approval_execution_confirmation_and_verification(db):
    user, org, workspace = _scope(db)
    run = start_run(
        db,
        org.id,
        procedure_key="irrigation_operations",
        workspace_id=workspace.id,
        trigger_type="irrigation_decision",
        trigger_ref="decision-42",
        context={"field_name": "North Ranch", "requested_command": "Start irrigation"},
        actor=user.id,
    )
    assert run["status"] == "waiting_approval"
    action = run["current_step"]
    assert action["action_class"] == "physical_control"

    approved = approve_step(db, org.id, run["id"], action["id"], actor_user_id=user.id)
    assert approved["status"] == "waiting_external"
    assert approved["current_step"]["output"]["physical_or_external_action_executed"] is False
    assert approved["human_decision_count"] == 1

    with pytest.raises(ValueError, match="explicitly confirmed"):
        complete_step(db, org.id, run["id"], action["id"], actor=user.id, result={"status": "ok"})

    executed = complete_step(
        db, org.id, run["id"], action["id"], actor=user.id,
        result={"executed": True, "execution_status": "executed", "provider_event_id": "wiseconn-1"},
    )
    assert executed["status"] == "waiting_verification"

    verification = executed["current_step"]
    closed = complete_step(
        db, org.id, run["id"], verification["id"], actor=user.id,
        result={"verified": True, "verification_status": "matched"},
    )
    assert closed["status"] == "completed"
    assert closed["human_decision_count"] == 1
    assert autonomy_summary(db, org.id, workspace.id)["autonomous_completion_rate"] == 0.0


def test_failed_verification_becomes_exception_instead_of_false_success(db):
    user, org, workspace = _scope(db)
    run = start_run(
        db, org.id,
        procedure_key="field_issue_resolution",
        workspace_id=workspace.id,
        trigger_type="field_issue",
        trigger_ref="issue-failed-verification",
        context={"summary": "Inspect pump", "task_title": "Inspect pump"},
        actor=user.id,
    )
    assert run["status"] == "waiting_verification"
    verification = run["current_step"]
    failed = complete_step(
        db, org.id, run["id"], verification["id"], actor=user.id,
        result={"verified": False, "verification_status": "not_verified", "reason": "Leak is still present"},
    )
    assert failed["status"] == "exception"
    assert failed["outcome_status"] == "verification_failed"
    assert failed["completed_at"] is None


def test_a2_policy_cannot_be_upgraded_into_execution_by_clicking_approve(db):
    user, org, workspace = _scope(db, "a2")
    upsert_policy(
        db,
        org.id,
        workspace_id=workspace.id,
        autonomy_level="A2",
        actor_user_id=user.id,
    )
    run = start_run(
        db, org.id,
        procedure_key="field_issue_resolution",
        workspace_id=workspace.id,
        trigger_type="manual",
        context={"summary": "Prepare Block C follow-up"},
        actor=user.id,
    )
    assert run["status"] == "exception"
    assert run["current_step"]["status"] == "blocked_policy"
    assert "requires A3 or higher" in run["failure_reason"]


def test_lower_policy_gates_otherwise_safe_field_dispatch(db):
    user, org, workspace = _scope(db)
    upsert_policy(
        db,
        org.id,
        workspace_id=workspace.id,
        autonomy_level="A3",
        actor_user_id=user.id,
    )
    run = start_run(
        db, org.id,
        procedure_key="field_issue_resolution",
        workspace_id=workspace.id,
        trigger_type="manual",
        context={"summary": "Scout Block B"},
        actor=user.id,
    )
    assert run["status"] == "waiting_approval"
    assert run["current_step"]["step_type"] == "task_dispatch"

    approved = approve_step(db, org.id, run["id"], run["current_step"]["id"], actor_user_id=user.id)
    assert approved["status"] == "waiting_verification"
    assert approved["human_decision_count"] == 1


def test_customer_procedure_versions_and_requires_explicit_close(db):
    _, org, _ = _scope(db)
    with pytest.raises(ValueError, match="final procedure step"):
        create_custom_procedure(
            db, org.id, name="Broken SOP", domain="operations",
            steps=[{"name": "Only step", "type": "checkpoint"}],
        )

    first = create_custom_procedure(
        db,
        org.id,
        name="Packhouse Exception SOP",
        domain="packhouse",
        trigger_types=["manual"],
        steps=[
            {"key": "ground", "name": "Ground exception", "type": "checkpoint"},
            {"key": "close", "name": "Close", "type": "close"},
        ],
    )
    second = create_custom_procedure(
        db,
        org.id,
        name="Packhouse Exception SOP",
        domain="packhouse",
        procedure_key=first["procedure_key"],
        trigger_types=["manual"],
        steps=[
            {"key": "ground", "name": "Ground exception", "type": "checkpoint"},
            {"key": "verify", "name": "Verify", "type": "verification", "action_class": "verification"},
            {"key": "close", "name": "Close", "type": "close"},
        ],
    )
    assert first["version"] == 1
    assert second["version"] == 2
