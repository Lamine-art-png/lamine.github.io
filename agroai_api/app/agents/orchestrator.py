"""Deterministic agent orchestration grounded in stored AGRO-AI records."""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.models import (
    AgentActionProposal,
    AgentFinding,
    AgentMessage,
    AgentRecommendation,
    AgentRunAuditEvent,
    AgentTask,
    AgentToolCall,
    AgentWorkflowRun,
)
from app.assurance.models import AssuranceEvidenceArtifact, HarvestLot, InputApplication, TraceabilityEvent
from app.assurance.repository import AssuranceRepository


WORKFLOW_TYPES = {
    "assurance_audit",
    "missing_proof_triage",
    "waterops_readiness",
    "irrigation_decision_review",
    "buyer_proof_pack",
    "lender_risk_pack",
}

HUMAN_APPROVAL_ACTIONS = {
    "approve_irrigation_schedule",
    "ready_for_external_submission",
    "send_externally",
    "file_with_regulator",
    "mark_certified",
    "mark_compliant",
    "delete_evidence",
    "change_legal_status",
}

SAFE_ACTIONS = {
    "create_passport",
    "attach_evidence",
    "classify_evidence",
    "request_missing_document",
    "create_input_application",
    "create_harvest_lot",
    "create_traceability_event",
    "refresh_readiness",
    "generate_pdf_export",
    "generate_buyer_pack",
    "generate_waterops_pack",
    "ask_human_for_scope",
    "mark_needs_review",
}


class LLMAdapter:
    """Optional summary adapter. It never changes evidence facts."""

    def available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY") or os.getenv("LLM_PROVIDER"))

    def rewrite_summary(self, summary: str, facts: dict[str, Any]) -> str:
        return summary


