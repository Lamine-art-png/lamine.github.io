from __future__ import annotations

import pytest

from app.agents.autonomy_runtime import AutonomyConflict, AutonomyForbidden, AutonomousOperationsRuntime
from app.agents.field_intelligence_bridge import enqueue_completed_observation, run_trigger_jobs
from app.agents.models import AgentWorkflowRun
from app.models.field_intelligence import FieldObservation
from app.models.operational_records import IngestionJob
from app.models.saas import Organization, User, Workspace


def _enterprise(db):
    user = User(email="autonomy-owner@example.com", name="Autonomy Owner")
    db.add(user)
    db.flush()
    org = Organization(
        name="Autonomy Test Farm",
        slug="autonomy-test-farm",
        owner_user_id=user.id,
        plan="enterprise",
        subscription_status="active",
        verification_status="approved_legacy",
    )
    db.add(org)
    db.commit()
    return user, org


def _completed_field_evidence(db, org_id: str) -> FieldObservation:
    observation = FieldObservation(
        tenant_id=org_id,
        workspace_id=None,
        field_name="North 12",
        event_type="irrigation_leak",
        severity="high",
        status="completed",
        summary="Leak repaired and normal flow confirmed.",
        confidence=0.98,
        structured_json={"verification": "flow_restored"},
        uncertain_fields_json=[],
        correlation_json={},
        provenance_json={"source": "field_intelligence"},
        task_ids_json=[],
        evidence_ids_json=[],
        audit_json=[],
    )
    db.add(observation)
    db.commit()
    return observation


def test_zero_touch_run_requires_verified_evidence_before_success(db):
    user, org = _enterprise(db)
    runtime = AutonomousOperationsRuntime(db, organization_id=org.id, workspace_id=None, actor_user_id=user.id)

    procedure = runtime.create_procedure(
        name="Field issue resolution",
        domain="field_intelligence",
        autonomy_level=4,
        trigger_type="field_observation",
        definition={"goal": "resolve issue and verify outcome"},
    )
    runtime.set_procedure_status(procedure["id"], "active")

    first = runtime.start_run(
        procedure_id=procedure["id"],
        idempotency_key="field-observation-001",
        source_type="field_observation",
        source_id="source-001",
        payload={"field": "North 12"},
    )
    replay = runtime.start_run(
        procedure_id=procedure["id"],
        idempotency_key="field-observation-001",
        source_type="field_observation",
        source_id="source-001",
        payload={"field": "North 12"},
    )
    assert replay["run"]["id"] == first["run"]["id"]

    action = runtime.plan_action(
        first["run"]["id"],
        action_type="create_field_task",
        idempotency_key="repair-task",
        title="Repair North 12 leak",
        description="Dispatch field crew and close only after proof is attached.",
        risk_level="low",
        payload={"priority": "high"},
    )
    assert action["status"] == "ready"
    assert action["requires_human_approval"] is False

    runtime.begin_action(first["run"]["id"], action["id"])
    runtime.record_action_result(
        first["run"]["id"],
        action["id"],
        succeeded=True,
        result={"task_id": "task-123"},
    )

    with pytest.raises(AutonomyForbidden, match="unfinished or unverified"):
        runtime.complete_run(first["run"]["id"], status_value="succeeded")

    evidence = _completed_field_evidence(db, org.id)
    runtime.verify_action(
        first["run"]["id"],
        action["id"],
        evidence_ids=[evidence.id],
        metadata={"verification": "field follow-up completed"},
    )
    completed = runtime.complete_run(
        first["run"]["id"],
        status_value="succeeded",
        summary="Issue resolved and independently verified.",
        metrics={"time_to_resolution_minutes": 42},
    )

    assert completed["run"]["verified_outcome"] is True
    assert completed["run"]["human_touch_count"] == 0
    command = runtime.command_center()
    assert command["zero_touch_successes"] == 1
    assert command["human_assisted_successes"] == 0
    assert command["autonomous_completion_rate"] == 100.0


