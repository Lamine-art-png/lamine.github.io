from __future__ import annotations

from copy import deepcopy


PLANS: list[dict] = [
    {
        "id": "free",
        "name": "Free",
        "public_price_monthly": "$0",
        "public_price_annual": "$0",
        "recommended_buyer": "Pilot users, small growers, and field teams testing AGRO-AI",
        "included_limits": {
            "workspaces": "1 workspace",
            "uploads": "Limited uploads",
            "ai_runs": "Limited AGRO-AI runs",
            "exports": "Basic branded exports",
        },
        "features": [
            "Basic field updates",
            "Basic reports",
            "Starter evidence base",
            "Command Center access",
        ],
        "support_level": "Community and setup guidance",
        "cta_label": "Start pilot",
        "upgrade_path": "professional",
        "is_custom_pricing": False,
    },
    {
        "id": "professional",
        "name": "Professional",
        "public_price_monthly": "$299/month",
        "public_price_annual": "$2,990/year",
        "recommended_buyer": "Commercial farms, packhouses, advisors, irrigated growers, and small co-ops",
        "included_limits": {
            "workspaces": "Up to 3 farms or sites",
            "uploads": "Standard evidence uploads",
            "ai_runs": "Moderate AGRO-AI usage",
            "exports": "Buyer-ready exports",
        },
        "features": [
            "Full field operating loop",
            "Core WaterOps and Assurance workflows",
            "Standard reports",
            "Connector access",
        ],
        "support_level": "Email support",
        "cta_label": "Upgrade to Professional",
        "upgrade_path": "network",
        "is_custom_pricing": False,
    },
    {
        "id": "network",
        "name": "Network",
        "public_price_monthly": "From $1,500/month",
        "public_price_annual": "From $15,000/year",
        "recommended_buyer": "Grower groups, exporters, sourcing teams, water agencies, insurers, and multi-site agribusinesses",
        "included_limits": {
            "workspaces": "Multi-farm dashboards",
            "uploads": "Scaled evidence operations",
            "ai_runs": "Usage-based scaling",
            "exports": "Network and compliance exports",
        },
        "features": [
            "Supplier and compliance workflows",
            "APIs and role controls",
            "Advanced automation",
            "Customer success and implementation planning",
        ],
        "support_level": "Customer success",
        "cta_label": "Contact sales",
        "upgrade_path": None,
        "is_custom_pricing": True,
    },
]


SERVICE_ADD_ONS: list[dict] = [
    {
        "id": "farm_onboarding",
        "name": "Farm onboarding / assurance setup",
        "price": "$3,500-$7,500 one time",
        "description": "Workspace setup, evidence organization, and assurance readiness configuration.",
    },
    {
        "id": "network_implementation",
        "name": "Network implementation / assurance rollout",
        "price": "$12,500-$25,000 one time",
        "description": "Multi-site rollout planning, supplier workflows, and operating cadence setup.",
    },
    {
        "id": "custom_integrations",
        "name": "Custom integrations / special audit prep",
        "price": "Quoted separately",
        "description": "Custom system mapping, audit-specific evidence prep, and integration work.",
    },
]


def public_plans() -> list[dict]:
    return deepcopy(PLANS)


def service_add_ons() -> list[dict]:
    return deepcopy(SERVICE_ADD_ONS)


def plan_by_id(plan_id: str | None) -> dict:
    normalized = (plan_id or "free").lower()
    aliases = {
        "pro": "professional",
        "pilot": "free",
        "waterops": "professional",
        "assurance": "professional",
        "enterprise": "network",
        "internal": "professional",
    }
    target = aliases.get(normalized, normalized)
    for plan in PLANS:
        if plan["id"] == target:
            return deepcopy(plan)
    return deepcopy(PLANS[0])


def upgrade_options(current_plan: str | None) -> list[dict]:
    current = plan_by_id(current_plan)["id"]
    if current == "free":
        return [plan_by_id("professional"), plan_by_id("network")]
    if current == "professional":
        return [plan_by_id("network")]
    return []
