"""Durable autonomous-operations state machine built on the existing agent ledger.

The runtime deliberately separates four truths:
1. a procedure may recommend work;
2. policy may allow or require approval for that work;
3. an executor may report that the action was performed;
4. Assurance-grade evidence must independently verify the outcome before a
   workflow can be counted as successfully completed.

That separation is the safety boundary for physical agriculture.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.models import (
    AgentActionEvidenceLink,
    AgentActionProposal,
    AgentPolicy,
    AgentProcedure,
    AgentRunAuditEvent,
    AgentWorkflowOutcome,
    AgentWorkflowRun,
)
from app.models.saas import Workspace
from app.services.evidence_reference_validator import (
    EvidenceReferenceError,
    validate_evidence_references,
)


RUN_TERMINAL = {"succeeded", "failed", "cancelled"}
RUN_ACTIVE = {"running", "waiting_approval", "waiting_evidence"}
ACTION_TERMINAL = {"verified", "failed", "rejected", "cancelled"}
EXECUTABLE_ACTION_TYPES = {
    "email_report_to_user",
    "create_field_task",
    "record_field_update",
    "parse_field_message",
    "request_controller_action",
    "integration_readiness_check",
    "collect_missing_evidence",
}
PHYSICAL_OR_REGULATED_ACTIONS = {
    "request_controller_action",
    "start_irrigation",
    "stop_irrigation",
    "change_valve_state",
    "apply_pesticide",
    "apply_fertilizer",
    "file_with_regulator",
    "send_externally",
    "change_legal_status",
}


class AutonomyConflict(ValueError):
    pass


class AutonomyForbidden(ValueError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class AutonomousOperationsRuntime:
    def __init__(self, db: Session, *, organization_id: str, workspace_id: str | None, actor_user_id: str | None):
        self.db = db
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.actor_user_id = actor_user_id
        if workspace_id:
            workspace = (
                db.query(Workspace)
                .filter(Workspace.id == workspace_id, Workspace.organization_id == organization_id)
                .first()
            )
            if not workspace:
                raise AutonomyForbidden("Workspace is unavailable in the active organization")

    def create_procedure(
        self,
        *,
        name: str,
        domain: str,
        autonomy_level: int,
        trigger_type: str,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        if not 0 <= autonomy_level <= 5:
            raise AutonomyConflict("autonomy_level must be between A0 and A5")
        latest = (
            self.db.query(func.max(AgentProcedure.version))
            .filter(
                AgentProcedure.organization_id == self.organization_id,
                AgentProcedure.workspace_id == self.workspace_id,
                AgentProcedure.name == name,
            )
            .scalar()
        )
        row = AgentProcedure(
            id=_id("proc"),
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            name=name.strip()[:180],
            domain=domain.strip().lower()[:80],
            version=int(latest or 0) + 1,
            status="draft",
            autonomy_level=autonomy_level,
            trigger_type=trigger_type.strip().lower()[:80] or "manual",
            definition_json=definition or {},
            created_by=self.actor_user_id,
        )
        self.db.add(row)
        self.db.commit()
        return self._row(row)

    def set_procedure_status(self, procedure_id: str, status_value: str) -> dict[str, Any]:
        if status_value not in {"draft", "active", "disabled"}:
            raise AutonomyConflict("Unsupported procedure status")
        row = self._procedure(procedure_id)
        if status_value == "active":
            # Only one version of the same procedure may execute in a workspace.
            self.db.query(AgentProcedure).filter(
                AgentProcedure.organization_id == self.organization_id,
                AgentProcedure.workspace_id == self.workspace_id,
                AgentProcedure.name == row.name,
                AgentProcedure.id != row.id,
                AgentProcedure.status == "active",
            ).update({"status": "disabled"}, synchronize_session=False)
        row.status = status_value
        row.updated_at = datetime.utcnow()
        self.db.commit()
        return self._row(row)

    def create_policy(self, *, name: str, domain: str, rules: dict[str, Any], enabled: bool = True) -> dict[str, Any]:
        row = AgentPolicy(
            id=_id("policy"),
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            name=name.strip()[:180],
            domain=domain.strip().lower()[:80],
            enabled=enabled,
            rules_json=rules or {},
            created_by=self.actor_user_id,
        )
        self.db.add(row)
        self.db.commit()
        return self._row(row)

    def start_run(
        self,
        *,
        procedure_id: str,
        idempotency_key: str,
        source_type: str | None = None,
        source_id: str | None = None,
        payload: dict[str, Any] | None = None,
        priority: str = "normal",
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise AutonomyConflict("idempotency_key is required")
        existing = (
            self.db.query(AgentWorkflowRun)
            .filter(
                AgentWorkflowRun.organization_id == self.organization_id,
                AgentWorkflowRun.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing:
            return self.run(existing.id)

        procedure = self._procedure(procedure_id)
        if procedure.status != "active":
            raise AutonomyForbidden("Only active procedures can execute")
        policy_snapshot = self._policy_snapshot(procedure.domain)
        run = AgentWorkflowRun(
            id=_id("run"),
            tenant_id=None,
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            procedure_id=procedure.id,
            procedure_version=procedure.version,
            workflow_type=f"autonomy:{procedure.domain}",
            source_type=(source_type or "manual")[:80],
            source_id=(source_id or None),
            status="running",
            priority=priority if priority in {"low", "normal", "high", "critical"} else "normal",
            autonomy_level=procedure.autonomy_level,
            current_step="triggered",
            idempotency_key=idempotency_key[:180],
            policy_snapshot_json=policy_snapshot,
            actor=self.actor_user_id or "system",
            payload=payload or {},
            result={"procedure_name": procedure.name, "procedure_version": procedure.version},
            requires_human_approval=False,
        )
        self.db.add(run)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = (
                self.db.query(AgentWorkflowRun)
                .filter(
                    AgentWorkflowRun.organization_id == self.organization_id,
                    AgentWorkflowRun.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing:
                return self.run(existing.id)
            raise
        self._audit(run, "run_started", {"source_type": source_type, "source_id": source_id})
        self.db.commit()
        return self.run(run.id)

    def plan_action(
        self,
        run_id: str,
        *,
        action_type: str,
        idempotency_key: str,
        title: str,
        description: str,
        risk_level: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id)
        if run.status not in {"running", "waiting_evidence"}:
            raise AutonomyConflict(f"Cannot plan an action while run is {run.status}")
        if action_type not in EXECUTABLE_ACTION_TYPES:
            raise AutonomyConflict(f"Unsupported executable action type: {action_type}")
        if run.autonomy_level <= 1:
            raise AutonomyForbidden("A0/A1 procedures may observe or recommend but cannot create executable actions")
        existing = (
            self.db.query(AgentActionProposal)
            .filter(AgentActionProposal.run_id == run.id, AgentActionProposal.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return self._row(existing)

        normalized_risk = risk_level if risk_level in {"low", "medium", "high", "critical"} else "high"
        requires_approval = self._requires_approval(run, action_type, normalized_risk, payload or {})
        action = AgentActionProposal(
            id=_id("act"),
            tenant_id=None,
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            run_id=run.id,
            workflow_type=run.workflow_type,
            action_type=action_type[:100],
            idempotency_key=idempotency_key[:180],
            status="approval_required" if requires_approval else "ready",
            execution_status="not_started",
            verification_status="not_required",
            risk_level=normalized_risk,
            priority=run.priority,
            actor=self.actor_user_id or "system",
            payload={
                "id": _id("action_payload"),
                "action_type": action_type,
                "title": title[:240],
                "description": description[:2000],
                "risk_level": normalized_risk,
                "payload": payload or {},
            },
            result={},
            execution_result_json={},
            requires_human_approval=requires_approval,
        )
        run.current_step = f"action:{action_type}"
        run.requires_human_approval = requires_approval
        if requires_approval:
            run.status = "waiting_approval"
        elif run.status == "waiting_evidence":
            run.status = "running"
        self.db.add(action)
        self._audit(run, "action_planned", {"action_id": action.id, "action_type": action_type, "requires_approval": requires_approval})
        self.db.commit()
        return self._row(action)

    def decide_action(self, run_id: str, action_id: str, *, approved: bool) -> dict[str, Any]:
        run = self._run(run_id)
        action = self._action(run, action_id)
        if action.status != "approval_required":
            raise AutonomyConflict("Action is not waiting for approval")
        run.human_touch_count = int(run.human_touch_count or 0) + 1
        run.requires_human_approval = False
        action.approved_by = self.actor_user_id or "user"
        action.approved_at = datetime.utcnow()
        if approved:
            action.status = "ready"
            run.status = "running"
            decision = "approved"
        else:
            action.status = "rejected"
            action.execution_status = "rejected"
            run.status = "failed"
            run.completed_at = datetime.utcnow()
            decision = "rejected"
        self._audit(run, "action_decision", {"action_id": action.id, "decision": decision})
        self.db.commit()
        return self.run(run.id)

    def begin_action(self, run_id: str, action_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        action = self._action(run, action_id)
        if action.status != "ready" or action.execution_status != "not_started":
            raise AutonomyConflict("Action is not ready to execute")
        action.execution_status = "executing"
        action.status = "executing"
        run.current_step = f"executing:{action.action_type or 'action'}"
        self._audit(run, "action_execution_started", {"action_id": action.id})
        self.db.commit()
        return self._row(action)

    def record_action_result(
        self,
        run_id: str,
        action_id: str,
        *,
        succeeded: bool,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id)
        action = self._action(run, action_id)
        if action.execution_status not in {"executing", "not_started"}:
            raise AutonomyConflict("Action execution result has already been recorded")
        action.executed_at = datetime.utcnow()
        action.execution_result_json = result or {}
        if not succeeded:
            action.execution_status = "failed"
            action.status = "failed"
            action.verification_status = "not_verified"
            run.status = "failed"
            run.completed_at = datetime.utcnow()
            self._audit(run, "action_execution_failed", {"action_id": action.id, "result": result or {}})
        else:
            action.execution_status = "succeeded"
            action.status = "waiting_evidence"
            action.verification_status = "pending"
            run.status = "waiting_evidence"
            run.current_step = f"verify:{action.action_type or 'action'}"
            self._audit(run, "action_executed_waiting_evidence", {"action_id": action.id})
        self.db.commit()
        return self.run(run.id)

    def verify_action(
        self,
        run_id: str,
        action_id: str,
        *,
        evidence_ids: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id)
        action = self._action(run, action_id)
        if action.execution_status != "succeeded":
            raise AutonomyConflict("Only successfully executed actions can be verified")
        try:
            validated = validate_evidence_references(
                self.db,
                tenant_id=self.organization_id,
                evidence_ids=evidence_ids,
            )
        except EvidenceReferenceError as exc:
            raise AutonomyForbidden(str(exc)) from exc

        for reference in validated:
            existing = (
                self.db.query(AgentActionEvidenceLink)
                .filter(
                    AgentActionEvidenceLink.action_id == action.id,
                    AgentActionEvidenceLink.evidence_type == reference.evidence_type,
                    AgentActionEvidenceLink.evidence_id == reference.evidence_id,
                )
                .first()
            )
            if not existing:
                self.db.add(
                    AgentActionEvidenceLink(
                        id=_id("proof"),
                        organization_id=self.organization_id,
                        workspace_id=self.workspace_id,
                        run_id=run.id,
                        action_id=action.id,
                        evidence_type=reference.evidence_type,
                        evidence_id=reference.evidence_id,
                        verification_status="verified",
                        metadata_json=metadata or {},
                        verified_by=self.actor_user_id or "system",
                    )
                )
        action.verification_status = "verified"
        action.status = "verified"
        if not self._unverified_successful_actions(run.id, excluding_action_id=action.id):
            run.status = "running"
            run.current_step = "verified"
        self._audit(run, "action_verified", {"action_id": action.id, "evidence_ids": evidence_ids})
        self.db.commit()
        return self.run(run.id)

    def complete_run(
        self,
        run_id: str,
        *,
        status_value: str,
        summary: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id)
        if status_value not in {"succeeded", "failed", "cancelled"}:
            raise AutonomyConflict("Unsupported terminal status")
        existing = self.db.query(AgentWorkflowOutcome).filter_by(run_id=run.id).first()
        if existing:
            return self.run(run.id)
        if status_value == "succeeded":
            if run.status in {"failed", "cancelled"}:
                raise AutonomyForbidden(f"A {run.status} workflow cannot be promoted to verified success")
            actions = (
                self.db.query(AgentActionProposal)
                .filter(AgentActionProposal.run_id == run.id)
                .all()
            )
            if not actions:
                raise AutonomyForbidden("Workflow cannot succeed without at least one executed and verified action")
            failed_actions = [
                row.id for row in actions
                if row.status in {"failed", "rejected", "cancelled"}
                or row.execution_status in {"failed", "rejected"}
            ]
            if failed_actions:
                raise AutonomyForbidden("Workflow cannot succeed after an action failed, was rejected, or was cancelled")
            unfinished = [
                row.id for row in actions
                if row.status in {"proposed", "approval_required", "ready", "executing", "waiting_evidence"}
            ]
            if unfinished:
                raise AutonomyForbidden("Workflow cannot succeed while actions remain unfinished or unverified")
            if self._unverified_successful_actions(run.id):
                raise AutonomyForbidden("Workflow cannot succeed until Assurance-grade evidence verifies every executed action")
            not_verified = [
                row.id for row in actions
                if row.status != "verified"
                or row.execution_status != "succeeded"
                or row.verification_status != "verified"
            ]
            if not_verified:
                raise AutonomyForbidden("Workflow cannot succeed unless every action has a verified successful outcome")
            run.verified_outcome = True
        else:
            run.verified_outcome = False
        run.status = status_value
        run.completed_at = datetime.utcnow()
        run.requires_human_approval = False
        run.current_step = "completed"
        outcome = AgentWorkflowOutcome(
            id=_id("outcome"),
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            run_id=run.id,
            status=status_value,
            summary=(summary or "")[:4000] or None,
            metrics_json=metrics or {},
        )
        self.db.add(outcome)
        self._audit(run, "run_completed", {"status": status_value, "verified_outcome": run.verified_outcome})
        self.db.commit()
        return self.run(run.id)

    def run(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        actions = (
            self.db.query(AgentActionProposal)
            .filter(AgentActionProposal.run_id == run.id)
            .order_by(AgentActionProposal.created_at.asc())
            .all()
        )
        links = (
            self.db.query(AgentActionEvidenceLink)
            .filter(AgentActionEvidenceLink.run_id == run.id)
            .order_by(AgentActionEvidenceLink.verified_at.asc())
            .all()
        )
        outcome = self.db.query(AgentWorkflowOutcome).filter_by(run_id=run.id).first()
        return {
            "run": self._row(run),
            "actions": [self._row(row) for row in actions],
            "evidence_links": [self._row(row) for row in links],
            "outcome": self._row(outcome) if outcome else None,
        }

    def command_center(self) -> dict[str, Any]:
        query = self.db.query(AgentWorkflowRun).filter(AgentWorkflowRun.organization_id == self.organization_id)
        if self.workspace_id:
            query = query.filter(AgentWorkflowRun.workspace_id == self.workspace_id)
        runs = query.order_by(AgentWorkflowRun.created_at.desc()).limit(200).all()
        successful = [row for row in runs if row.status == "succeeded" and row.verified_outcome]
        zero_touch = [row for row in successful if int(row.human_touch_count or 0) == 0]
        assisted = [row for row in successful if int(row.human_touch_count or 0) > 0]
        active = [row for row in runs if row.status in RUN_ACTIVE]
        denominator = len(successful)
        return {
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "active_runs": len(active),
            "waiting_approval": sum(1 for row in active if row.status == "waiting_approval"),
            "waiting_evidence": sum(1 for row in active if row.status == "waiting_evidence"),
            "verified_successes": len(successful),
            "zero_touch_successes": len(zero_touch),
            "human_assisted_successes": len(assisted),
            "autonomous_completion_rate": round((len(zero_touch) / denominator * 100.0), 2) if denominator else 0.0,
            "recent_runs": [self._row(row) for row in runs[:30]],
        }

    def _requires_approval(self, run: AgentWorkflowRun, action_type: str, risk_level: str, payload: dict[str, Any]) -> bool:
        if run.autonomy_level <= 3:
            return True
        if risk_level == "critical" or action_type in PHYSICAL_OR_REGULATED_ACTIONS:
            return True
        snapshot = run.policy_snapshot_json or {}
        for policy in snapshot.get("policies", []):
            rules = policy.get("rules") or {}
            if action_type in set(rules.get("always_require_approval_for") or []):
                return True
            if risk_level in set(rules.get("approval_required_risks") or []):
                return True
            amount = payload.get("amount")
            threshold = rules.get("max_autonomous_amount")
            if isinstance(amount, (int, float)) and isinstance(threshold, (int, float)) and amount > threshold:
                return True
        return False

    def _policy_snapshot(self, domain: str) -> dict[str, Any]:
        query = self.db.query(AgentPolicy).filter(
            AgentPolicy.organization_id == self.organization_id,
            AgentPolicy.domain == domain,
            AgentPolicy.enabled.is_(True),
        )
        policies = query.filter(
            (AgentPolicy.workspace_id == self.workspace_id) | (AgentPolicy.workspace_id.is_(None))
        ).order_by(AgentPolicy.created_at.asc()).all()
        return {
            "captured_at": datetime.utcnow().isoformat() + "Z",
            "policies": [
                {"id": row.id, "name": row.name, "domain": row.domain, "rules": row.rules_json or {}}
                for row in policies
            ],
        }

    def _unverified_successful_actions(self, run_id: str, excluding_action_id: str | None = None) -> list[str]:
        query = self.db.query(AgentActionProposal).filter(
            AgentActionProposal.run_id == run_id,
            AgentActionProposal.execution_status == "succeeded",
            AgentActionProposal.verification_status != "verified",
        )
        if excluding_action_id:
            query = query.filter(AgentActionProposal.id != excluding_action_id)
        return [row.id for row in query.all()]

    def _procedure(self, procedure_id: str) -> AgentProcedure:
        row = (
            self.db.query(AgentProcedure)
            .filter(
                AgentProcedure.id == procedure_id,
                AgentProcedure.organization_id == self.organization_id,
            )
            .first()
        )
        if not row or (row.workspace_id and row.workspace_id != self.workspace_id):
            raise AutonomyForbidden("Procedure is unavailable in the active workspace")
        return row

    def _run(self, run_id: str) -> AgentWorkflowRun:
        row = (
            self.db.query(AgentWorkflowRun)
            .filter(
                AgentWorkflowRun.id == run_id,
                AgentWorkflowRun.organization_id == self.organization_id,
            )
            .first()
        )
        if not row:
            raise AutonomyForbidden("Workflow run is unavailable in the active workspace")
        if row.workspace_id != self.workspace_id:
            if self.workspace_id is None and row.workspace_id is not None:
                # Omitted workspace scope resolves to the run's immutable scope;
                # it never means "use the organization's first workspace".
                self.workspace_id = row.workspace_id
            else:
                raise AutonomyForbidden("Workflow run is unavailable in the active workspace")
        return row

    def _action(self, run: AgentWorkflowRun, action_id: str) -> AgentActionProposal:
        row = (
            self.db.query(AgentActionProposal)
            .filter(
                AgentActionProposal.id == action_id,
                AgentActionProposal.run_id == run.id,
                AgentActionProposal.organization_id == self.organization_id,
            )
            .first()
        )
        if not row or row.workspace_id != run.workspace_id:
            raise AutonomyForbidden("Action is unavailable in the active workflow")
        return row

    def _audit(self, run: AgentWorkflowRun, event: str, details: dict[str, Any]) -> None:
        self.db.add(
            AgentRunAuditEvent(
                id=_id("audit"),
                tenant_id=None,
                organization_id=self.organization_id,
                workspace_id=self.workspace_id,
                run_id=run.id,
                workflow_type=run.workflow_type,
                status="recorded",
                priority=run.priority,
                actor=self.actor_user_id or "system",
                payload={"event": event, **details},
                result={},
                requires_human_approval=False,
            )
        )

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}
