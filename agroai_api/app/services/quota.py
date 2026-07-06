"""Durable usage/quota accounting for commercial controls."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.saas import Organization, UsageEvent
from app.services.entitlements import resolve_effective_entitlements


METRIC_FEATURE_LIMIT = {
    "evidence_upload": "quota.evidence_upload.monthly",
    "ai_action": "quota.ai_action.monthly",
    "agent_run": "quota.agent_run.monthly",
    "report_export": "quota.report_export.monthly",
}


@dataclass(frozen=True)
class QuotaSnapshot:
    metric: str
    limit: int | None
    used: int
    remaining: int | None
    period_key: str


class QuotaService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def current_period_key(now: datetime | None = None) -> str:
        value = now or datetime.utcnow()
        return value.strftime("%Y-%m")

    def count_usage(self, organization_id: str, metric: str, period_key: str | None = None) -> int:
        query = self.db.query(func.coalesce(func.sum(UsageEvent.quantity), 0)).filter(
            UsageEvent.organization_id == organization_id,
            UsageEvent.state == "committed",
        )
        query = query.filter((UsageEvent.metric == metric) | (UsageEvent.event_type == metric))
        if period_key:
            query = query.filter(UsageEvent.period_key == period_key)
        return int(query.scalar() or 0)

    def snapshot(self, org: Organization, metric: str, period_key: str | None = None) -> QuotaSnapshot:
        key = period_key or self.current_period_key()
        effective = resolve_effective_entitlements(org, db=self.db)
        limit_key = METRIC_FEATURE_LIMIT.get(metric)
        raw_limit = effective.values.get(limit_key) if limit_key else None
        limit = int(raw_limit) if raw_limit is not None else None
        used = self.count_usage(org.id, metric, key)
        remaining = None if limit is None else max(0, limit - used)
        return QuotaSnapshot(metric=metric, limit=limit, used=used, remaining=remaining, period_key=key)

    def check(self, org: Organization, metric: str, quantity: int = 1) -> QuotaSnapshot:
        snapshot = self.snapshot(org, metric)
        if snapshot.limit is not None and snapshot.used + quantity > snapshot.limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "quota_exceeded",
                    "metric": metric,
                    "limit": snapshot.limit,
                    "used": snapshot.used,
                    "remaining": snapshot.remaining,
                    "period_key": snapshot.period_key,
                    "message": f"Monthly {metric.replace('_', ' ')} quota reached.",
                },
            )
        return snapshot

    def record(
        self,
        org: Organization,
        metric: str,
        *,
        quantity: int = 1,
        workspace_id: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UsageEvent:
        period_key = self.current_period_key()
        if request_id:
            existing = (
                self.db.query(UsageEvent)
                .filter(
                    UsageEvent.organization_id == org.id,
                    UsageEvent.request_id == request_id,
                    UsageEvent.metric == metric,
                    UsageEvent.state == "committed",
                )
                .first()
            )
            if existing:
                return existing
        self.check(org, metric, quantity)
        event = UsageEvent(
            organization_id=org.id,
            workspace_id=workspace_id,
            user_id=user_id,
            event_type=metric,
            metric=metric,
            quantity=quantity,
            unit="count",
            period_key=period_key,
            request_id=request_id,
            state="committed",
            metadata_json=metadata or {},
        )
        self.db.add(event)
        return event
