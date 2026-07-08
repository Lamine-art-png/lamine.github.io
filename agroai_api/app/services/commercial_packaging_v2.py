"""Commercial packaging v2 for quotas and connector minimum tiers."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

PACKAGING_VERSION = "2026-07.3"
PLAN_ORDER = ("free", "professional", "team", "network", "enterprise")

EVIDENCE_UPLOAD_LIMITS: dict[str, int | None] = {
    "free": 15,
    "professional": 500,
    "team": 2_500,
    "network": 10_000,
    "enterprise": None,
}

CONNECTOR_REQUIRED_PLAN: dict[str, str] = {
    "manual_csv": "free",
    "chat_upload": "free",
    "wiseconn": "professional",
    "talgil": "professional",
    "weather": "professional",
    "openet": "professional",
    "gmail": "professional",
    "outlook": "professional",
    "google_drive": "professional",
    "dropbox": "professional",
    "box": "professional",
    "slack": "professional",
    "custom_api": "network",
    "universal_controller": "enterprise",
    "salesforce": "enterprise",
    "google_earth_engine": "enterprise",
}

DOCUMENT_OAUTH_PROVIDERS = {"gmail", "outlook", "google_drive", "dropbox", "box", "slack"}
ENTERPRISE_INTEGRATION_PROVIDERS = {"universal_controller", "salesforce", "google_earth_engine"}
MANUAL_EVIDENCE_PROVIDERS = {"manual_csv", "chat_upload"}


def required_plan_for_provider(provider: str) -> str:
    return CONNECTOR_REQUIRED_PLAN.get(provider, "professional")


def feature_for_provider(provider: str) -> str:
    if provider in MANUAL_EVIDENCE_PROVIDERS:
        return "connectors.manual_upload"
    if provider in DOCUMENT_OAUTH_PROVIDERS:
        return "connectors.oauth_documents"
    if provider == "custom_api":
        return "connectors.custom_api"
    if provider in ENTERPRISE_INTEGRATION_PROVIDERS:
        return "connectors.custom_integration"
    return "connectors.live"


def evidence_limit_for_plan(plan: str | None) -> int | None:
    aliases = {
        "pilot": "free",
        "pro": "professional",
        "waterops": "professional",
        "assurance_audit": "professional",
        "assurance": "team",
    }
    normalized = str(plan or "free").lower()
    return EVIDENCE_UPLOAD_LIMITS.get(aliases.get(normalized, normalized), EVIDENCE_UPLOAD_LIMITS["free"])


def apply_catalog_packaging(catalog: list[dict[str, Any]]) -> None:
    for item in catalog:
        provider = str(item.get("id") or "")
        if provider:
            item["required_plan"] = required_plan_for_provider(provider)


def install_commercial_packaging_v2() -> None:
    from app.services import connector_commercial_guard as guard
    from app.services.commercial_control import BASE_ENTITLEMENTS
    from app.services.entitlements import PLAN_LIMITS
    from app.services.product_plans import PLANS

    for plan_id, limit in EVIDENCE_UPLOAD_LIMITS.items():
        BASE_ENTITLEMENTS[plan_id]["quota.evidence_upload.monthly"] = limit

    BASE_ENTITLEMENTS["network"]["connectors.custom_api"] = "enabled"

    for plan_id, limit in EVIDENCE_UPLOAD_LIMITS.items():
        if limit is not None and plan_id in PLAN_LIMITS:
            PLAN_LIMITS[plan_id] = replace(PLAN_LIMITS[plan_id], max_uploads_monthly=limit)

    alias_targets = {
        "pilot": "free",
        "assurance_audit": "professional",
        "waterops": "professional",
        "assurance": "team",
        "pro": "professional",
    }
    for alias, canonical in alias_targets.items():
        PLAN_LIMITS[alias] = PLAN_LIMITS[canonical]

    upload_copy = {
        "free": "15 evidence/file imports per month",
        "professional": "500 evidence/file imports per month",
        "team": "2,500 evidence/file imports per month",
        "network": "10,000 evidence/file imports per month",
        "enterprise": "Contract-configured import volume",
    }
    for plan in PLANS:
        plan_id = str(plan.get("id") or "")
        if plan_id in upload_copy:
            plan.setdefault("included_limits", {})["uploads"] = upload_copy[plan_id]

    network = next((plan for plan in PLANS if plan.get("id") == "network"), None)
    if network is not None:
        network["annual_savings_badge"] = "Save 17% annually"
        features = network.setdefault("features", [])
        if "Standard Custom API access" not in features:
            features.append("Standard Custom API access")

    professional = next((plan for plan in PLANS if plan.get("id") == "professional"), None)
    if professional is not None:
        professional["annual_savings_badge"] = "Save 17% annually"
        features = professional.setdefault("features", [])
        for feature in ("Weather context", "OpenET / ET context"):
            if feature not in features:
                features.append(feature)

    guard.MANUAL_PROVIDERS = set(MANUAL_EVIDENCE_PROVIDERS)
    guard.DOCUMENT_OAUTH_PROVIDERS = set(DOCUMENT_OAUTH_PROVIDERS)
    guard.CONTRACT_PROVIDERS = set(ENTERPRISE_INTEGRATION_PROVIDERS)

    def _connector_feature(provider: str) -> tuple[str, str | None]:
        required_plan = required_plan_for_provider(provider)
        return feature_for_provider(provider), None if required_plan == "free" else required_plan

    guard.connector_feature = _connector_feature
