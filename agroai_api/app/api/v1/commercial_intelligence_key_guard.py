"""Key-limit guard for the commercial Intelligence bootstrap path."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.api.v1 import commercial_intelligence as legacy
from app.models.platform_api import PlatformApiKey
from app.models.saas import Organization
from app.platform_api.programs import enforce_enrollment_limit, require_active_enrollment


_original_create_platform_key = legacy.create_platform_key


def _bounded_create_platform_key(
    db: Session,
    *,
    project: Any,
    service_account: Any,
    name: str,
    scopes: list[str],
    created_by_user_id: str | None,
    **kwargs: Any,
):
    organization = db.get(Organization, project.organization_id)
    if organization is None:
        raise ValueError("organization unavailable")
    enrollment = require_active_enrollment(
        db,
        organization,
        environment=project.environment,
        operation="intelligence_key_create",
    )
    active_count = (
        db.query(PlatformApiKey)
        .filter(
            PlatformApiKey.organization_id == project.organization_id,
            PlatformApiKey.status == "active",
            PlatformApiKey.revoked_at.is_(None),
        )
        .count()
    )
    enforce_enrollment_limit(
        db,
        enrollment=enrollment,
        resource_name="keys",
        current_count=active_count,
    )
    return _original_create_platform_key(
        db,
        project=project,
        service_account=service_account,
        name=name,
        scopes=scopes,
        created_by_user_id=created_by_user_id,
        **kwargs,
    )


legacy.create_platform_key = _bounded_create_platform_key
