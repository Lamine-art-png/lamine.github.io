from __future__ import annotations

from fastapi import HTTPException, status


SCOPES: frozenset[str] = frozenset(
    {
        "projects:read",
        "projects:write",
        "keys:read",
        "keys:write",
        "service_accounts:read",
        "service_accounts:write",
        "fields:read",
        "fields:write",
        "connectors:read",
        "connectors:write",
        "connectors:sync",
        "sources:read",
        "sources:write",
        "observations:read",
        "observations:write",
        "jobs:read",
        "intelligence:read",
        "intelligence:run",
        "recommendations:read",
        "recommendations:write",
        "reports:read",
        "reports:write",
        "webhooks:read",
        "webhooks:write",
        "usage:read",
        "request_logs:read",
        "actions:plan",
        "actions:execute",
    }
)


def normalize_scopes(values: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    scopes = sorted({str(value).strip() for value in values or [] if str(value).strip()})
    unknown = [scope for scope in scopes if scope not in SCOPES]
    if unknown:
        raise ValueError(f"unknown Platform API scopes: {', '.join(unknown)}")
    return scopes


def require_scopes(granted: set[str] | frozenset[str], required: set[str] | frozenset[str]) -> None:
    missing = sorted(required - granted)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "scope_denied",
                "type": "authorization_error",
                "message": "The API key does not have the required scope.",
                "details": {"missing_scopes": missing},
            },
        )