class AgentOrchestrator:
    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.assurance = AssuranceRepository(db, tenant_id)
        self.llm = LLMAdapter()

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_type = payload.get("workflow_type", "assurance_audit")
        if workflow_type not in WORKFLOW_TYPES:
            raise ValueError(f"Unsupported workflow_type: {workflow_type}")
        if payload.get("passport_id"):
            return self.triage_passport(payload["passport_id"], workflow_type=workflow_type, actor=payload.get("actor", "user"), payload=payload)
        result = self._default_result(
            summary="AGRO-AI needs a passport or workbench session before it can ground this workflow.",
            missing_proof=[{"requirement_key": "workspace_scope", "suggested_action": "Select an Assurance Passport or Workbench session."}],
            recommended_actions=[self._action("ask_human_for_scope", "Select workspace scope", "Choose the passport or session to review.", True)],
        )
        return self._persist_run(workflow_type, payload, result, actor=payload.get("actor", "user"))

    def triage_passport(self, passport_id: str, *, workflow_type: str = "assurance_audit", actor: str = "system", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if workflow_type not in WORKFLOW_TYPES:
            raise ValueError(f"Unsupported workflow_type: {workflow_type}")
        passport_package = self.assurance.get_passport(passport_id)
        passport = passport_package["passport"]
        readiness = self.assurance.readiness(passport_id)
        evidence = passport_package["evidence"]
        input_apps = passport_package["input_applications"]
        harvest_lots = passport_package["harvest_lots"]
        trace_events = passport_package["traceability_events"]

        proof_present = [{"type": row["evidence_type"], "id": row["id"], "domain": row["proof_domain"]} for row in evidence]
        missing_proof = [
            {
                "requirement_key": item["requirement_key"],
                "domain": item["section_type"],
                "severity": item["severity"],
                "needed_evidence": item.get("needed_evidence_types", []),
                "suggested_action": "Attach evidence or mark for reviewer follow-up.",
                "grounded_by": [item["rule_pack_id"], item["requirement_key"]],
            }
            for item in readiness["missing_evidence"]
        ]
        risk_flags = []
        if readiness.get("status") == "needs_scope_review":
            risk_flags.append({
                "severity": "required",
                "summary": "Passport scope needs review before unrelated tenant assets can be excluded confidently.",
                "grounded_by": readiness["scope"].get("missing_scope", []),
            })
        if readiness.get("risk_level") in {"medium", "high"}:
            risk_flags.append({
                "severity": readiness["risk_level"],
                "summary": f"Readiness risk is {readiness['risk_level']} based on missing proof.",
                "grounded_by": ["readiness_score"],
            })

        automation_plan = [
            self._action("refresh_readiness", "Refresh readiness", "Recalculate missing proof using passport-scoped evidence.", False),
            self._action("generate_pdf_export", "Draft Assurance PDF", "Prepare an audit readiness evidence package for reviewer evaluation.", False),
        ]
        if readiness.get("status") == "needs_scope_review":
            automation_plan.insert(0, self._action("ask_human_for_scope", "Confirm passport scope", "Add parcel IDs or reporting period before relying on WaterOps records.", True))
        recommended_actions = list(automation_plan)
        for item in missing_proof[:5]:
            recommended_actions.append(self._action("request_missing_document", f"Request {item['requirement_key']}", "Collect the missing proof from the farm team.", False, grounded_by=item["grounded_by"]))

        next_best_action = recommended_actions[0] if recommended_actions else self._action("mark_needs_review", "Send to reviewer", "Review the evidence package before external use.", True)
        summary = (
            f"AGRO-AI reviewed {passport.get('farm_name')} for audit readiness. "
            f"It found {len(proof_present)} evidence artifact(s), {len(input_apps)} input record(s), "
            f"{len(harvest_lots)} harvest lot(s), and {len(trace_events)} traceability event(s)."
        )
        result = self._default_result(
            summary=self.llm.rewrite_summary(summary, {"readiness": readiness}) if self.llm.available() else summary,
            findings=[
                {"summary": "Proof present", "severity": "info", "evidence_reference": [row["id"] for row in evidence], "confidence": 1.0},
                {"summary": "Missing proof detected" if missing_proof else "No missing checklist proof detected", "severity": "required" if missing_proof else "info", "evidence_reference": [item["requirement_key"] for item in readiness["missing_evidence"]], "confidence": 1.0},
            ],
            missing_proof=missing_proof,
            risk_flags=risk_flags,
            recommended_actions=recommended_actions,
            automation_plan=automation_plan,
            human_approval_required=any(action["requires_human_approval"] for action in recommended_actions),
            confidence=0.92,
            truth_constraints=[
                "Audit readiness only; not a certification, approval, legal determination, or direct filing.",
                "No live-source completeness claim unless a configured live source supplied the record.",
                "LLM summary text cannot override stored evidence facts.",
            ],
            extra={
                "passport": passport,
                "readiness": readiness,
                "proof_present": proof_present,
                "next_best_action": next_best_action,
                "suggested_report": {"type": "assurance_passport_pdf", "action": "generate_pdf_export", "status": "draft_ready"},
            },
        )
        return self._persist_run(workflow_type, payload or {"passport_id": passport_id}, result, passport_id=passport_id, actor=actor)

    def triage_workbench_session(self, session_id: str, *, actor: str = "system") -> dict[str, Any]:
        result = self._default_result(
            summary="AGRO-AI can classify uploaded Workbench records and attach them to an Assurance Passport when scope is provided.",
            findings=[{"summary": "Workbench session selected", "severity": "info", "evidence_reference": [session_id], "confidence": 0.9}],
            missing_proof=[],
            risk_flags=[{"severity": "needs_review", "summary": "Workbench triage needs a linked Assurance Passport for audit readiness scoring.", "grounded_by": [session_id]}],
            recommended_actions=[self._action("ask_human_for_scope", "Link Assurance Passport", "Select or create a passport before evidence is used for readiness.", True)],
            automation_plan=[self._action("classify_evidence", "Classify uploaded records", "Infer evidence categories from uploaded filenames and metadata.", False)],
            human_approval_required=True,
            confidence=0.75,
            truth_constraints=["Workbench triage is draft classification only until attached to a passport."],
            extra={"workbench_session_id": session_id},
        )
        return self._persist_run("missing_proof_triage", {"workbench_session_id": session_id}, result, workbench_session_id=session_id, actor=actor)

    def action_decision(self, run_id: str, action_id: str, *, approved: bool, actor: str = "user") -> dict[str, Any]:
        run = self.db.query(AgentWorkflowRun).filter_by(id=run_id, tenant_id=self.tenant_id).first()
        if not run:
            raise KeyError("Agent run not found")
        action = self.db.query(AgentActionProposal).filter_by(id=action_id, run_id=run_id, tenant_id=self.tenant_id).first()
        if not action:
            raise KeyError("Agent action not found")
        action.status = "approved" if approved else "rejected"
        action.approved_by = actor if approved else None
        action.approved_at = datetime.utcnow() if approved else None
        action.updated_at = datetime.utcnow()
        self.db.add(AgentRunAuditEvent(
            id=f"age-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            run_id=run_id,
            passport_id=run.passport_id,
            workbench_session_id=run.workbench_session_id,
            workflow_type=run.workflow_type,
            actor=actor,
            payload={"action_id": action_id, "decision": action.status},
            result={"requires_human_approval": action.requires_human_approval},
        ))
        self.db.commit()
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.db.query(AgentWorkflowRun).filter_by(id=run_id, tenant_id=self.tenant_id).first()
        if not run:
            raise KeyError("Agent run not found")
        return self._run_payload(run)

    def list_runs(self, passport_id: str | None = None) -> list[dict[str, Any]]:
        query = self.db.query(AgentWorkflowRun).filter_by(tenant_id=self.tenant_id)
        if passport_id:
            query = query.filter_by(passport_id=passport_id)
        return [self._run_payload(row) for row in query.order_by(AgentWorkflowRun.created_at.desc()).all()]

    def _default_result(self, *, summary: str, findings: list[dict[str, Any]] | None = None, missing_proof: list[dict[str, Any]] | None = None, risk_flags: list[dict[str, Any]] | None = None, recommended_actions: list[dict[str, Any]] | None = None, automation_plan: list[dict[str, Any]] | None = None, human_approval_required: bool = False, confidence: float = 0.8, truth_constraints: list[str] | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        result = {
            "summary": summary,
            "findings": findings or [],
            "missing_proof": missing_proof or [],
            "risk_flags": risk_flags or [],
            "recommended_actions": recommended_actions or [],
            "automation_plan": automation_plan or [],
            "human_approval_required": human_approval_required,
            "confidence": confidence,
            "truth_constraints": truth_constraints or [],
        }
        result.update(extra or {})
        return result

    def _action(self, action_type: str, title: str, rationale: str, requires_approval: bool, grounded_by: list[str] | None = None) -> dict[str, Any]:
        if action_type not in SAFE_ACTIONS and action_type not in HUMAN_APPROVAL_ACTIONS:
            raise ValueError(f"Unsupported agent action: {action_type}")
        return {
            "id": f"act-{uuid.uuid4().hex[:12]}",
            "action_type": action_type,
            "title": title,
            "rationale": rationale,
            "requires_human_approval": requires_approval or action_type in HUMAN_APPROVAL_ACTIONS,
            "grounded_by": grounded_by or [],
            "status": "proposed",
        }

    def _persist_run(self, workflow_type: str, payload: dict[str, Any], result: dict[str, Any], *, passport_id: str | None = None, workbench_session_id: str | None = None, actor: str = "system") -> dict[str, Any]:
        run = AgentWorkflowRun(
            id=f"run-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            passport_id=passport_id,
            workbench_session_id=workbench_session_id,
            workflow_type=workflow_type,
            status="needs_review" if result["human_approval_required"] else "completed",
            priority="normal",
            actor=actor,
            payload=payload,
            result=result,
            requires_human_approval=result["human_approval_required"],
        )
        self.db.add(run)
        self.db.flush()
        self.db.add(AgentTask(
            id=f"agt-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            run_id=run.id,
            passport_id=passport_id,
            workbench_session_id=workbench_session_id,
            workflow_type=workflow_type,
            actor=actor,
            payload={"task": "deterministic_triage"},
            result={"status": "completed"},
        ))
        for finding in result["findings"]:
            self.db.add(AgentFinding(
                id=f"agf-{uuid.uuid4().hex[:12]}",
                tenant_id=self.tenant_id,
                run_id=run.id,
                passport_id=passport_id,
                workbench_session_id=workbench_session_id,
                workflow_type=workflow_type,
                payload=finding,
                result=finding,
            ))
        for recommendation in result["recommended_actions"]:
            self.db.add(AgentRecommendation(
                id=f"agr-{uuid.uuid4().hex[:12]}",
                tenant_id=self.tenant_id,
                run_id=run.id,
                passport_id=passport_id,
                workbench_session_id=workbench_session_id,
                workflow_type=workflow_type,
                payload=recommendation,
                result=recommendation,
                requires_human_approval=recommendation["requires_human_approval"],
            ))
            self.db.add(AgentActionProposal(
                id=recommendation["id"],
                tenant_id=self.tenant_id,
                run_id=run.id,
                passport_id=passport_id,
                workbench_session_id=workbench_session_id,
                workflow_type=workflow_type,
                payload=recommendation,
                result=recommendation,
                requires_human_approval=recommendation["requires_human_approval"],
            ))
        self.db.add(AgentToolCall(
            id=f"agc-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            run_id=run.id,
            passport_id=passport_id,
            workbench_session_id=workbench_session_id,
            workflow_type=workflow_type,
            payload={"tool": "assurance_readiness" if passport_id else "workbench_triage"},
            result={"status": "completed"},
        ))
        self.db.add(AgentMessage(
            id=f"agm-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            run_id=run.id,
            passport_id=passport_id,
            workbench_session_id=workbench_session_id,
            workflow_type=workflow_type,
            payload={"role": "agent", "content": result["summary"]},
            result={"truth_constraints": result["truth_constraints"]},
        ))
        self.db.add(AgentRunAuditEvent(
            id=f"age-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            run_id=run.id,
            passport_id=passport_id,
            workbench_session_id=workbench_session_id,
            workflow_type=workflow_type,
            actor=actor,
            payload={"event": "run_created"},
            result={"status": run.status},
        ))
        self.db.commit()
        return self.get_run(run.id)

    def _run_payload(self, run: AgentWorkflowRun) -> dict[str, Any]:
        actions = self.db.query(AgentActionProposal).filter_by(tenant_id=self.tenant_id, run_id=run.id).all()
        messages = self.db.query(AgentMessage).filter_by(tenant_id=self.tenant_id, run_id=run.id).all()
        return {
            "id": run.id,
            "tenant_id": run.tenant_id,
            "passport_id": run.passport_id,
            "workbench_session_id": run.workbench_session_id,
            "workflow_type": run.workflow_type,
            "status": run.status,
            "priority": run.priority,
            "created_at": run.created_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
            "actor": run.actor,
            "payload": run.payload,
            "result": run.result,
            "findings": run.result.get("findings", []),
            "recommendations": run.result.get("recommended_actions", []),
            "proposed_actions": [{**row.payload, "id": row.id, "status": row.status} for row in actions],
            "automation_plan": run.result.get("automation_plan", []),
            "messages": [{"id": row.id, **row.payload, "created_at": row.created_at.isoformat()} for row in messages],
            "requires_human_approval": run.requires_human_approval,
            "approved_by": run.approved_by,
            "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        }

