from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BILLING = ROOT / "agroai_api/app/api/v1/platform_billing.py"
DEEP_WORKFLOW = ROOT / ".github/workflows/platform-api-billing-deep-production-verification.yml"
TEST = ROOT / "agroai_api/tests/unit/test_platform_billing_cleanup.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_billing() -> None:
    text = BILLING.read_text(encoding="utf-8")

    if "from app.billing_bootstrap import safe_runtime_billing_status" not in text:
        text = replace_once(
            text,
            "from app.api.deps import AuthContext, require_platform_admin\n",
            "from app.api.deps import AuthContext, require_platform_admin\n"
            "from app.billing_bootstrap import safe_runtime_billing_status\n",
            label="billing bootstrap import",
        )

    helper_and_endpoint = '''\n\ndef _checkout_subscription_reusable(row: PlatformApiSubscription | None) -> bool:\n    """Allow another Checkout only before Stripe created a subscription.\n\n    Closing or canceling Stripe Checkout can leave AGRO-AI with a local\n    `checkout_pending` row. That row is safe to reuse only while it has no\n    Stripe subscription identity. Every Stripe-mapped or active lifecycle row\n    remains protected by the one-subscription invariant.\n    """\n\n    return bool(\n        row is not None\n        and not str(row.stripe_subscription_id or "").strip()\n        and row.status in {"checkout_pending", "canceled"}\n    )\n\n\n@router.get("/billing-readiness")\ndef billing_readiness() -> dict:\n    """Return non-secret billing launch diagnostics even while pricing is closed."""\n\n    payload = safe_runtime_billing_status()\n    payload["settings_flags"] = {\n        name: bool(getattr(settings, name, False))\n        for name in (\n            "PLATFORM_API_BILLING_ENABLED",\n            "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",\n            "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",\n            "PLATFORM_API_PRICING_ENABLED",\n            "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",\n        )\n    }\n    return payload\n'''
    anchor = '\n\n@router.get("/pricing")\n'
    if "def _checkout_subscription_reusable" not in text:
        text = replace_once(
            text,
            anchor,
            helper_and_endpoint + anchor,
            label="retry helper and readiness endpoint",
        )

    old_guard = (
        '        if existing and existing.status not in {"canceled"}:\n'
        '            raise HTTPException(status_code=409, detail={"code": "api_subscription_already_exists"})\n'
    )
    new_guard = (
        '        if existing and not _checkout_subscription_reusable(existing):\n'
        '            raise HTTPException(status_code=409, detail={"code": "api_subscription_already_exists"})\n'
    )
    if old_guard in text:
        text = replace_once(text, old_guard, new_guard, label="checkout retry guard")
    elif new_guard not in text:
        raise RuntimeError("checkout retry guard: expected old or new guard")

    BILLING.write_text(text, encoding="utf-8")


def patch_deep_workflow() -> None:
    text = DEEP_WORKFLOW.read_text(encoding="utf-8")

    trigger_anchor = "      - agroai_api/start-production.sh\n"
    extra_triggers = (
        "      - agroai_api/app/__init__.py\n"
        "      - agroai_api/app/billing_bootstrap.py\n"
        "      - agroai_api/app/api/v1/platform_billing.py\n"
    )
    if extra_triggers not in text:
        text = replace_once(
            text,
            trigger_anchor,
            trigger_anchor + extra_triggers,
            label="deep workflow path triggers",
        )

    diagnostic_step = '''\n      - name: Verify effective live billing bootstrap\n        shell: bash\n        run: |\n          set -euo pipefail\n          curl --fail --silent --show-error --max-time 30 \\\n            "${BACKEND_ORIGIN}/v1/platform/billing-readiness" -o billing-readiness.json\n          cat billing-readiness.json\n          python3 - <<'PY'\n          import json\n          value = json.load(open("billing-readiness.json", encoding="utf-8"))\n          assert value.get("status") == "ready", value\n          assert value.get("bootstrapped") is True, value\n          assert value.get("complete_live_configuration") is True, value\n          assert value.get("missing") == [], value\n          assert value.get("invalid") == [], value\n          assert all((value.get("effective_flags") or {}).values()), value\n          assert all((value.get("settings_flags") or {}).values()), value\n          print("billing_bootstrap=green")\n          PY\n'''
    pricing_anchor = "\n      - name: Verify active commercial pricing\n"
    if "- name: Verify effective live billing bootstrap" not in text:
        text = replace_once(
            text,
            pricing_anchor,
            diagnostic_step + pricing_anchor,
            label="deep billing diagnostic step",
        )

    route_anchor = '              "/v1/platform/pricing": "get",\n'
    if '              "/v1/platform/billing-readiness": "get",\n' not in text:
        text = replace_once(
            text,
            route_anchor,
            '              "/v1/platform/billing-readiness": "get",\n' + route_anchor,
            label="readiness OpenAPI contract",
        )

    success_old = "- API and database readiness: green\\n- Developer and Scale catalog:"
    success_new = "- API and database readiness: green\\n- non-secret billing bootstrap diagnostic: green\\n- Developer and Scale catalog:"
    if success_old in text:
        text = replace_once(text, success_old, success_new, label="success evidence")

    artifact_anchor = "            readiness.json\n"
    if "            billing-readiness.json\n" not in text:
        text = replace_once(
            text,
            artifact_anchor,
            artifact_anchor + "            billing-readiness.json\n",
            label="billing diagnostic artifact",
        )

    DEEP_WORKFLOW.write_text(text, encoding="utf-8")


def write_tests() -> None:
    TEST.write_text(
        '''from __future__ import annotations\n\nimport json\nfrom types import SimpleNamespace\n\nfrom app.api.v1.platform_billing import (\n    _checkout_subscription_reusable,\n    billing_readiness,\n)\n\n\ndef test_abandoned_checkout_without_stripe_subscription_is_reusable():\n    row = SimpleNamespace(status="checkout_pending", stripe_subscription_id=None)\n    assert _checkout_subscription_reusable(row) is True\n\n\ndef test_canceled_checkout_without_stripe_subscription_is_reusable():\n    row = SimpleNamespace(status="canceled", stripe_subscription_id="")\n    assert _checkout_subscription_reusable(row) is True\n\n\ndef test_stripe_mapped_or_active_subscription_is_never_reusable():\n    assert _checkout_subscription_reusable(\n        SimpleNamespace(status="checkout_pending", stripe_subscription_id="sub_live_123")\n    ) is False\n    assert _checkout_subscription_reusable(\n        SimpleNamespace(status="active", stripe_subscription_id=None)\n    ) is False\n\n\ndef test_billing_readiness_never_exposes_configured_secret_values(monkeypatch):\n    secrets = {\n        "PLATFORM_API_STRIPE_SECRET_KEY": "sk_live_super_secret_value",\n        "PLATFORM_API_STRIPE_WEBHOOK_SECRET": "whsec_super_secret_value",\n        "PLATFORM_API_STRIPE_METER_ID": "mtr_secret_identifier",\n        "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID": "price_secret_dev_month",\n    }\n    for name, value in secrets.items():\n        monkeypatch.setenv(name, value)\n    rendered = json.dumps(billing_readiness(), sort_keys=True)\n    for value in secrets.values():\n        assert value not in rendered\n    assert "missing" in rendered\n    assert "invalid" in rendered\n''',
        encoding="utf-8",
    )


def main() -> None:
    patch_billing()
    patch_deep_workflow()
    write_tests()


if __name__ == "__main__":
    main()