def test_critical_physical_action_stops_for_human_approval_and_is_not_zero_touch(db):
    user, org = _enterprise(db)
    runtime = AutonomousOperationsRuntime(db, organization_id=org.id, workspace_id=None, actor_user_id=user.id)
    procedure = runtime.create_procedure(
        name="Closed-loop irrigation",
        domain="water",
        autonomy_level=5,
        trigger_type="threshold",
        definition={"goal": "respond to water risk"},
    )
    runtime.set_procedure_status(procedure["id"], "active")
    run = runtime.start_run(
        procedure_id=procedure["id"],
        idempotency_key="water-event-001",
        source_type="telemetry_threshold",
        source_id="zone-a",
        payload={"soil_vwc": 0.11},
    )
    action = runtime.plan_action(
        run["run"]["id"],
        action_type="request_controller_action",
        idempotency_key="controller-request-001",
        title="Prepare Zone A irrigation action",
        description="Prepare the controller operation under enterprise policy.",
        risk_level="critical",
        payload={"duration_minutes": 90},
    )
    assert action["status"] == "approval_required"

    approved = runtime.decide_action(run["run"]["id"], action["id"], approved=True)
    assert approved["run"]["status"] == "running"
    assert approved["run"]["human_touch_count"] == 1

    runtime.begin_action(run["run"]["id"], action["id"])
    runtime.record_action_result(
        run["run"]["id"], action["id"], succeeded=True, result={"approval_task": "task-controller-1"}
    )
    evidence = _completed_field_evidence(db, org.id)
    runtime.verify_action(run["run"]["id"], action["id"], evidence_ids=[evidence.id])
    runtime.complete_run(run["run"]["id"], status_value="succeeded")

    command = runtime.command_center()
    assert command["zero_touch_successes"] == 0
    assert command["human_assisted_successes"] == 1
    assert command["autonomous_completion_rate"] == 0.0


def test_policy_snapshot_can_force_approval_for_noncritical_action(db):
    user, org = _enterprise(db)
    runtime = AutonomousOperationsRuntime(db, organization_id=org.id, workspace_id=None, actor_user_id=user.id)
    runtime.create_policy(
        name="Finance approval ceiling",
        domain="finance",
        rules={"max_autonomous_amount": 5000},
    )
    procedure = runtime.create_procedure(
        name="Procurement request",
        domain="finance",
        autonomy_level=4,
        trigger_type="inventory_threshold",
        definition={},
    )
    runtime.set_procedure_status(procedure["id"], "active")
    run = runtime.start_run(
        procedure_id=procedure["id"],
        idempotency_key="purchase-001",
        payload={"input": "fertilizer"},
    )
    action = runtime.plan_action(
        run["run"]["id"],
        action_type="create_field_task",
        idempotency_key="purchase-action-001",
        title="Prepare supplier request",
        description="Prepare the purchase workflow.",
        risk_level="medium",
        payload={"amount": 12000},
    )
    assert action["requires_human_approval"] is True
    assert action["status"] == "approval_required"
    assert run["run"]["policy_snapshot_json"]["policies"][0]["name"] == "Finance approval ceiling"


def test_a1_procedure_cannot_create_executable_action(db):
    user, org = _enterprise(db)
    runtime = AutonomousOperationsRuntime(db, organization_id=org.id, workspace_id=None, actor_user_id=user.id)
    procedure = runtime.create_procedure(
        name="Observe only",
        domain="field_intelligence",
        autonomy_level=1,
        trigger_type="field_observation",
        definition={},
    )
    runtime.set_procedure_status(procedure["id"], "active")
    run = runtime.start_run(procedure_id=procedure["id"], idempotency_key="observe-001")
    with pytest.raises(AutonomyForbidden, match="A0/A1"):
        runtime.plan_action(
            run["run"]["id"],
            action_type="create_field_task",
            idempotency_key="should-not-execute",
            title="No execution",
            description="This should remain recommendation-only.",
            risk_level="low",
            payload={},
        )



