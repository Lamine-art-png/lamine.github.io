from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.platform_api import ApiProject, ApiServiceAccount, PlatformApiKey
from app.models.saas import Workspace


def organization_workspace(db: Session, *, organization_id: str, workspace_id: str | None) -> Workspace | None:
    if not workspace_id:
        return None
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or workspace.organization_id != organization_id:
        raise ValueError("workspace is not available to the authenticated organization")
    return workspace


def compatible_workspace_id(
    db: Session,
    *,
    organization_id: str,
    project: ApiProject,
    service_account: ApiServiceAccount | None = None,
    supplied_workspace_id: str | None = None,
) -> str | None:
    if project.organization_id != organization_id:
        raise ValueError("API project organization mismatch")
    project_workspace = organization_workspace(
        db,
        organization_id=organization_id,
        workspace_id=project.workspace_id,
    )
    service_workspace = None
    if service_account is not None:
        if (
            service_account.organization_id != organization_id
            or service_account.api_project_id != project.id
        ):
            raise ValueError("service account does not belong to the API project organization")
        service_workspace = organization_workspace(
            db,
            organization_id=organization_id,
            workspace_id=service_account.workspace_id,
        )
    supplied_workspace = organization_workspace(
        db,
        organization_id=organization_id,
        workspace_id=supplied_workspace_id,
    )

    expected = project_workspace or service_workspace
    if project_workspace and service_workspace and project_workspace.id != service_workspace.id:
        raise ValueError("service account workspace is incompatible with the API project")
    if expected and supplied_workspace and expected.id != supplied_workspace.id:
        raise ValueError("workspace is incompatible with the API project")
    return (supplied_workspace or service_workspace or project_workspace).id if (
        supplied_workspace or service_workspace or project_workspace
    ) else None


def assert_key_lineage(
    db: Session,
    *,
    key: PlatformApiKey,
    project: ApiProject,
    service_account: ApiServiceAccount,
) -> None:
    organization_id = key.organization_id
    if project.id != key.api_project_id or project.organization_id != organization_id:
        raise ValueError("API key project organization mismatch")
    if (
        service_account.id != key.service_account_id
        or service_account.organization_id != organization_id
        or service_account.api_project_id != project.id
    ):
        raise ValueError("API key service-account organization mismatch")
    compatible_workspace_id(
        db,
        organization_id=organization_id,
        project=project,
        service_account=service_account,
        supplied_workspace_id=key.workspace_id,
    )
