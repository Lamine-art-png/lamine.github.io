"""Commercial policy for the variable-cost Ask AGRO-AI surface.

Ask AGRO-AI is intentionally a paid capability. Free remains useful for
workspace setup, evidence ingestion, readiness, and basic operations, but model
inference starts at Professional. The installer is idempotent because the API
package can be imported more than once in tests and process bootstraps.
"""
from __future__ import annotations

from dataclasses import replace

from app.services.commercial_control import BASE_ENTITLEMENTS, PAID_VARIABLE_COST_FEATURES
from app.services.entitlements import PLAN_LIMITS
from app.services.product_plans import PLANS


_INSTALLED = False


def install_ask_agro_ai_commercial_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    free = BASE_ENTITLEMENTS["free"]
    free["intelligence.ask"] = "locked"
    free["quota.ai_action.monthly"] = 0
    free["quota.deep_investigation.monthly"] = 0
    PAID_VARIABLE_COST_FEATURES.add("intelligence.ask")

    # Keep the legacy customer-safe compatibility serializer aligned with the
    # canonical commercial control plane. Otherwise Free would still advertise
    # 25 AGRO-AI messages and can_run_agro_ai=true despite the authoritative 402.
    PLAN_LIMITS["free"] = replace(
        PLAN_LIMITS["free"],
        max_agro_ai_messages_monthly=0,
    )
    PLAN_LIMITS["pilot"] = PLAN_LIMITS["free"]

    for plan in PLANS:
        if plan.get("id") == "free":
            limits = dict(plan.get("included_limits") or {})
            limits.pop("messages", None)
            plan["included_limits"] = limits

            locked = [
                item
                for item in list(plan.get("locked_features") or [])
                if item != "Advanced intelligence"
            ]
            for item in ("Ask AGRO-AI", "Deep analysis"):
                if item not in locked:
                    locked.append(item)
            plan["locked_features"] = locked

        if plan.get("id") == "professional":
            features = list(plan.get("features") or [])
            if "Ask AGRO-AI" not in features:
                features.insert(0, "Ask AGRO-AI")
            plan["features"] = features

    _INSTALLED = True
