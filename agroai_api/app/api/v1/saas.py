from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_org_membership, require_workspace_access
from app.api.v1.auth import _unique_slug
from app.db.base import get_db
from app.models.saas import Organization, OrganizationMembership, UsageEvent, User, Workspace
from app.services.entitlements import (
    assert_can_create_workspace,
    assert_can_export_reports,
    assert_can_run_agent,
    assert_can_upload_evidence,
    get_plan_limits,
    require_owner_or_admin,
    require_workspace_mode,
    serialize_entitlements,
)

router = APIRouter(tags=["saas"])


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2)


class WorkspaceCreate(BaseModel):
    organization_id: str | None = None
    name: str = Field(min_length=2)
    crop: str | None = None
    region: str | None = None
    mode: str = "evaluation"


class PortalProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=160)
    job_title: str | None = Field(default=None, max_length=160)
    organization_id: str | None = None


class PortalPreferencesUpdate(BaseModel):
    locale: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
    notifications: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None


def _workspace_payload(workspace: Workspace) -> dict:
    return {"id": workspace.id, "organization_id": workspace.organization_id, "name": workspace.name, "crop": workspace.crop, "region": workspace.region, "mode": workspace.mode, "created_at": workspace.created_at.isoformat(), "updated_at": workspace.updated_at.isoformat()}


