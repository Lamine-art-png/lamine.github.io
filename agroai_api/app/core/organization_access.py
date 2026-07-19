from __future__ import annotations

from typing import Any


APPROVED_ORGANIZATION_STATUSES = frozenset({"approved", "approved_legacy"})


def normalized_organization_status(value: Any) -> str:
    status = getattr(value, "verification_status", value)
    return str(status or "verification_required").strip().lower()


def organization_access_allowed(value: Any) -> bool:
    """Return the server-authoritative organization access decision.

    The input may be an organization model or a raw persisted status. Keeping
    this policy independent of FastAPI and Platform API models lets human JWT
    and service-account authentication share the same decision without a
    browser-session or dependency-module import.
    """

    return normalized_organization_status(value) in APPROVED_ORGANIZATION_STATUSES
