"""Single ownership rule for platform resources.

A resource belongs to (organization, API project) and, when it was created by
a workspace-restricted key, to that workspace. A workspace-restricted
principal sees only its workspace's resources; a project-wide principal sees
the whole project.
"""
from __future__ import annotations

from typing import Any

from app.platform_api.principal import PlatformPrincipal


def owned(query: Any, model: Any, principal: PlatformPrincipal) -> Any:
    query = query.filter(
        model.organization_id == principal.organization_id,
        model.api_project_id == principal.api_project_id,
    )
    if principal.workspace_id:
        query = query.filter(model.workspace_id == principal.workspace_id)
    return query
