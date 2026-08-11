from __future__ import annotations


VALID_PLATFORM_STRIPE_MODES = frozenset({"test", "live"})


def normalized_platform_stripe_mode(value: str | None) -> str:
    return str(value or "").strip().lower()


def platform_stripe_configuration_error(
    *,
    mode: str | None,
    secret_key: str | None,
) -> str | None:
    normalized = normalized_platform_stripe_mode(mode)
    if normalized not in VALID_PLATFORM_STRIPE_MODES:
        return "api_billing_stripe_mode_invalid"
    prefix = "sk_live_" if normalized == "live" else "sk_test_"
    if not str(secret_key or "").startswith(prefix):
        return "api_billing_stripe_key_mode_mismatch"
    return None


def platform_stripe_livemode_matches(*, mode: str | None, livemode: bool) -> bool:
    normalized = normalized_platform_stripe_mode(mode)
    return normalized in VALID_PLATFORM_STRIPE_MODES and livemode == (
        normalized == "live"
    )