def test_failed_or_actionless_runs_cannot_be_promoted_to_verified_success(db):
    user, org = _enterprise(db)
    runtime = AutonomousOperationsRuntime(db, organization_id=org.id, workspace_id=None, actor_user_id=user.id)
    procedure = runtime.create_procedure(
        name="Fail closed",
        domain="field_intelligence",
        autonomy_level=4,
        trigger_type="manual",
        definition={},
    )
    runtime.set_procedure_status(procedure["id"], "active")

    empty = runtime.start_run(procedure_id=procedure["id"], idempotency_key="empty-run")
    with pytest.raises(AutonomyForbidden, match="without at least one"):
        runtime.complete_run(empty["run"]["id"], status_value="succeeded")

    failed = runtime.start_run(procedure_id=procedure["id"], idempotency_key="failed-run")
    action = runtime.plan_action(
        failed["run"]["id"],
        action_type="create_field_task",
        idempotency_key="failed-action",
        title="Attempt work",
        description="This action will fail.",
        risk_level="low",
        payload={},
    )
    runtime.begin_action(failed["run"]["id"], action["id"])
    runtime.record_action_result(failed["run"]["id"], action["id"], succeeded=False, result={"error": "boom"})
    with pytest.raises(AutonomyForbidden, match="cannot be promoted"):
        runtime.complete_run(failed["run"]["id"], status_value="succeeded")


def test_unknown_action_type_is_rejected_before_persistence(db):
    user, org = _enterprise(db)
    runtime = AutonomousOperationsRuntime(db, organization_id=org.id, workspace_id=None, actor_user_id=user.id)
    procedure = runtime.create_procedure(
        name="Known adapters only",
        domain="field_intelligence",
        autonomy_level=4,
        trigger_type="manual",
        definition={},
    )
    runtime.set_procedure_status(procedure["id"], "active")
    run = runtime.start_run(procedure_id=procedure["id"], idempotency_key="known-adapters")
    with pytest.raises(AutonomyConflict, match="Unsupported executable action type"):
        runtime.plan_action(
            run["run"]["id"],
            action_type="start_irrigation",
            idempotency_key="unsupported",
            title="Do not persist",
            description="No executable adapter exists for this raw action.",
            risk_level="critical",
            payload={},
        )



def test_workspace_scoped_action_rejects_proof_from_another_workspace(db):
    user, org = _enterprise(db)
    ws_a = Workspace(id="ws-autonomy-a", organization_id=org.id, name="A", mode="live")
    ws_b = Workspace(id="ws-autonomy-b", organization_id=org.id, name="B", mode="live")
    db.add_all([ws_a, ws_b])
    db.commit()
    runtime = AutonomousOperationsRuntime(db, organization_id=org.id, workspace_id=ws_a.id, actor_user_id=user.id)
    procedure = runtime.create_procedure(
        name="Workspace proof",
        domain="field_intelligence",
        autonomy_level=4,
        trigger_type="field_observation",
        definition={},
    )
    runtime.set_procedure_status(procedure["id"], "active")
    run = runtime.start_run(procedure_id=procedure["id"], idempotency_key="workspace-proof-run")
    action = runtime.plan_action(
        run["run"]["id"],
        action_type="create_field_task",
        idempotency_key="workspace-proof-action",
        title="Verify within workspace",
        description="Proof must come from this workspace.",
        risk_level="low",
        payload={},
    )
    runtime.begin_action(run["run"]["id"], action["id"])
    runtime.record_action_result(run["run"]["id"], action["id"], succeeded=True, result={"status": "executed"})

    foreign = FieldObservation(
        tenant_id=org.id,
        workspace_id=ws_b.id,
        field_name="Foreign field",
        event_type="observation",
        status="completed",
        summary="Valid evidence, wrong workspace.",
        confidence=0.99,
        structured_json={},
        uncertain_fields_json=[],
        correlation_json={},
        provenance_json={},
        task_ids_json=[],
        evidence_ids_json=[],
        audit_json=[],
    )
    db.add(foreign)
    db.commit()

    with pytest.raises(AutonomyForbidden, match="unavailable"):
        runtime.verify_action(run["run"]["id"], action["id"], evidence_ids=[foreign.id])



