"""Canonical AGRO-AI commercial and effective-entitlement control plane.

This module deliberately separates customer identity, commercial plan, subscription
state, contract configuration, and runtime authorization. Frontend locks are UX;
backend callers must use this resolver for premium or variable-cost capabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.saas import CommercialContract, EntitlementOverride, Organization
from app.services.product_plans import plan_by_id


PLAN_VERSION = "2026-07"
ACTIVE_PAID_STATES = {"active", "trialing", "contracted"}
FEATURE_STATES = {"unavailable", "locked", "requestable", "preview", "enabled", "contract_only"}


BASE_ENTITLEMENTS: dict[str, dict[str, Any]] = {
    "free": {
        "intelligence.profile": "essential",
        "intelligence.ask": "enabled",
        "field_intelligence.capture": "enabled",
        "intelligence.deep_analysis": "locked",
        "intelligence.workspace_memory": "preview",
        "intelligence.shared_memory": "locked",
        "intelligence.cross_workspace": "locked",
        "intelligence.portfolio_synthesis": "locked",
        "intelligence.network_benchmarking": "locked",
        "intelligence.agentic": "preview",
        "reports.generate": "locked",
        "reports.pdf_export": "locked",
        "reports.email_delivery": "locked",
        "reports.multi_workspace": "locked",
        "compliance.packet_draft": "locked",
        "evidence.upload": "enabled",
        "evidence.shared_library": "locked",
        "evidence.rollups": "locked",
        "connectors.manual_upload": "enabled",
        "connectors.live": "locked",
        "connectors.oauth_documents": "locked",
        "connectors.custom_api": "locked",
        "connectors.custom_integration": "locked",
        "team.invite": "locked",
        "team.roles": "locked",
        "workflows.approvals": "locked",
        "admin.requests": "locked",
        "network.multi_workspace": "locked",
        "network.rollups": "locked",
        "network.portfolio_analytics": "locked",
        "agents.plan": "preview",
        "agents.execute_safe": "locked",
        "agents.execute_approval_gated": "locked",
        "governance.audit_logs": "locked",
        "governance.sso": "locked",
        "governance.custom_retention": "locked",
        "api.access": "locked",
        "webhooks.outbound": "locked",
        "quota.workspace": 1,
        "quota.seat": 1,
        "quota.evidence_upload.monthly": 10,
        "quota.ai_action.monthly": 25,
        "quota.deep_investigation.monthly": 2,
        "quota.agent_run.monthly": 10,
        "quota.report_generation.monthly": 0,
        "quota.report_export.monthly": 0,
        "quota.active_connector": 1,
        "quota.managed_entity": 25,
    },
    "professional": {
        "intelligence.profile": "operational",
        "intelligence.ask": "enabled",
        "intelligence.deep_analysis": "enabled",
        "intelligence.workspace_memory": "enabled",
        "intelligence.shared_memory": "preview",
        "intelligence.cross_workspace": "locked",
        "intelligence.portfolio_synthesis": "locked",
        "intelligence.network_benchmarking": "locked",
        "intelligence.agentic": "enabled",
        "reports.generate": "enabled",
        "reports.pdf_export": "enabled",
        "reports.email_delivery": "enabled",
        "reports.multi_workspace": "locked",
        "compliance.packet_draft": "enabled",
        "evidence.upload": "enabled",
        "evidence.shared_library": "preview",
        "evidence.rollups": "locked",
        "connectors.manual_upload": "enabled",
        "connectors.live": "enabled",
        "connectors.oauth_documents": "enabled",
        "connectors.custom_api": "locked",
        "connectors.custom_integration": "requestable",
        "team.invite": "locked",
        "team.roles": "locked",
        "workflows.approvals": "locked",
        "admin.requests": "locked",
        "network.multi_workspace": "locked",
        "network.rollups": "locked",
        "network.portfolio_analytics": "locked",
        "agents.plan": "enabled",
        "agents.execute_safe": "enabled",
        "agents.execute_approval_gated": "preview",
        "governance.audit_logs": "locked",
        "governance.sso": "locked",
        "governance.custom_retention": "locked",
        "api.access": "preview",
        "webhooks.outbound": "locked",
        "quota.workspace": 5,
        "quota.seat": 3,
        "quota.evidence_upload.monthly": 500,
        "quota.ai_action.monthly": 500,
        "quota.deep_investigation.monthly": 25,
        "quota.agent_run.monthly": 100,
        "quota.report_generation.monthly": 25,
        "quota.report_export.monthly": 25,
        "quota.active_connector": 3,
        "quota.managed_entity": 250,
    },
    "team": {
        "intelligence.profile": "collaborative",
        "intelligence.ask": "enabled",
        "intelligence.deep_analysis": "enabled",
        "intelligence.workspace_memory": "enabled",
        "intelligence.shared_memory": "enabled",
        "intelligence.cross_workspace": "preview",
        "intelligence.portfolio_synthesis": "preview",
        "intelligence.network_benchmarking": "locked",
        "intelligence.agentic": "enabled",
        "reports.generate": "enabled",
        "reports.pdf_export": "enabled",
        "reports.email_delivery": "enabled",
        "reports.multi_workspace": "preview",
        "compliance.packet_draft": "enabled",
        "evidence.upload": "enabled",
        "evidence.shared_library": "enabled",
        "evidence.rollups": "preview",
        "connectors.manual_upload": "enabled",
        "connectors.live": "enabled",
        "connectors.oauth_documents": "enabled",
        "connectors.custom_api": "locked",
        "connectors.custom_integration": "requestable",
        "team.invite": "enabled",
        "team.roles": "enabled",
        "workflows.approvals": "enabled",
        "admin.requests": "enabled",
        "network.multi_workspace": "preview",
        "network.rollups": "locked",
        "network.portfolio_analytics": "locked",
        "agents.plan": "enabled",
        "agents.execute_safe": "enabled",
        "agents.execute_approval_gated": "enabled",
        "governance.audit_logs": "preview",
        "governance.sso": "locked",
        "governance.custom_retention": "locked",
        "api.access": "enabled",
        "webhooks.outbound": "preview",
        "quota.workspace": 25,
        "quota.seat": 10,
        "quota.evidence_upload.monthly": 2500,
        "quota.ai_action.monthly": 2500,
        "quota.deep_investigation.monthly": 150,
        "quota.agent_run.monthly": 500,
        "quota.report_generation.monthly": 100,
        "quota.report_export.monthly": 100,
        "quota.active_connector": 8,
        "quota.managed_entity": 1500,
    },
    "network": {
        "intelligence.profile": "network",
        "intelligence.ask": "enabled",
        "intelligence.deep_analysis": "enabled",
        "intelligence.workspace_memory": "enabled",
        "intelligence.shared_memory": "enabled",
        "intelligence.cross_workspace": "enabled",
        "intelligence.portfolio_synthesis": "enabled",
        "intelligence.network_benchmarking": "enabled",
        "intelligence.agentic": "enabled",
        "reports.generate": "enabled",
        "reports.pdf_export": "enabled",
        "reports.email_delivery": "enabled",
        "reports.multi_workspace": "enabled",
        "compliance.packet_draft": "enabled",
        "evidence.upload": "enabled",
        "evidence.shared_library": "enabled",
        "evidence.rollups": "enabled",
        "connectors.manual_upload": "enabled",
        "connectors.live": "enabled",
        "connectors.oauth_documents": "enabled",
        "connectors.custom_api": "preview",
        "connectors.custom_integration": "requestable",
        "team.invite": "enabled",
        "team.roles": "enabled",
        "workflows.approvals": "enabled",
        "admin.requests": "enabled",
        "network.multi_workspace": "enabled",
        "network.rollups": "enabled",
        "network.portfolio_analytics": "enabled",
        "agents.plan": "enabled",
        "agents.execute_safe": "enabled",
        "agents.execute_approval_gated": "enabled",
        "governance.audit_logs": "enabled",
        "governance.sso": "requestable",
        "governance.custom_retention": "requestable",
        "api.access": "enabled",
        "webhooks.outbound": "enabled",
        "quota.workspace": 50,
        "quota.seat": 25,
        "quota.evidence_upload.monthly": 10000,
        "quota.ai_action.monthly": 10000,
        "quota.deep_investigation.monthly": 750,
        "quota.agent_run.monthly": 2500,
        "quota.report_generation.monthly": 500,
        "quota.report_export.monthly": 500,
        "quota.active_connector": 20,
        "quota.managed_entity": 10000,
    },
    "enterprise": {
        "intelligence.profile": "institutional",
        "intelligence.ask": "enabled",
        "intelligence.deep_analysis": "enabled",
        "intelligence.workspace_memory": "enabled",
        "intelligence.shared_memory": "enabled",
        "intelligence.cross_workspace": "enabled",
        "intelligence.portfolio_synthesis": "enabled",
        "intelligence.network_benchmarking": "enabled",
        "intelligence.agentic": "enabled",
        "reports.generate": "enabled",
        "reports.pdf_export": "enabled",
        "reports.email_delivery": "enabled",
        "reports.multi_workspace": "enabled",
        "compliance.packet_draft": "enabled",
        "evidence.upload": "enabled",
        "evidence.shared_library": "enabled",
        "evidence.rollups": "enabled",
        "connectors.manual_upload": "enabled",
        "connectors.live": "enabled",
        "connectors.oauth_documents": "enabled",
        "connectors.custom_api": "contract_only",
        "connectors.custom_integration": "contract_only",
        "team.invite": "enabled",
        "team.roles": "enabled",
        "workflows.approvals": "enabled",
        "admin.requests": "enabled",
        "network.multi_workspace": "enabled",
        "network.rollups": "enabled",
        "network.portfolio_analytics": "enabled",
        "agents.plan": "enabled",
        "agents.execute_safe": "enabled",
        "agents.execute_approval_gated": "enabled",
        "governance.audit_logs": "enabled",
        "governance.sso": "requestable",
        "governance.custom_retention": "contract_only",
        "api.access": "enabled",
        "webhooks.outbound": "enabled",
        # Enterprise capacity is intentionally contract-configured rather than fake-unlimited.
        "quota.workspace": None,
        "quota.seat": None,
        "quota.evidence_upload.monthly": None,
        "quota.ai_action.monthly": None,
        "quota.deep_investigation.monthly": None,
        "quota.agent_run.monthly": None,
        "quota.report_generation.monthly": None,
        "quota.report_export.monthly": None,
        "quota.active_connector": None,
        "quota.managed_entity": None,
    },
}


PAID_VARIABLE_COST_FEATURES = {
    "intelligence.deep_analysis",
    "intelligence.agentic",
    "reports.generate",
    "reports.pdf_export",
    "reports.email_delivery",
    "connectors.live",
    "connectors.oauth_documents",
    "connectors.custom_api",
    "agents.execute_safe",
    "agents.execute_approval_gated",
    "api.access",
}


@dataclass(frozen=True)
class EffectiveEntitlements:
    organization_id: str
    plan: str
    plan_version: str
    customer_class: str
    organization_type: str | None
    subscription_status: str
    values: dict[str, Any]
    sources: dict[str, str]

    def value(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def state(self, key: str) -> str:
        value = self.values.get(key, "unavailable")
        if isinstance(value, bool):
            return "enabled" if value else "locked"
        return value if isinstance(value, str) and value in FEATURE_STATES else "unavailable"

    def enabled(self, key: str, *, allow_preview: bool = False) -> bool:
        state = self.state(key)
        return state == "enabled" or (allow_preview and state == "preview")


def canonical_plan(plan: str | None) -> str:
    return str(plan_by_id(plan)["id"])


def _table_exists(db: Session, table: str) -> bool:
    try:
        return inspect(db.get_bind()).has_table(table)
    except Exception:
        return False


def _active_window(now: datetime, starts: datetime | None, ends: datetime | None) -> bool:
    return (starts is None or starts <= now) and (ends is None or ends > now)


def _contract_values(db: Session, org: Organization, now: datetime) -> dict[str, Any]:
    if not _table_exists(db, "commercial_contracts"):
        return {}
    rows = (
        db.query(CommercialContract)
        .filter(CommercialContract.organization_id == org.id, CommercialContract.status.in_(["active", "executed"]))
        .order_by(CommercialContract.created_at.asc())
        .all()
    )
    merged: dict[str, Any] = {}
    for row in rows:
        if not _active_window(now, row.effective_from, row.effective_to):
            continue
        metadata = row.metadata_json or {}
        values = metadata.get("entitlements") if isinstance(metadata, dict) else None
        if isinstance(values, dict):
            merged.update(values)
    return merged


def _override_values(db: Session, org: Organization, now: datetime) -> dict[str, Any]:
    if not _table_exists(db, "entitlement_overrides"):
        return {}
    rows = (
        db.query(EntitlementOverride)
        .filter(EntitlementOverride.organization_id == org.id)
        .order_by(EntitlementOverride.created_at.asc())
        .all()
    )
    merged: dict[str, Any] = {}
    for row in rows:
        if _active_window(now, row.valid_from, row.valid_until):
            value = row.value_json
            merged[row.feature_key] = value.get("value") if isinstance(value, dict) and set(value) == {"value"} else value
    return merged


def resolve_effective_entitlements(db: Session, org: Organization, *, at_time: datetime | None = None) -> EffectiveEntitlements:
    now = at_time or datetime.utcnow()
    plan = canonical_plan(org.plan)
    values = dict(BASE_ENTITLEMENTS[plan])
    sources = {key: f"plan:{plan}" for key in values}

    for key, value in _contract_values(db, org, now).items():
        values[key] = value
        sources[key] = "commercial_contract"

    for key, value in _override_values(db, org, now).items():
        values[key] = value
        sources[key] = "organization_override"

    if plan != "free" and org.subscription_status not in ACTIVE_PAID_STATES:
        for key in PAID_VARIABLE_COST_FEATURES:
            if key in values and values[key] not in {"unavailable", "locked"}:
                values[key] = "locked"
                sources[key] = f"subscription:{org.subscription_status or 'inactive'}"

    return EffectiveEntitlements(
        organization_id=org.id,
        plan=plan,
        plan_version=getattr(org, "plan_version", None) or PLAN_VERSION,
        customer_class=getattr(org, "customer_class", None) or "individual_operator",
        organization_type=getattr(org, "organization_type", None),
        subscription_status=org.subscription_status or "inactive",
        values=values,
        sources=sources,
    )


def feature_state(db: Session, org: Organization, feature_key: str) -> str:
    return resolve_effective_entitlements(db, org).state(feature_key)


def has_feature(db: Session, org: Organization, feature_key: str, *, allow_preview: bool = False) -> bool:
    return resolve_effective_entitlements(db, org).enabled(feature_key, allow_preview=allow_preview)


def require_feature(
    db: Session,
    org: Organization,
    feature_key: str,
    *,
    recommended_plan: str | None = None,
    allow_preview: bool = False,
) -> EffectiveEntitlements:
    effective = resolve_effective_entitlements(db, org)
    state = effective.state(feature_key)
    if effective.enabled(feature_key, allow_preview=allow_preview):
        return effective
    code = "subscription_inactive" if str(effective.sources.get(feature_key, "")).startswith("subscription:") else "upgrade_required"
    detail: dict[str, Any] = {
        "code": code,
        "feature": feature_key,
        "feature_state": state,
        "message": "This capability is not enabled for the organization's current commercial state.",
    }
    if recommended_plan:
        detail["recommended_plan"] = recommended_plan
    raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)


def get_limit(db: Session, org: Organization, key: str) -> int | None:
    value = resolve_effective_entitlements(db, org).value(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def customer_safe_entitlement_payload(db: Session, org: Organization) -> dict[str, Any]:
    effective = resolve_effective_entitlements(db, org)
    capabilities = {
        key: value
        for key, value in effective.values.items()
        if not key.startswith("quota.")
    }
    quotas = {
        key.removeprefix("quota."): value
        for key, value in effective.values.items()
        if key.startswith("quota.")
    }
    return {
        "plan": effective.plan,
        "plan_version": effective.plan_version,
        "customer_class": effective.customer_class,
        "organization_type": effective.organization_type,
        "subscription_status": effective.subscription_status,
        "intelligence_profile": effective.value("intelligence.profile", "essential"),
        "capabilities": capabilities,
        "quotas": quotas,
    }
