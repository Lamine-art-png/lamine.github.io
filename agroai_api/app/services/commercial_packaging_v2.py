"""AGRO-AI commercial packaging v2.

This module is the product-packaging source of truth for connector minimum tiers
and evidence-import capacity. It intentionally distinguishes standard Custom API
access (Network+) from bespoke custom integration work (Enterprise/contract).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

PACKAGING_VERSION = "2026-07.2"
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
    normalized = str(plan or "free").lower()
    aliases = {
        "pilot": "free",
        "pro": "professional",
        "waterops": "professional",
        "assurance_audit": "professional",
        "assurance": "team",
    }
    return EVIDENCE_UPLOAD_LIMITS.get(aliases.get(normalized, normalized), EVIDENCE_UPLOAD_LIMITS["free"])


def apply_catalog_packaging(catalog: list[dict[str, Any]]) -> None:
    """Apply exact provider minimum tiers to the customer-visible connector catalog."""
    for item in catalog:
        provider = str(item.get("id") or "")
        if provider:
            item["required_plan"] = required_plan_for_provider(provider)


def install_commercial_packaging_v2() -> None:
    """Synchronize legacy plan structures with the v2 packaging contract.

    The application still exposes a few compatibility plan structures. This
    installer updates data mappings only; it never replaces endpoint code.
    """
    from app.services.commercial_control import BASE_ENTITLEMENTS
    from app.services.entitlements import PLAN_LIMITS
    from app.services.product_plans import PLANS

    for plan_id, limit in EVIDENCE_UPLOAD_LIMITS.items():
        BASE_ENTITLEMENTS[plan_id]["quota.evidence_upload.monthly"] = limit

    # Standard Custom API access starts at Network. Bespoke provider-specific
    # integration remains a distinct Enterprise/contract capability.
    BASE_ENTITLEMENTS["network"]["connectors.custom_api"] = "enabled"
    BASE_ENTITLEMENTS["enterprise"]["connectors.custom_api"] = "enabled"

    for plan_id, limit in EVIDENCE_UPLOAD_LIMITS.items():
        if limit is None or plan_id not in PLAN_LIMITS:
            continue
        PLAN_LIMITS[plan_id] = replace(PLAN_LIMITS[plan_id], max_uploads_monthly=limit)

    # Refresh aliases that may still reference older frozen PlanLimits objects.
    for alias in ("pilot", "assurance_audit", "waterops", "assurance", "pro"):
        canonical = {
            "pilot": "free",
            "assurance_audit": "professional",
            "waterops": "professional",
            "assurance": "team",
            "pro": "professional",
        }[alias]
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
    if network is not None and "Standard Custom API access" not in network.get("features", []):
        network.setdefault("features", []).append("Standard Custom API access")

    professional = next((plan for plan in PLANS if plan.get("id") == "professional"), None)
    if professional is not None:
        features = professional.setdefault("features", [])
        for feature in ("Weather context", "OpenET / ET context"):
            if feature not in features:
                features.append(feature)
