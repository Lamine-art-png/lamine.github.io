"""Shared commercial guard for connector writes across API and worker paths."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import event, func
from sqlalchemy.orm import Session

from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization
from app.services.commercial_control import get_limit, require_feature
from app.services.commercial_packaging_v2 import (
    ENTERPRISE_INTEGRATION_PROVIDERS,
    MANUAL_EVIDENCE_PROVIDERS,
    feature_for_provider,
    required_plan_for_provider,
)

MANUAL_PROVIDERS = set(MANUAL_EVIDENCE_PROVIDERS)
CONTRACT_PROVIDERS = set(ENTERPRISE_INTEGRATION_PROVIDERS)


def connector_feature(provider: str) -> tuple[str, str | None]:
    required_plan = required_plan_for_provider(provider)
    return feature_for_provider(provider), None if required_plan == "free" else required_plan


def _active_connection_count(session: Session, organization_id: str) -> int:
    return int(
        session.query(func.count(ConnectorConnection.id))
        .filter(
            ConnectorConnection.tenant_id == organization_id,
            ConnectorConnection.provider.notin_(MANUAL_PROVIDERS),
        )
        .scalar()
        or 0
    )


def _pending_nonmanual_count(session: Session, organization_id: str) -> int:
    return sum(
        1
        for item in session.new
        if isinstance(item, ConnectorConnection)
        and item.tenant_id == organization_id
        and item.provider not in MANUAL_PROVIDERS
    )


def enforce_connector_write(session: Session, connection: ConnectorConnection, *, check_capacity: bool) -> None:
    org = session.get(Organization, connection.tenant_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    feature_key, recommended_plan = connector_feature(connection.provider)
    require_feature(
        session,
        org,
        feature_key,
        recommended_plan=recommended_plan,
        allow_preview=connection.provider == "custom_api",
    )

    if not check_capacity or connection.provider in MANUAL_PROVIDERS:
        return
    limit = get_limit(session, org, "quota.active_connector")
    if limit is None:
        return
    projected = _active_connection_count(session, org.id) + _pending_nonmanual_count(session, org.id)
    if projected > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "quota_exceeded",
                "metric": "active_connector",
                "limit": limit,
                "message": "Active connector capacity is exhausted for the current commercial plan.",
            },
        )


@event.listens_for(Session, "before_flush")
def _enforce_connector_commercial_state(session: Session, _flush_context, _instances) -> None:
    new_connections = [item for item in session.new if isinstance(item, ConnectorConnection)]
    dirty_connections = [
        item
        for item in session.dirty
        if isinstance(item, ConnectorConnection) and item not in session.deleted
    ]
    for connection in new_connections:
        enforce_connector_write(session, connection, check_capacity=True)
    for connection in dirty_connections:
        enforce_connector_write(session, connection, check_capacity=False)
