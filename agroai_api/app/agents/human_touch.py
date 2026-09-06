"""Human-intervention accounting for Autonomous Completion Rate.

Interactive portal actions are not zero-touch autonomy. This helper records an
immutable audit event and increments the run's cumulative human-touch counter.
Server-side workers do not call it, so fully automated runs remain zero-touch.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.models import AgentRunAuditEvent, AgentWorkflowRun


def record_human_touch(
    db: Session,
    *,
    organization_id: str,
    workspace_id: str | None,
    run_id: str,
    actor_user_id: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> AgentWorkflowRun:
    run = (
        db.query(AgentWorkflowRun)
        .filter(
            AgentWorkflowRun.id == run_id,
            AgentWorkflowRun.organization_id == organization_id,
        )
        .first()
    )
    if not run or (workspace_id and run.workspace_id != workspace_id):
        raise ValueError("Workflow run is unavailable in the active workspace")

    run.human_touch_count = int(run.human_touch_count or 0) + 1
    run.updated_at = datetime.utcnow()
    db.add(
        AgentRunAuditEvent(
            id=f"audit_{uuid.uuid4().hex[:20]}",
            tenant_id=None,
            organization_id=organization_id,
            workspace_id=run.workspace_id,
            run_id=run.id,
            workflow_type=run.workflow_type,
            status="recorded",
            priority=run.priority,
            actor=actor_user_id,
            payload={"event": "human_touch", "reason": reason, **(details or {})},
            result={},
            requires_human_approval=False,
        )
    )
    db.commit()
    db.refresh(run)
    return run
