"""Operator Cockpit endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.models.saas import Workspace
from app.services.operator_cockpit import (
    build_context,
    decision_workbench,
    exceptions,
    field_intelligence,
    readiness_summary,
    report_factory,
)


router = APIRouter(tags=["operator-cockpit"])


class WorkbenchRunRequest(BaseModel):
    workspace_id: str | None = None
    field_id: str | None = None
    mode: Literal["daily", "field", "compliance", "irrigation"] = "daily"


class ReportFactoryRequest(BaseModel):
    report_type: Literal[
        "water_use_summary",
        "compliance_packet",
        "exception_report",
        "executive_brief",
        "grower_recommendation",
    ]
    workspace_id: str | None = None
    field_id: str | None = None
    audience: Literal["operator", "owner", "agency", "lender", "investor", "grower"] | None = None


def _require_org(ctx: AuthContext) -> str:
    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization.id


def _workspace(db: Session, organization_id: str, workspace_id: str | None) -> Workspace | None:
    query = db.query(Workspace).filter(Workspace.organization_id == organization_id)
    if workspace_id:
        workspace = query.filter(Workspace.id == workspace_id).first()
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace
    return query.order_by(Workspace.created_at.asc()).first()


def _context(db: Session, ctx: AuthContext, workspace_id: str | None = None):
    organization_id = _require_org(ctx)
    return build_context(db, organization_id, _workspace(db, organization_id, workspace_id))


@router.get("/readiness/summary")
def get_readiness_summary(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return readiness_summary(_context(db, ctx, workspace_id))


@router.get("/fields/intelligence")
def get_fields_intelligence(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return field_intelligence(_context(db, ctx, workspace_id))


@router.get("/exceptions")
def get_exceptions(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return exceptions(_context(db, ctx, workspace_id))


@router.get("/decisions/workbench")
def get_decision_workbench(
    workspace_id: str | None = Query(default=None),
    field_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return decision_workbench(_context(db, ctx, workspace_id), field_id=field_id)


@router.post("/decisions/workbench/run")
def run_decision_workbench(
    payload: WorkbenchRunRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return decision_workbench(_context(db, ctx, payload.workspace_id), mode=payload.mode, field_id=payload.field_id)


@router.post("/reports/factory")
def create_factory_report(
    payload: ReportFactoryRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return report_factory(
        _context(db, ctx, payload.workspace_id),
        report_type=payload.report_type,
        audience=payload.audience,
        field_id=payload.field_id,
    )

