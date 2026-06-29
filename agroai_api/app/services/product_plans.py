from __future__ import annotations

from copy import deepcopy


PLANS: list[dict] = [
    {
        "id": "free",
        "name": "Free",
        "public_price_monthly": "$0/month",
        "public_price_annual": "$0/year",
        "recommended_buyer": "For pilots and small teams testing AGRO-AI.",
        "included_limits": {
            "users": "1 user",
            "workspaces": "1 workspace",
            "uploads": "10 evidence uploads/month",
            "messages": "25 AGRO-AI messages/month",
        },
        "features": [
            "Basic field updates",
            "Basic readiness view",
            "Basic support request",
        ],
        "locked_features": [
            "PDF reports",
            "Compliance packets",
            "Connectors",
            "Team members",
            "Admin requests",
            "Advanced intelligence",
        ],
        "support_level": "Basic support",
        "cta_label": "Start free",
        "annual_savings_badge": None,
        "is_custom_pricing": False,
    },
    {
        "id": "professional",
        "name": "Professional",
        "public_price_monthly": "$299/month",
        "public_price_annual": "$2,990/year",
        "recommended_buyer": "For commercial farms, advisors, and operators running field operations.",
        "included_limits": {
            "users": "3 seats included",
            "workspaces": "5 workspaces",
            "uploads": "500 evidence uploads/month",
            "messages": "500 AGRO-AI messages/month",
        },
        "features": [
            "Water risk briefs",
            "Operator checklists",
            "Report and PDF generation",
            "Compliance packet drafts",
            "Standard support",
            "Basic integrations and request integration",
        ],
        "locked_features": ["Team invites", "Admin request inbox", "Network rollups"],
        "support_level": "Standard support",
        "cta_label": "Upgrade to Professional",
        "annual_savings_badge": "Save 17% annually",
        "is_custom_pricing": False,
    },
    {
        "id": "team",
        "name": "Team",
        "public_price_monthly": "$799/month",
        "public_price_annual": "$7,990/year",
        "recommended_buyer": "For advisory teams, farm management teams, and multi-site operators.",
        "included_limits": {
            "users": "10 seats included",
            "workspaces": "25 workspaces",
            "uploads": "2,500 evidence uploads/month",
            "messages": "2,500 AGRO-AI messages/month",
        },
        "features": [
            "Team member invites",
            "Role controls",
            "Shared evidence library",
            "Admin request inbox",
            "Advanced reports and PDF",
            "Connector workflows",
            "Priority support",
            "$49/seat/month for additional seats",
        ],
        "locked_features": ["Network rollups", "Enterprise security review"],
        "support_level": "Priority support",
        "cta_label": "Get Team plan",
        "annual_savings_badge": None,
        "is_custom_pricing": False,
    },
    {
        "id": "network",
        "name": "Network",
        "public_price_monthly": "$1,500/month",
        "public_price_annual": "$15,000/year",
        "recommended_buyer": "For grower networks, water districts, exporters, lenders, insurers, and multi-farm programs.",
        "included_limits": {
            "users": "25 seats included",
            "workspaces": "50 workspaces or sites",
            "uploads": "10,000 evidence uploads/month",
            "messages": "10,000 AGRO-AI messages/month",
        },
        "features": [
            "50,000 managed acres included",
            "Network dashboard",
            "Multi-workspace reporting",
            "Compliance and evidence rollups",
            "Partner and customer reporting",
            "Priority onboarding",
        ],
        "locked_features": ["Larger deployments move to Enterprise"],
        "support_level": "Priority onboarding",
        "cta_label": "Start Network rollout",
        "annual_savings_badge": None,
        "is_custom_pricing": False,
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "public_price_monthly": "Contact sales",
        "public_price_annual": "Contact sales",
        "recommended_buyer": "For agencies, lenders, insurers, food companies, and national-scale networks.",
        "included_limits": {
            "users": "Custom seats",
            "workspaces": "Custom workspaces",
            "uploads": "Custom upload volume",
            "messages": "Custom AGRO-AI usage",
        },
        "features": [
            "SSO and SAML when available",
            "Audit logs",
            "Custom integrations",
            "Dedicated onboarding",
            "Data governance",
            "Custom reporting",
            "Security review",
            "Enterprise support",
        ],
        "locked_features": [],
        "support_level": "Enterprise support",
        "cta_label": "Contact sales",
        "annual_savings_badge": None,
        "is_custom_pricing": True,
    },
]


SERVICE_ADD_ONS: list[dict] = [
    {
        "id": "onboarding",
        "name": "Onboarding and rollout",
        "price": "Quoted separately",
        "description": "Workspace setup, evidence architecture, role planning, and operating launch support.",
    },
    {
        "id": "custom_integrations",
        "name": "Custom integrations",
        "price": "Quoted separately",
        "description": "Custom controller, document, CRM, and reporting integrations for production rollout.",
    },
    {
        "id": "enterprise_security",
        "name": "Enterprise security review",
        "price": "Quoted separately",
        "description": "Security review, governance alignment, and production launch readiness support.",
    },
]


ALIASES = {
    "pilot": "free",
    "assurance_audit": "professional",
    "waterops": "professional",
    "assurance": "team",
    "pro": "professional",
}


def public_plans() -> list[dict]:
    return deepcopy(PLANS)


def service_add_ons() -> list[dict]:
    return deepcopy(SERVICE_ADD_ONS)


def plan_by_id(plan_id: str | None) -> dict:
    normalized = ALIASES.get((plan_id or "free").lower(), (plan_id or "free").lower())
    for plan in PLANS:
        if plan["id"] == normalized:
            return deepcopy(plan)
    return deepcopy(PLANS[0])


def upgrade_options(current_plan: str | None) -> list[dict]:
    current = plan_by_id(current_plan)["id"]
    if current == "free":
        return [plan_by_id("professional"), plan_by_id("team"), plan_by_id("network")]
    if current == "professional":
        return [plan_by_id("team"), plan_by_id("network"), plan_by_id("enterprise")]
    if current == "team":
        return [plan_by_id("network"), plan_by_id("enterprise")]
    if current == "network":
        return [plan_by_id("enterprise")]
    return []
