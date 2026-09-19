from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.commercial_intelligence import (
    ADVISORY_SCOPES,
    MAX_TOPUP_CENTS,
    MIN_TOPUP_CENTS,
    PUBLIC_MODEL,
    TASK_CATALOG,
    IntelligenceRequest,
    WalletCheckoutRequest,
)


def test_commercial_intelligence_surface_is_small_and_paid() -> None:
    # Browser self-service and machine routes are intentionally composed from
    # separate routers. The production contract is the final FastAPI app.
    from app.main import app

    required = {
        ("POST", "/v1/intelligence"),
        ("GET", "/v1/intelligence/pricing"),
        ("GET", "/v1/platform/developer/wallet"),
        ("POST", "/v1/platform/developer/wallet/sync"),
        ("POST", "/v1/platform/developer/wallet/checkout"),
        ("POST", "/v1/platform/developer/intelligence/bootstrap"),
        ("POST", "/v1/platform/developer/intelligence/run"),
    }
    registered = [
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if (method, route.path) in required
    ]
    assert set(registered) == required
    assert len(registered) == len(required), "commercial route+method registrations must be unique"
    assert PUBLIC_MODEL == "agroai-intelligence-1"
    assert TASK_CATALOG
    assert all(int(item["price_cents"]) > 0 for item in TASK_CATALOG.values())


def test_self_service_live_key_is_advisory_only() -> None:
    assert ADVISORY_SCOPES == ["intelligence:run"]
    assert "actions:execute" not in ADVISORY_SCOPES
    assert "connectors:write" not in ADVISORY_SCOPES
    assert "connectors:sync" not in ADVISORY_SCOPES


def test_intelligence_input_rejects_credentials() -> None:
    with pytest.raises(ValidationError):
        IntelligenceRequest(
            task="field_diagnosis",
            question="What changed?",
            input={"crop": "almond", "api_key": "do-not-store"},
        )


def test_intelligence_input_is_bounded() -> None:
    with pytest.raises(ValidationError):
        IntelligenceRequest(
            task="answer",
            question="Analyze this.",
            input={"blob": "x" * 300_000},
        )


def test_wallet_checkout_is_bounded() -> None:
    assert MIN_TOPUP_CENTS == 500
    assert MAX_TOPUP_CENTS == 500_000
    with pytest.raises(ValidationError):
        WalletCheckoutRequest(amount_cents=499)
    with pytest.raises(ValidationError):
        WalletCheckoutRequest(amount_cents=500_001)
