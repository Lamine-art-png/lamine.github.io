from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_platform_billing() -> None:
    path = ROOT / "agroai_api/app/api/v1/platform_billing.py"
    text = path.read_text(encoding="utf-8")

    if "from app.billing_bootstrap import safe_runtime_billing_status" not in text:
        text = replace_once(
            text,
            "from app.api.deps import AuthContext, require_platform_admin\n",
            "from app.api.deps import AuthContext, require_platform_admin\n"
            "from app.billing_bootstrap import safe_runtime_billing_status\n",
            "billing bootstrap import",
        )

    helper = '''\n\ndef _checkout_subscription_reusable(row: PlatformApiSubscription | None) -> bool:\n    """Allow a new Checkout only when no Stripe subscription was created.\n\n    A browser can close or cancel Stripe Checkout after AGRO-AI persists the\n    local `checkout_pending` row. Reusing that row is safe only while it has no\n    Stripe subscription identity. Every Stripe-mapped or active lifecycle row\n    remains protected by the existing single-subscription conflict.\n    """\n\n    return bool(\n        row is not None\n        and not str(row.stripe_subscription_id or "").strip()\n        and row.status in {"checkout_pending", "canceled"}\n    )\n'''
    anchor = '\n\n@router.get("/pricing")\n'
    if "def _checkout_subscription_reusable" not in text:
        text = replace_once(text, anchor, helper + anchor, "checkout retry helper")

    readiness = '''\n\n@router.get("/billing-readiness")\ndef billing_readiness() -> dict:\n    """Return only non-secret live billing launch diagnostics.\n\n    The endpoint exists even while pricing is closed so production automation\n    can identify a missing or malformed variable name without exposing any\n    configured value, identifier, customer, or key fragment.\n    """\n\n    payload = safe_runtime_billing_status()\n    payload["settings_flags"] = {\n        name: bool(getattr(settings, name, False))\n        for name in (\n            "PLATFORM_API_BILLING_ENABLED",\n            "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",\n            "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",\n            "PLATFORM_API_PRICING_ENABLED",\n            "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",\n        )\n    }\n    return payload\n'''
    if '@router.get("/billing-readiness")' not in text:
        text = replace_once(text, anchor, readiness + anchor, "billing readiness route")

    text = replace_once(
        text,
        '        if existing and existing.status not in {"canceled"}:\n'
        '            raise HTTPException(status_code=409, detail={"code": "api_subscription_already_exists"})\n',
        '        if existing and not _checkout_subscription_reusable(existing):\n'
        '            raise HTTPException(status_code=409, detail={"code": "api_subscription_already_exists"})\n',
        "checkout retry guard",
    )
    path.write_text(text, encoding="utf-8")


def patch_workflow() -> None:
    path = ROOT / ".github/workflows/platform-api-billing-deep-production-verification.yml"
    text = path.read_text(encoding="utf-8")

    diagnostic_step = '''\n      - name: Diagnose effective live billing bootstrap\n        shell: bash\n        run: |\n          set -euo pipefail\n          curl --fail --silent --show-error --max-time 30 \\\n            "${BACKEND_ORIGIN}/v1/platform/billing-readiness" -o billing-readiness.json\n          cat billing-readiness.json\n          python3 - <<'PY'\n          import json\n          value = json.load(open("billing-readiness.json", encoding="utf-8"))\n          assert value.get("status") == "ready", value\n          assert value.get("bootstrapped") is True, value\n          assert value.get("complete_live_configuration") is True, value\n          assert value.get("missing") == [], value\n          assert value.get("invalid") == [], value\n          assert all((value.get("effective_flags") or {}).values()), value\n          assert all((value.get("settings_flags") or {}).values()), value\n          print("billing_bootstrap=green")\n          PY\n'''
    pricing_anchor = "\n      - name: Verify active commercial pricing\n"
    if "- name: Diagnose effective live billing bootstrap" not in text:
        text = replace_once(text, pricing_anchor, diagnostic_step + pricing_anchor, "billing diagnostic step")

    if '"/v1/platform/billing-readiness": "get",' not in text:
        text = replace_once(
            text,
            '              "/v1/platform/pricing": "get",\n',
            '              "/v1/platform/billing-readiness": "get",\n'
            '              "/v1/platform/pricing": "get",\n',
            "diagnostic OpenAPI route",
        )

    text = replace_once(
        text,
        '- API and database readiness: green\\n- Developer and Scale catalog:',
        '- API and database readiness: green\\n- non-secret billing bootstrap diagnostic: green\\n- Developer and Scale catalog:',
        "success evidence diagnostic",
    )

    if "            billing-readiness.json\n" not in text:
        text = replace_once(
            text,
            "            readiness.json\n",
            "            readiness.json\n            billing-readiness.json\n",
            "diagnostic artifact",
        )

    # Changes to the bootstrap helper must trigger this workflow after merge.
    if "      - agroai_api/app/billing_bootstrap.py\n" not in text:
        text = replace_once(
            text,
            "      - agroai_api/start-production.sh\n",
            "      - agroai_api/start-production.sh\n"
            "      - agroai_api/app/__init__.py\n"
            "      - agroai_api/app/billing_bootstrap.py\n"
            "      - agroai_api/app/api/v1/platform_billing.py\n",
            "workflow path triggers",
        )

    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_platform_billing()
    patch_workflow()


if __name__ == "__main__":
    main()
