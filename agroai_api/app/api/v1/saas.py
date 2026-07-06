from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_org_membership, require_workspace_access
from app.api.v1.auth import _unique_slug
from app.db.base import get_db
from app.models.saas import Organization, OrganizationMembership, UsageEvent, User, Workspace
from app.services.entitlements import (
    assert_can_create_workspace,
    assert_can_export_reports,
    require_owner_or_admin,
    require_feature,
    require_workspace_mode,
    serialize_entitlements,
)
from app.services.quota import QuotaService

router = APIRouter(tags=["saas"])


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2)


class WorkspaceCreate(BaseModel):
    organization_id: str | None = None
    name: str = Field(min_length=2)
    crop: str | None = None
    region: str | None = None
    mode: str = "evaluation"


def _workspace_payload(workspace: Workspace) -> dict:
    return {
        "id": workspace.id,
        "organization_id": workspace.organization_id,
        "name": workspace.name,
        "crop": workspace.crop,
        "region": workspace.region,
        "mode": workspace.mode,
        "created_at": workspace.created_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat(),
    }


@router.post("/orgs", status_code=status.HTTP_201_CREATED)
def create_org(payload: OrganizationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    org = Organization(name=payload.name, slug=_unique_slug(db, payload.name), owner_user_id=user.id)
    db.add(org)
    db.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(organization_id=org.id, name="Evaluation workspace", mode="evaluation")
    db.add_all([membership, workspace])
    db.commit()
    db.refresh(org)
    return {"organization": {"id": org.id, "name": org.name, "slug": org.slug, "plan": serialize_entitlements(org, db)["plan"], "subscription_status": org.subscription_status}}


@router.get("/orgs")
def list_orgs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    memberships = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user.id)
        .order_by(OrganizationMembership.created_at.asc())
        .all()
    )
    return {
        "organizations": [
            {
                "id": m.organization.id,
                "name": m.organization.name,
                "slug": m.organization.slug,
                "plan": serialize_entitlements(m.organization, db)["plan"],
                "subscription_status": m.organization.subscription_status,
                "role": m.role,
            }
            for m in memberships
        ]
    }


@router.post("/orgs/{org_id}/switch")
def switch_org(org_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    org, membership = require_org_membership(org_id, user, db)
    return {
        "current_organization": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "plan": serialize_entitlements(org, db)["plan"],
            "subscription_status": org.subscription_status,
            "role": membership.role,
        },
        "entitlements": serialize_entitlements(org, db),
    }


@router.get("/workspaces")
def list_workspaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    org_ids = [membership.organization_id for membership in user.memberships]
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.organization_id.in_(org_ids))
        .order_by(Workspace.created_at.asc())
        .all()
        if org_ids
        else []
    )
    return {"workspaces": [_workspace_payload(workspace) for workspace in workspaces]}


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.mode not in {"evaluation", "live"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="mode must be evaluation or live")
    org_id = payload.organization_id or (user.memberships[0].organization_id if user.memberships else None)
    if not org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    org, _membership = require_org_membership(org_id, user, db)
    assert_can_create_workspace(db, org, payload.mode)
    workspace = Workspace(
        organization_id=org.id,
        name=payload.name,
        crop=payload.crop,
        region=payload.region,
        mode=payload.mode,
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return {"workspace": _workspace_payload(workspace), "entitlements": serialize_entitlements(org, db)}


@router.get("/workspaces/{workspace_id}/assurance/overview")
def assurance_overview(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    org = workspace.organization
    return {
        "workspace": _workspace_payload(workspace),
        "readiness": 64 if workspace.mode == "evaluation" else 72,
        "open_actions": [
            "Reviewer approval required before any external use.",
            "Upload controller and flow-meter proof before live assurance.",
        ],
        "missing_proof_count": 3,
        "agent_runs": db.query(UsageEvent).filter(UsageEvent.workspace_id == workspace.id, UsageEvent.event_type == "agent_run").count(),
        "top_priority_work": "Complete proof coverage for irrigation event chain.",
        "ai_insight_summary": "Evaluation insight only. Not certified, not regulator-approved, and requires human review.",
        "connected_systems": ["Evaluation data package"] if workspace.mode == "evaluation" else ["Configured integrations"],
        "entitlements": serialize_entitlements(org, db),
    }


@router.get("/workspaces/{workspace_id}/evidence")
def list_evidence(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    return {
        "workspace_id": workspace.id,
        "evidence": [],
        "empty_state": "No tenant evidence has been uploaded for this workspace.",
        "classification_status": "pending",
        "proof_domain_mapping": {},
    }


@router.post("/workspaces/{workspace_id}/evidence")
def upload_evidence_stub(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    require_feature(workspace.organization, "evidence.upload", db=db)
    QuotaService(db).record(
        workspace.organization,
        "evidence_upload",
        workspace_id=workspace.id,
        user_id=user.id,
        metadata={"source": "api_stub"},
    )
    db.commit()
    return {
        "status": "accepted_for_review",
        "classification_status": "pending",
        "confidence": None,
        "issues": ["Upload storage adapter is not yet configured for production files."],
    }


@router.post("/workspaces/{workspace_id}/agents/run")
def run_agent(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    require_feature(workspace.organization, "agents.plan", db=db)
    event = QuotaService(db).record(
        workspace.organization,
        "agent_run",
        workspace_id=workspace.id,
        user_id=user.id,
        metadata={"agent": "readiness"},
    )
    db.commit()
    return {
        "run_id": event.id,
        "status": "requires_human_review",
        "latest_findings": ["Missing proof remains before report export."],
        "action_proposals": ["Assign reviewer to evidence chain."],
        "human_approval_required": True,
    }


@router.get("/workspaces/{workspace_id}/agents/runs")
def agent_runs(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    rows = (
        db.query(UsageEvent)
        .filter(UsageEvent.workspace_id == workspace.id, UsageEvent.event_type == "agent_run")
        .order_by(UsageEvent.created_at.desc())
        .all()
    )
    return {
        "runs": [
            {
                "id": row.id,
                "status": "requires_human_review",
                "created_at": row.created_at.isoformat(),
                "metadata": row.metadata_json or {},
            }
            for row in rows
        ]
    }


@router.get("/workspaces/{workspace_id}/reports")
def reports(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    can_export = serialize_entitlements(workspace.organization, db)["can_export_reports"]
    return {
        "reports": [
            {
                "id": "readiness-summary",
                "title": "Readiness summary",
                "status": "draftable" if can_export else "blocked",
                "export_allowed": can_export,
                "truthful_status": "Evaluation draft. Reviewer required before external use.",
            }
        ]
    }


@router.post("/workspaces/{workspace_id}/reports/export")
def export_report(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    assert_can_export_reports(workspace.organization, db=db)
    QuotaService(db).record(
        workspace.organization,
        "report_export",
        workspace_id=workspace.id,
        user_id=user.id,
        metadata={"report": "readiness-summary"},
    )
    db.commit()
    return {"status": "queued", "truthful_status": "Draft report queued for reviewer-safe generation."}


@router.post("/workspaces/{workspace_id}/assurance/passports")
def create_assurance_passport(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, membership = require_workspace_access(workspace_id, user, db)
    require_owner_or_admin(membership.role)
    require_workspace_mode(workspace, "live")
    require_feature(workspace.organization, "agents.execute_approval_gated", db=db)
    return {"status": "draft", "truthful_status": "Reviewer required. Not certified or regulator-approved."}
