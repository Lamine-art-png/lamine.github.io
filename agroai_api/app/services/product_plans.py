"""Canonical AGRO-AI commercial plan catalog.

The catalog is code-backed for the current rollout so runtime authorization stays
cheap and deterministic. Database overrides can refine organization-specific
entitlements without making Stripe or the frontend a request-time dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PLAN_VERSION = "2026-07"

CANONICAL_PLAN_CODES = ("free", "professional", "team", "network", "enterprise")
PAID_PLAN_CODES = {"professional", "team", "network", "enterprise"}
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing", "contracted"}

PLAN_ALIASES = {
    "pilot": "professional",
    "pro": "professional",
    "waterops": "network",
    "assurance": "team",
    "assurance_audit": "team",
}

PLAN_ORDER = {
    "free": 0,
    "professional": 1,
    "team": 2,
    "network": 3,
    "enterprise": 4,
}

CUSTOMER_CLASSES = (
    "individual_operator",
    "professional_operator",
    "operating_team",
    "network_program",
    "institutional_enterprise",
)


@dataclass(frozen=True)
class PublicPrice:
    monthly: int | None
    yearly: int | None
    custom: bool = False


@dataclass(frozen=True)
class PlanDefinition:
    code: str
    name: str
    version: str
    price: PublicPrice
    public: bool
    custom_pricing: bool
    entitlements: dict[str, Any]


def _state(value: str) -> dict[str, str]:
    return {"state": value}


PLAN_CATALOG: dict[str, PlanDefinition] = {
    "free": PlanDefinition(
        code="free",
        name="Free",
        version=PLAN_VERSION,
        price=PublicPrice(monthly=0, yearly=0),
        public=True,
        custom_pricing=False,
        entitlements={
            "quota.seats": 1,
            "quota.workspaces": 1,
            "quota.evidence_upload.monthly": 10,
            "quota.ai_action.monthly": 25,
            "quota.agent_run.monthly": 0,
            "quota.report_export.monthly": 0,
            "intelligence.profile": "essential",
            "intelligence.ask": _state("enabled"),
            "intelligence.deep_analysis": _state("locked"),
            "intelligence.cross_workspace": _state("locked"),
            "evidence.upload": _state("enabled"),
            "reports.generate": _state("enabled"),
            "reports.pdf_export": _state("locked"),
            "reports.email_delivery": _state("locked"),
            "connectors.manual_upload": _state("enabled"),
            "connectors.live": _state("locked"),
            "connectors.provider.wiseconn": _state("locked"),
            "connectors.provider.talgil": _state("locked"),
            "connectors.provider.openet": _state("locked"),
            "team.invite": _state("locked"),
            "team.roles": _state("locked"),
            "agents.plan": _state("locked"),
            "agents.execute_approval_gated": _state("locked"),
            "network.cross_workspace_intelligence": _state("locked"),
            "governance.audit_logs": _state("locked"),
            "governance.sso": _state("unavailable"),
            "api.access": _state("locked"),
        },
    ),
    "professional": PlanDefinition(
        code="professional",
        name="Professional",
        version=PLAN_VERSION,
        price=PublicPrice(monthly=299, yearly=2990),
        public=True,
        custom_pricing=False,
        entitlements={
            "quota.seats": 3,
            "quota.workspaces": 5,
            "quota.evidence_upload.monthly": 500,
            "quota.ai_action.monthly": 500,
            "quota.agent_run.monthly": 500,
            "quota.report_export.monthly": 500,
            "intelligence.profile": "operational",
            "intelligence.ask": _state("enabled"),
            "intelligence.deep_analysis": _state("enabled"),
            "intelligence.cross_workspace": _state("locked"),
            "evidence.upload": _state("enabled"),
            "reports.generate": _state("enabled"),
            "reports.pdf_export": _state("enabled"),
            "reports.email_delivery": _state("locked"),
            "connectors.manual_upload": _state("enabled"),
            "connectors.live": _state("enabled"),
            "connectors.provider.wiseconn": _state("enabled"),
            "connectors.provider.talgil": _state("enabled"),
            "connectors.provider.openet": _state("requestable"),
            "team.invite": _state("locked"),
            "team.roles": _state("locked"),
            "agents.plan": _state("enabled"),
            "agents.execute_approval_gated": _state("requestable"),
            "network.cross_workspace_intelligence": _state("locked"),
            "governance.audit_logs": _state("locked"),
            "governance.sso": _state("unavailable"),
            "api.access": _state("requestable"),
        },
    ),
    "team": PlanDefinition(
        code="team",
        name="Team",
        version=PLAN_VERSION,
        price=PublicPrice(monthly=799, yearly=7990),
        public=True,
        custom_pricing=False,
        entitlements={
            "quota.seats": 10,
            "quota.workspaces": 25,
            "quota.evidence_upload.monthly": 2500,
            "quota.ai_action.monthly": 2500,
            "quota.agent_run.monthly": 2500,
            "quota.report_export.monthly": 2500,
            "intelligence.profile": "collaborative",
            "intelligence.ask": _state("enabled"),
            "intelligence.deep_analysis": _state("enabled"),
            "intelligence.cross_workspace": _state("locked"),
            "evidence.upload": _state("enabled"),
            "reports.generate": _state("enabled"),
            "reports.pdf_export": _state("enabled"),
            "reports.email_delivery": _state("enabled"),
            "connectors.manual_upload": _state("enabled"),
            "connectors.live": _state("enabled"),
            "connectors.provider.wiseconn": _state("enabled"),
            "connectors.provider.talgil": _state("enabled"),
            "connectors.provider.openet": _state("enabled"),
            "team.invite": _state("enabled"),
            "team.roles": _state("enabled"),
            "agents.plan": _state("enabled"),
            "agents.execute_approval_gated": _state("enabled"),
            "network.cross_workspace_intelligence": _state("locked"),
            "governance.audit_logs": _state("requestable"),
            "governance.sso": _state("unavailable"),
            "api.access": _state("requestable"),
        },
    ),
    "network": PlanDefinition(
        code="network",
        name="Network",
        version=PLAN_VERSION,
        price=PublicPrice(monthly=1500, yearly=15000),
        public=True,
        custom_pricing=False,
        entitlements={
            "quota.seats": 25,
            "quota.workspaces": 50,
            "quota.evidence_upload.monthly": 10000,
            "quota.ai_action.monthly": 10000,
            "quota.agent_run.monthly": 10000,
            "quota.report_export.monthly": 10000,
            "quota.managed_entity": 25000,
            "intelligence.profile": "network",
            "intelligence.ask": _state("enabled"),
            "intelligence.deep_analysis": _state("enabled"),
            "intelligence.cross_workspace": _state("enabled"),
            "evidence.upload": _state("enabled"),
            "reports.generate": _state("enabled"),
            "reports.pdf_export": _state("enabled"),
            "reports.email_delivery": _state("enabled"),
            "connectors.manual_upload": _state("enabled"),
            "connectors.live": _state("enabled"),
            "connectors.provider.wiseconn": _state("enabled"),
            "connectors.provider.talgil": _state("enabled"),
            "connectors.provider.openet": _state("enabled"),
            "connectors.custom_api": _state("requestable"),
            "team.invite": _state("enabled"),
            "team.roles": _state("enabled"),
            "agents.plan": _state("enabled"),
            "agents.execute_approval_gated": _state("enabled"),
            "network.cross_workspace_intelligence": _state("enabled"),
            "network.portfolio_analytics": _state("enabled"),
            "governance.audit_logs": _state("requestable"),
            "governance.sso": _state("requestable"),
            "api.access": _state("enabled"),
        },
    ),
    "enterprise": PlanDefinition(
        code="enterprise",
        name="Enterprise",
        version=PLAN_VERSION,
        price=PublicPrice(monthly=None, yearly=None, custom=True),
        public=True,
        custom_pricing=True,
        entitlements={
            "quota.seats": 25,
            "quota.workspaces": 50,
            "quota.evidence_upload.monthly": 10000,
            "quota.ai_action.monthly": 10000,
            "quota.agent_run.monthly": 10000,
            "quota.report_export.monthly": 10000,
            "quota.managed_entity": 25000,
            "intelligence.profile": "institutional",
            "intelligence.ask": _state("enabled"),
            "intelligence.deep_analysis": _state("enabled"),
            "intelligence.cross_workspace": _state("enabled"),
            "evidence.upload": _state("enabled"),
            "reports.generate": _state("enabled"),
            "reports.pdf_export": _state("enabled"),
            "reports.email_delivery": _state("enabled"),
            "connectors.manual_upload": _state("enabled"),
            "connectors.live": _state("enabled"),
            "connectors.provider.wiseconn": _state("enabled"),
            "connectors.provider.talgil": _state("enabled"),
            "connectors.provider.openet": _state("enabled"),
            "connectors.custom_api": _state("requestable"),
            "connectors.custom_integration": _state("requestable"),
            "team.invite": _state("enabled"),
            "team.roles": _state("enabled"),
            "agents.plan": _state("enabled"),
            "agents.execute_approval_gated": _state("enabled"),
            "network.cross_workspace_intelligence": _state("enabled"),
            "network.portfolio_analytics": _state("enabled"),
            "governance.audit_logs": _state("requestable"),
            "governance.sso": _state("requestable"),
            "governance.custom_retention": _state("requestable"),
            "api.access": _state("enabled"),
        },
    ),
}


def normalize_plan_code(plan: str | None) -> str:
    code = (plan or "free").strip().lower()
    code = PLAN_ALIASES.get(code, code)
    return code if code in PLAN_CATALOG else "free"


def public_plan_catalog() -> list[dict[str, Any]]:
    return [
        {
            "code": plan.code,
            "name": plan.name,
            "version": plan.version,
            "public": plan.public,
            "custom_pricing": plan.custom_pricing,
            "price": {
                "monthly": plan.price.monthly,
                "yearly": plan.price.yearly,
                "custom": plan.price.custom,
            },
            "entitlements": plan.entitlements,
        }
        for plan in PLAN_CATALOG.values()
        if plan.public
    ]


def recommended_plan_for_feature(feature_key: str) -> str | None:
    for code in CANONICAL_PLAN_CODES:
        value = PLAN_CATALOG[code].entitlements.get(feature_key)
        if isinstance(value, dict) and value.get("state") in {"enabled", "preview"}:
            return code
        if value is True:
            return code
    return None
