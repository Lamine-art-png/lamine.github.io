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
    router,
)
from app.api.v1.commercial_intelligence_selfserve import router as selfserve_router


def test_commercial_intelligence_surface_is_small_and_paid() -> None:
    paths = {route.path for route in router.routes}
    assert "/intelligence" in paths
    assert "/intelligence/pricing" in paths
    browser_paths = {route.path for route in selfserve_router.routes}
    assert "/platform/developer/wallet" in browser_paths
    assert "/platform/developer/wallet/checkout" in browser_paths
    assert "/platform/developer/intelligence/bootstrap" in browser_paths
    assert "/platform/developer/intelligence/run" in browser_paths
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