def test_autonomy_rejects_non_idempotent_freeform_adapter_even_when_agentic_surface_supports_it(db):
    user, org = _enterprise(db)
    runtime = AutonomousOperationsRuntime(db, organization_id=org.id, workspace_id=None, actor_user_id=user.id)
    procedure = runtime.create_procedure(
        name="Durable adapters only",
        domain="field_intelligence",
        autonomy_level=4,
        trigger_type="manual",
        definition={},
    )
    runtime.set_procedure_status(procedure["id"], "active")
    run = runtime.start_run(procedure_id=procedure["id"], idempotency_key="durable-only")
    with pytest.raises(AutonomyConflict, match="Unsupported executable action type"):
        runtime.plan_action(
            run["run"]["id"],
            action_type="record_field_update",
            idempotency_key="freeform-write",
            title="Do not write",
            description="Free-form evidence writes are not a durable autonomy adapter in v1.",
            risk_level="low",
            payload={},
        )



def test_completed_field_observation_drives_durable_procedure_to_idempotent_task(db):
    user, org = _enterprise(db)
    workspace = Workspace(id="ws-fi-autonomy-e2e", organization_id=org.id, name="Field Ops", mode="live")
    db.add(workspace)
    db.commit()

    runtime = AutonomousOperationsRuntime(
        db,
        organization_id=org.id,
        workspace_id=workspace.id,
        actor_user_id=user.id,
    )
    procedure = runtime.create_procedure(
        name="Dispatch high-severity field issues",
        domain="field_intelligence",
        autonomy_level=4,
        trigger_type="field_observation",
        definition={"when": {"event_types": ["issue"], "minimum_severity": "high"}},
    )
    runtime.set_procedure_status(procedure["id"], "active")

    observation = FieldObservation(
        tenant_id=org.id,
        workspace_id=workspace.id,
        field_name="North 12",
        block_name="Block A",
        event_type="issue",
        severity="high",
        status="completed",
        summary="Leak detected at west valve.",
        recommended_action="Inspect and repair the west valve.",
        confidence=0.97,
        structured_json={},
        uncertain_fields_json=[],
        correlation_json={},
        provenance_json={"source": "field_intelligence"},
        task_ids_json=[],
        evidence_ids_json=[],
        audit_json=[],
    )
    db.add(observation)
    db.flush()
    trigger = enqueue_completed_observation(db, observation)
    db.commit()
    assert trigger is not None

    first = run_trigger_jobs(db, limit=10, worker_id="autonomy-test-worker")
    assert first["processed"] == 1
    run = (
        db.query(AgentWorkflowRun)
        .filter(
            AgentWorkflowRun.organization_id == org.id,
            AgentWorkflowRun.source_id == observation.id,
        )
        .one()
    )
    assert run.status == "waiting_evidence"
    task = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == org.id,
            IngestionJob.job_type == "field_ops_task",
        )
        .one()
    )
    assert (task.input_json or {}).get("source_autonomy_run_id") == run.id
    assert (task.input_json or {}).get("source_autonomy_action_id")

    # Replay cannot create a second workflow or duplicate field task.
    replay = enqueue_completed_observation(db, observation)
    db.commit()
    assert replay is not None
    run_trigger_jobs(db, limit=10, worker_id="autonomy-test-worker-2")
    assert db.query(AgentWorkflowRun).filter(AgentWorkflowRun.organization_id == org.id).count() == 1
    assert (
        db.query(IngestionJob)
        .filter(IngestionJob.tenant_id == org.id, IngestionJob.job_type == "field_ops_task")
        .count()
        == 1
    )