def _ensure_preferences_table(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id VARCHAR PRIMARY KEY,
            locale VARCHAR,
            timezone VARCHAR,
            notifications_json TEXT,
            ui_json TEXT,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
    """))
    db.commit()


def _json_dict(value: Any, fallback: dict | None = None) -> dict:
    if isinstance(value, dict):
        return value
    if value:
        try:
            parsed = json.loads(str(value))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return fallback or {}


def _preferences_payload(row: Any | None, user: User) -> dict:
    default_notifications = {"report_delivery": True, "operational_alerts": True, "support_updates": True, "billing_updates": True}
    default_ui = {"density": "comfortable", "assistant_speed": "balanced", "job_title": ""}
    if not row:
        return {"locale": "auto", "timezone": "auto", "notifications": default_notifications, "ui": default_ui, "user": {"id": user.id, "name": user.name, "email": user.email}}
    data = row._mapping if hasattr(row, "_mapping") else row
    return {"locale": data.get("locale") or "auto", "timezone": data.get("timezone") or "auto", "notifications": _json_dict(data.get("notifications_json"), default_notifications), "ui": _json_dict(data.get("ui_json"), default_ui), "updated_at": data.get("updated_at"), "user": {"id": user.id, "name": user.name, "email": user.email}}


def _get_preferences_row(db: Session, user_id: str):
    _ensure_preferences_table(db)
    return db.execute(text("SELECT * FROM user_preferences WHERE user_id = :user_id"), {"user_id": user_id}).first()


def _save_preferences(db: Session, user: User, prefs: dict) -> dict:
    now = datetime.utcnow().isoformat(timespec="seconds")
    db.execute(text("""
        INSERT INTO user_preferences (user_id, locale, timezone, notifications_json, ui_json, created_at, updated_at)
        VALUES (:user_id, :locale, :timezone, :notifications_json, :ui_json, :created_at, :updated_at)
        ON CONFLICT(user_id) DO UPDATE SET
            locale = excluded.locale,
            timezone = excluded.timezone,
            notifications_json = excluded.notifications_json,
            ui_json = excluded.ui_json,
            updated_at = excluded.updated_at
    """), {"user_id": user.id, "locale": prefs.get("locale") or "auto", "timezone": prefs.get("timezone") or "auto", "notifications_json": json.dumps(prefs.get("notifications") or {}), "ui_json": json.dumps(prefs.get("ui") or {}), "created_at": now, "updated_at": now})
    db.commit()
    return _preferences_payload(_get_preferences_row(db, user.id), user)


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
    return {"organization": {"id": org.id, "name": org.name, "slug": org.slug, "plan": org.plan, "subscription_status": org.subscription_status}}


@router.get("/orgs")
def list_orgs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    memberships = db.query(OrganizationMembership).filter(OrganizationMembership.user_id == user.id).order_by(OrganizationMembership.created_at.asc()).all()
    return {"organizations": [{"id": m.organization.id, "name": m.organization.name, "slug": m.organization.slug, "plan": m.organization.plan, "subscription_status": m.organization.subscription_status, "role": m.role} for m in memberships]}


@router.post("/orgs/{org_id}/switch")
def switch_org(org_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    org, membership = require_org_membership(org_id, user, db)
    return {"current_organization": {"id": org.id, "name": org.name, "slug": org.slug, "plan": org.plan, "subscription_status": org.subscription_status, "role": membership.role}, "entitlements": serialize_entitlements(org)}


@router.get("/workspaces")
def list_workspaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    org_ids = [membership.organization_id for membership in user.memberships]
    workspaces = db.query(Workspace).filter(Workspace.organization_id.in_(org_ids)).order_by(Workspace.created_at.asc()).all() if org_ids else []
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
    workspace = Workspace(organization_id=org.id, name=payload.name, crop=payload.crop, region=payload.region, mode=payload.mode)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return {"workspace": _workspace_payload(workspace), "entitlements": serialize_entitlements(org)}


@router.get("/settings/preferences")
def get_portal_preferences(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {"preferences": _preferences_payload(_get_preferences_row(db, user.id), user)}


@router.patch("/settings/preferences")
def update_portal_preferences(payload: PortalPreferencesUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    prefs = _preferences_payload(_get_preferences_row(db, user.id), user)
    if payload.locale is not None:
        prefs["locale"] = payload.locale.strip() or "auto"
    if payload.timezone is not None:
        prefs["timezone"] = payload.timezone.strip() or "auto"
    if payload.notifications is not None:
        prefs["notifications"] = {**prefs.get("notifications", {}), **payload.notifications}
    if payload.ui is not None:
        prefs["ui"] = {**prefs.get("ui", {}), **payload.ui}
    return {"preferences": _save_preferences(db, user, prefs), "message": "Preferences saved."}


@router.patch("/settings/profile")
def update_portal_profile(payload: PortalProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.name is not None:
        user.name = payload.name.strip() or None
    org_id = payload.organization_id or (user.memberships[0].organization_id if user.memberships else None)
    org = None
    membership = None
    if org_id:
        org, membership = require_org_membership(org_id, user, db)
        if payload.company is not None and membership.role in {"owner", "admin"}:
            org.name = payload.company.strip() or org.name
    prefs = _preferences_payload(_get_preferences_row(db, user.id), user)
    if payload.job_title is not None:
        prefs["ui"] = {**prefs.get("ui", {}), "job_title": payload.job_title.strip()}
        _save_preferences(db, user, prefs)
    db.commit()
    return {"user": {"id": user.id, "name": user.name, "email": user.email}, "organization": {"id": org.id, "name": org.name, "role": membership.role} if org and membership else None, "preferences": _preferences_payload(_get_preferences_row(db, user.id), user)}


@router.get("/workspaces/{workspace_id}/assurance/overview")
def assurance_overview(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    org = workspace.organization
    return {"workspace": _workspace_payload(workspace), "readiness": 64 if workspace.mode == "evaluation" else 72, "open_actions": ["Reviewer approval required before any external use.", "Upload controller and flow-meter proof before live assurance."], "missing_proof_count": 3, "agent_runs": db.query(UsageEvent).filter(UsageEvent.workspace_id == workspace.id, UsageEvent.event_type == "agent_run").count(), "top_priority_work": "Complete proof coverage for irrigation event chain.", "ai_insight_summary": "Evaluation insight only. Not certified, not regulator-approved, and requires human review.", "connected_systems": ["Evaluation data package"] if workspace.mode == "evaluation" else ["Configured integrations"], "entitlements": serialize_entitlements(org)}


@router.get("/workspaces/{workspace_id}/evidence")
def list_evidence(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    return {"workspace_id": workspace.id, "evidence": [], "empty_state": "No tenant evidence has been uploaded for this workspace.", "classification_status": "pending", "proof_domain_mapping": {}}


@router.post("/workspaces/{workspace_id}/evidence")
def upload_evidence_stub(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    assert_can_upload_evidence(db, workspace.organization)
    event = UsageEvent(organization_id=workspace.organization_id, workspace_id=workspace.id, user_id=user.id, event_type="evidence_upload", quantity=1, metadata_json={"source": "api_stub"})
    db.add(event)
    db.commit()
    return {"status": "accepted_for_review", "classification_status": "pending", "confidence": None, "issues": ["Upload storage adapter is not yet configured for production files."]}


@router.post("/workspaces/{workspace_id}/agents/run")
def run_agent(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    assert_can_run_agent(db, workspace.organization)
    event = UsageEvent(organization_id=workspace.organization_id, workspace_id=workspace.id, user_id=user.id, event_type="agent_run", quantity=1, metadata_json={"agent": "readiness"})
    db.add(event)
    db.commit()
    return {"run_id": event.id, "status": "requires_human_review", "latest_findings": ["Missing proof remains before report export."], "action_proposals": ["Assign reviewer to evidence chain."], "human_approval_required": True}


@router.get("/workspaces/{workspace_id}/agents/runs")
def agent_runs(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    rows = db.query(UsageEvent).filter(UsageEvent.workspace_id == workspace.id, UsageEvent.event_type == "agent_run").order_by(UsageEvent.created_at.desc()).all()
    return {"runs": [{"id": row.id, "status": "requires_human_review", "created_at": row.created_at.isoformat(), "metadata": row.metadata_json or {}} for row in rows]}


@router.get("/workspaces/{workspace_id}/reports")
def reports(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    can_export = get_plan_limits(workspace.organization.plan).can_export_reports
    return {"reports": [{"id": "readiness-summary", "title": "Readiness summary", "status": "draftable" if can_export else "blocked", "export_allowed": can_export, "truthful_status": "Evaluation draft. Reviewer required before external use."}]}


@router.post("/workspaces/{workspace_id}/reports/export")
def export_report(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workspace, _ = require_workspace_access(workspace_id, user, db)
    assert_can_export_reports(workspace.organization)
    return {"status": "queued", "truthful_status": "Draft report queued for reviewer-safe generation."}
