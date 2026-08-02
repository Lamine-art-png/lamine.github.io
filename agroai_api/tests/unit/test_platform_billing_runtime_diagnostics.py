from __future__ import annotations

from app.billing_bootstrap import (
    LIVE_CAPABILITIES,
    apply_live_billing_bootstrap,
    diagnose_live_billing_environment,
    safe_runtime_billing_status,
)


def _live_environment() -> dict[str, str]:
    return {
        "PLATFORM_API_STRIPE_MODE": "live",
        "PLATFORM_API_PLAN_CATALOG_VERSION": "2026-07-provisional",
        "PLATFORM_API_OPERATION_COST_CATALOG_VERSION": "2026-07-provisional",
        "PLATFORM_API_STRIPE_SECRET_KEY": "sk_live_contract",
        "PLATFORM_API_STRIPE_WEBHOOK_SECRET": "whsec_contract",
        "PLATFORM_API_STRIPE_METER_ID": "mtr_contract",
        "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID": "price_dev_month",
        "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID": "price_dev_year",
        "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_OVERAGE_PRICE_ID": "price_dev_over_month",
        "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_OVERAGE_PRICE_ID": "price_dev_over_year",
        "PLATFORM_API_STRIPE_SCALE_MONTHLY_PRICE_ID": "price_scale_month",
        "PLATFORM_API_STRIPE_SCALE_ANNUAL_PRICE_ID": "price_scale_year",
        "PLATFORM_API_STRIPE_SCALE_MONTHLY_OVERAGE_PRICE_ID": "price_scale_over_month",
        "PLATFORM_API_STRIPE_SCALE_ANNUAL_OVERAGE_PRICE_ID": "price_scale_over_year",
    }


def test_meter_event_name_safely_defaults_to_the_canonical_constant():
    values = _live_environment()
    diagnosis = diagnose_live_billing_environment(values)
    assert diagnosis["complete_live_configuration"] is True
    assert diagnosis["meter_event_name_valid"] is True
    assert diagnosis["missing"] == []
    assert diagnosis["invalid"] == []


def test_diagnostics_report_names_but_never_secret_values():
    values = _live_environment()
    values.pop("PLATFORM_API_STRIPE_SCALE_ANNUAL_OVERAGE_PRICE_ID")
    values["PLATFORM_API_STRIPE_WEBHOOK_SECRET"] = "wrong"
    diagnosis = diagnose_live_billing_environment(values)
    rendered = repr(diagnosis)
    assert diagnosis["complete_live_configuration"] is False
    assert diagnosis["missing"] == ["PLATFORM_API_STRIPE_SCALE_ANNUAL_OVERAGE_PRICE_ID"]
    assert diagnosis["invalid"] == ["PLATFORM_API_STRIPE_WEBHOOK_SECRET"]
    assert "sk_live_contract" not in rendered
    assert "wrong" not in rendered


def test_complete_configuration_bootstraps_every_flag_and_reports_ready():
    values = _live_environment()
    diagnosis = apply_live_billing_bootstrap(values)
    status = safe_runtime_billing_status(values)
    assert diagnosis["complete_live_configuration"] is True
    assert status["status"] == "ready"
    assert status["bootstrapped"] is True
    assert status["stripe_secret_source"] == "dedicated"
    assert all(status["effective_flags"].values())
    assert all(values[name] == "true" for name in LIVE_CAPABILITIES)


def test_partial_configuration_remains_closed():
    values = _live_environment()
    values.pop("PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID")
    apply_live_billing_bootstrap(values)
    status = safe_runtime_billing_status(values)
    assert status["status"] == "not_ready"
    assert status["bootstrapped"] is False
    assert status["missing"] == ["PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID"]


def test_missing_platform_key_inherits_existing_shared_live_server_key():
    values = _live_environment()
    values.pop("PLATFORM_API_STRIPE_SECRET_KEY")
    values["STRIPE_SECRET_KEY"] = "sk_live_existing_saas_server_key"

    diagnosis = apply_live_billing_bootstrap(values)
    status = safe_runtime_billing_status(values)

    assert diagnosis["shared_live_secret_inherited"] is True
    assert values["PLATFORM_API_STRIPE_SECRET_KEY"] == "sk_live_existing_saas_server_key"
    assert status["status"] == "ready"
    assert status["stripe_secret_source"] == "dedicated"
    assert "sk_live_existing_saas_server_key" not in repr(status)


def test_test_or_malformed_shared_key_never_crosses_live_boundary():
    for unsafe_value in ("sk_test_not_live", "rk_live_restricted", "not-a-key", ""):
        values = _live_environment()
        values.pop("PLATFORM_API_STRIPE_SECRET_KEY")
        values["STRIPE_SECRET_KEY"] = unsafe_value

        diagnosis = apply_live_billing_bootstrap(values)
        status = safe_runtime_billing_status(values)

        assert diagnosis["shared_live_secret_inherited"] is False
        assert "PLATFORM_API_STRIPE_SECRET_KEY" not in values
        assert status["status"] == "not_ready"
        assert status["missing"] == ["PLATFORM_API_STRIPE_SECRET_KEY"]
        assert unsafe_value not in repr(status)


def test_dedicated_platform_key_takes_precedence_over_shared_key():
    values = _live_environment()
    values["STRIPE_SECRET_KEY"] = "sk_test_should_not_replace_dedicated"

    diagnosis = apply_live_billing_bootstrap(values)
    status = safe_runtime_billing_status(values)

    assert diagnosis["shared_live_secret_inherited"] is False
    assert values["PLATFORM_API_STRIPE_SECRET_KEY"] == "sk_live_contract"
    assert status["status"] == "ready"
