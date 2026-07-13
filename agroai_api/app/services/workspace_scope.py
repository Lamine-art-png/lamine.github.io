from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.saas import Workspace


def primary_workspace_id(db: Session, organization_id: str) -> str | None:
    """Return the stable original operation for legacy unscoped records."""
    row = (
        db.query(Workspace.id)
        .filter(Workspace.organization_id == organization_id)
        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
        .first()
    )
    return str(row[0]) if row else None


def includes_legacy_unscoped(db: Session, organization_id: str, workspace_id: str | None) -> bool:
    """Only the original operation may read records created before workspace scoping."""
    return bool(workspace_id and primary_workspace_id(db, organization_id) == workspace_id)
