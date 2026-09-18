import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.market_data_providers import (
    MarketDataProvider,
    MarketDataRequest,
    NotConfiguredMarketDataProvider,
    ProviderObservation,
    ResilientMarketDataProvider,
)
from app.services.market_intelligence import (
    MarketCalculationError,
    compute_position,
    convert_quantity,
    data_health,
    scenario_position,
)
from app.services.market_intelligence_ai import (
    generate_market_brief,
    validate_decision_support_policy,
    validate_numeric_grounding,
)


def position(**overrides):
    values = {
        "id": "pos-1",
        "position_key": "test-position",
        "name": "Test position",
        "commodity": "corn",
        "season": "2026",
        "country_code": "US",
        "region": "Iowa",
        "market_structure": "hybrid",
        "reporting_currency": "USD",
        "quantity_unit": "bushel",
        "expected_production": Decimal("100000"),
        "inventory_quantity": Decimal("10000"),
        "production_cost_per_unit": Decimal("3.50"),
        "current_realizable_price": Decimal("4.50"),
        "price_currency": "USD",
        "fx_rate_to_reporting": None,
        "freight_per_unit": Decimal("0.10"),
        "storage_per_unit": Decimal("0.05"),
        "metadata_json": {
            "production_cost_behavior": "fixed_total_at_baseline_yield",
            "inventory_cost_per_unit": "3.50",
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def contract(**overrides):
    values = {
        "status": "active",
        "quantity": Decimal("30000"),
        "quantity_unit": "bushel",
        "price": Decimal("4.40"),
        "currency": "USD",
        "fx_rate_to_reporting": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_corn_bushel_conversion_is_commodity_specific():
    pounds = convert_quantity(Decimal("1"), "bushel", "pound", "corn")
    assert abs(pounds - Decimal("56")) < Decimal("0.0001")
    with pytest.raises(MarketCalculationError):
        convert_quantity(Decimal("1"), "bushel", "tonne", "almonds")
    with pytest.raises(MarketCalculationError):
        convert_quantity(Decimal("1"), "bushel", "tonne", "rice")


def test_position_math_is_deterministic_decimal_economics():
    result = compute_position(position(), [contract()]).payload
    assert result["contracted_quantity"] == "30000.00000000"
    assert result["marketable_supply"] == "110000.00000000"
    assert result["uncontracted_quantity"] == "80000.00000000"
    assert result["contracted_percent"] == "27.2727"
    assert result["projected_revenue"] == "492000.00"
    assert result["projected_cost"] == "401500.00"
    assert result["projected_margin"] == "90500.00"
    assert result["data_complete"] is True


def test_missing_contract_fx_suppresses_margin_instead_of_partial_total():
    br_position = position(
        commodity="soybeans",
        quantity_unit="tonne",
        reporting_currency="USD",
        expected_production=Decimal("5000"),
        production_cost_per_unit=Decimal("350"),
        current_realizable_price=Decimal("2200"),
        price_currency="BRL",
        fx_rate_to_reporting=Decimal("0.18"),
        freight_per_unit=Decimal("20"),
        storage_per_unit=Decimal("5"),
    )
    br_contract = contract(
        quantity=Decimal("1000"), quantity_unit="tonne", price=Decimal("2150"), currency="BRL", fx_rate_to_reporting=None
    )
    result = compute_position(br_position, [br_contract]).payload
    assert result["projected_revenue"] is None
    assert result["projected_margin"] is None
    assert "contract_fx" in result["missing_inputs"]
    assert result["data_complete"] is False


def test_over_contracting_suppresses_projected_margin():
    result = compute_position(position(expected_production=Decimal("100"), inventory_quantity=Decimal("0")), [contract(quantity=Decimal("120"))]).payload
    assert result["over_contracted"] is True
    assert result["uncontracted_quantity"] == "0.00000000"
    assert result["projected_revenue"] is None
    assert result["projected_margin"] is None


def test_zero_change_scenario_is_exact_invariant():
    result = scenario_position(position(), [contract()], {
        "price_pct": 0,
        "yield_pct": 0,
        "fx_pct": 0,
        "production_cost_pct": 0,
        "freight_per_unit_delta": 0,
        "storage_per_unit_delta": 0,
        "sell_pct_now": 0,
    })
    assert result["zero_change_invariant"] is True
    assert result["result"] == result["baseline"]
    assert result["delta"]["projected_revenue"] == "0.00"


def test_fx_scenario_revalues_market_price_and_foreign_currency_contracts():
    br_position = position(
        commodity="soybeans",
        quantity_unit="tonne",
        reporting_currency="USD",
        expected_production=Decimal("100"),
        inventory_quantity=Decimal("0"),
        current_realizable_price=Decimal("2000"),
        price_currency="BRL",
        fx_rate_to_reporting=Decimal("0.20"),
        production_cost_per_unit=Decimal("100"),
        freight_per_unit=Decimal("0"),
        storage_per_unit=Decimal("0"),
    )
    br_contract = contract(
        quantity=Decimal("50"), quantity_unit="tonne", price=Decimal("1800"),
        currency="BRL", fx_rate_to_reporting=Decimal("0.20"),
    )
    scenario = scenario_position(br_position, [br_contract], {"fx_pct": 10})
    assert scenario["baseline"]["locked_revenue"] == "18000.00"
    assert scenario["result"]["locked_revenue"] == "19800.00"
    assert scenario["result"]["projected_revenue"] == "41800.00"


def test_scenario_rejects_negative_costs_and_unreconciled_sell_now():
    with pytest.raises(MarketCalculationError, match="cannot be negative"):
        scenario_position(position(), [contract()], {"freight_per_unit_delta": -1})
    foreign_contract = contract(currency="BRL", fx_rate_to_reporting=None)
    with pytest.raises(MarketCalculationError, match="reconciled position"):
        scenario_position(position(), [foreign_contract], {"sell_pct_now": 25})
    with pytest.raises(MarketCalculationError, match="positive uncontracted production"):
        scenario_position(position(expected_production=Decimal("0"), inventory_quantity=Decimal("0")), [], {"sell_pct_now": 25})


def test_specialty_crop_does_not_require_futures_market():
    almonds = position(
        commodity="almonds", market_structure="physical", quantity_unit="pound",
        expected_production=Decimal("1000000"), inventory_quantity=Decimal("0"), current_realizable_price=Decimal("2.30"),
        production_cost_per_unit=Decimal("1.65"), freight_per_unit=Decimal("0.08"), storage_per_unit=Decimal("0.03"),
    )
    almond_contract = contract(quantity=Decimal("250000"), quantity_unit="pound", price=Decimal("2.25"))
    result = compute_position(almonds, [almond_contract]).payload
    assert result["market_structure"] == "physical"
    assert result["projected_margin"] is not None
    assert result["contracted_percent"] == "25.0000"


def test_yield_decline_preserves_fixed_baseline_production_costs():
    scenario = scenario_position(position(inventory_quantity=Decimal("0")), [contract()], {"yield_pct": -20})
    assert scenario["baseline"]["fixed_production_cost_total"] == "350000.00"
    assert scenario["result"]["fixed_production_cost_total"] == "350000.00"
    assert scenario["result"]["expected_production"] == "80000.00000000"


def test_inventory_requires_cost_basis_for_margin_but_still_counts_as_supply():
    without_basis = position(metadata_json={"production_cost_behavior": "fixed_total_at_baseline_yield"})
    result = compute_position(without_basis, [contract()]).payload
    assert result["marketable_supply"] == "110000.00000000"
    assert result["projected_revenue"] == "492000.00"
    assert result["projected_cost"] is None
    assert result["projected_margin"] is None
    assert result["break_even_price"] is None
    assert "inventory_cost_per_unit" in result["missing_inputs"]


def test_missing_production_cost_never_becomes_zero_cost_margin():
    result = compute_position(
        position(
            inventory_quantity=Decimal("0"),
            production_cost_per_unit=None,
            metadata_json={"production_cost_behavior": "fixed_total_at_baseline_yield"},
        ),
        [contract()],
    ).payload
    assert result["projected_revenue"] == "447000.00"
    assert result["production_cost_per_unit"] is None
    assert result["fixed_production_cost_total"] is None
    assert result["projected_cost"] is None
    assert result["break_even_price"] is None
    assert result["projected_margin"] is None
    assert "production_cost_per_unit" in result["missing_inputs"]
    assert result["data_complete"] is False


def test_ai_numeric_claims_must_reference_exact_structured_evidence():
    evidence = {"projected_margin": "82000.00"}
    valid = {
        "summary": "Projected margin is 82,000.",
        "insights": [{
            "title": "Margin",
            "explanation": "Projected margin is 82000.00.",
            "evidence_ids": ["projected_margin"],
            "numeric_claims": [{"evidence_id": "projected_margin", "value": "82000.00"}],
        }],
        "limitations": [],
    }
    invalid = {
        "summary": "Projected margin is 90,000.",
        "insights": [{
            "title": "Margin",
            "explanation": "Projected margin is 90000.",
            "evidence_ids": ["projected_margin"],
            "numeric_claims": [{"evidence_id": "projected_margin", "value": "90000"}],
        }],
    }
    invented = {
        "insights": [{
            "title": "Invented",
            "explanation": "Value is 10.",
            "evidence_ids": ["invented"],
            "numeric_claims": [{"evidence_id": "invented", "value": "10"}],
        }],
    }
    assert validate_numeric_grounding(valid, evidence) == []
    assert validate_numeric_grounding(invalid, evidence)
    assert validate_numeric_grounding(invented, evidence)


def test_ai_prose_cannot_hide_an_unstructured_numeric_claim():
    evidence = {"projected_margin": "82000.00"}
    payload = {
        "summary": "Projected margin is 95000.",
        "insights": [{
            "title": "Margin",
            "explanation": "The margin is materially exposed.",
            "evidence_ids": ["projected_margin"],
            "numeric_claims": [{"evidence_id": "projected_margin", "value": "82000.00"}],
        }],
        "limitations": [],
    }
    errors = validate_numeric_grounding(payload, evidence)
    assert any(error.startswith("unstructured_numeric_claim:summary") for error in errors)


def test_ai_cannot_emit_personalized_derivatives_instruction():
    unsafe = {
        "summary": "Short December soybean futures now.",
        "insights": [],
        "limitations": [],
    }
    assert validate_decision_support_policy(unsafe) == ["personalized_derivatives_instruction"]
    safe = {
        "summary": "Review commercial exposure and compare educational hedge scenarios.",
        "insights": [],
        "limitations": [],
    }
    assert validate_decision_support_policy(safe) == []
    for wording in (
        "Establish a hedge with soybean futures.",
        "Use 12 contracts to hedge this exposure.",
        "Initiate an options hedge for this farm.",
    ):
        assert "personalized_derivatives_instruction" in validate_decision_support_policy(
            {"summary": wording, "insights": [], "limitations": [], "actions": []}
        )
    assert validate_decision_support_policy({
        "summary": "Verify the contract register.",
        "insights": [],
        "limitations": [],
        "actions": [{"kind": "execute_trade", "description": "Act"}],
    }) == ["disallowed_action_kind:execute_trade"]


def test_ai_action_descriptions_cannot_hide_trade_instructions_or_numbers():
    unsafe_policy = {
        "summary": "Review the current exposure.",
        "insights": [],
        "limitations": [],
        "actions": [{"kind": "compare", "description": "Use 12 soybean futures contracts to hedge this exposure."}],
    }
    policy_errors = validate_decision_support_policy(unsafe_policy)
    assert "personalized_derivatives_instruction" in policy_errors

    numeric_errors = validate_numeric_grounding(unsafe_policy, {})
    assert any(error.startswith("unstructured_numeric_claim:action_0") for error in numeric_errors)

    safe = {
        "summary": "Review the current exposure.",
        "insights": [],
        "limitations": [],
        "actions": [{"kind": "verify", "description": "Verify the contract register against the latest signed records."}],
    }
    assert validate_decision_support_policy(safe) == []
    assert validate_numeric_grounding(safe, {}) == []


def test_all_model_outage_keeps_deterministic_brief_available(monkeypatch):
    monkeypatch.setattr("app.services.market_intelligence_ai.ModelRouter.mode", lambda _self: "offline")
    computed = compute_position(position(), [contract()])
    result = asyncio.run(generate_market_brief(computed.payload, computed.evidence, question="What matters?"))
    assert result["status"] == "deterministic"
    assert result["model_trace"]["provider"] == "deterministic"
    assert result["model_trace"]["grounded"] is True


def test_unsupported_fallback_language_is_truthfully_labelled_english(monkeypatch):
    monkeypatch.setattr("app.services.market_intelligence_ai.ModelRouter.mode", lambda _self: "offline")
    computed = compute_position(position(), [contract()])
    result = asyncio.run(generate_market_brief(computed.payload, computed.evidence, language="sw-KE"))
    assert result["response_language"] == "en"
    assert "remains commercially exposed" in result["summary"]


def test_model_derivatives_instruction_triggers_policy_fallback(monkeypatch):
    unsafe = {
        "summary": "Short December soybean futures now.",
        "insights": [],
        "confidence": "low",
        "limitations": [],
    }

    class FakeRouter:
        def mode(self):
            return "online"

        async def run(self, **_kwargs):
            result = SimpleNamespace(
                status="ok", content=json.dumps(unsafe), error=None, provider="fake", model="fake-model"
            )
            selection = SimpleNamespace(model="fake-model", profile="test")
            return result, selection

    monkeypatch.setattr("app.services.market_intelligence_ai.ModelRouter", FakeRouter)
    computed = compute_position(position(), [contract()])
    result = asyncio.run(generate_market_brief(computed.payload, computed.evidence))
    assert result["status"] == "deterministic"
    assert result["model_trace"]["fallback_reason"] == "decision_support_policy_failed"


def test_live_provider_observation_requires_verified_upstream_provenance():
    from datetime import datetime
    with pytest.raises(ValueError):
        ProviderObservation(
            evidence_id="x", observation_type="price", provider="untrusted", source_name="untrusted",
            source_status="LIVE", value=Decimal("1"), unit="USD/t", currency="USD",
            observed_at=datetime.utcnow(), retrieved_at=datetime.utcnow(), metadata={},
        )


def test_provider_runtime_retries_caches_and_opens_circuit():
    class FlakyProvider(MarketDataProvider):
        provider_id = "flaky"

        def __init__(self):
            self.calls = 0

        async def status(self):
            return {"status": "LIVE"}

        async def observations(self, _request):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary")
            now = datetime.now(timezone.utc)
            return [ProviderObservation(
                evidence_id="verified", observation_type="cash_price", provider=self.provider_id,
                source_name="Verified", source_status="LIVE", value=Decimal("1"), unit="USD/t",
                currency="USD", observed_at=now, retrieved_at=now,
                licensing={"display_allowed": True},
                metadata={"upstream_request_verified": True, "freshness_max_age_minutes": 30},
            )]

    provider = FlakyProvider()
    runtime = ResilientMarketDataProvider(provider, max_attempts=2, cache_ttl_seconds=60)
    request = MarketDataRequest(commodity="corn", country_code="US")
    first = asyncio.run(runtime.observations(request))
    second = asyncio.run(runtime.observations(request))
    assert first[0].evidence_id == "verified"
    assert second[0].evidence_id == "verified"
    assert provider.calls == 2

    class BrokenProvider(FlakyProvider):
        provider_id = "broken"

        async def observations(self, _request):
            self.calls += 1
            raise TimeoutError("down")

    broken = BrokenProvider()
    guarded = ResilientMarketDataProvider(
        broken, max_attempts=1, circuit_failure_threshold=1, circuit_reset_seconds=60,
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(guarded.observations(request))
    with pytest.raises(RuntimeError, match="circuit open"):
        asyncio.run(guarded.observations(request))
    assert broken.calls == 1


def test_unconfigured_provider_reports_truthfully_and_returns_no_observations():
    provider = NotConfiguredMarketDataProvider(
        "government_cash_market",
        source_name="Government cash market",
        configuration_hint="Configure approved access.",
    )
    status = asyncio.run(provider.status())
    rows = asyncio.run(provider.observations(MarketDataRequest(commodity="corn", country_code="US")))
    assert status["status"] == "NOT_CONFIGURED"
    assert rows == []


def test_data_health_is_conservative_for_manual_mixed_and_derived_stale_sources():
    now = datetime.now(timezone.utc)
    live_stale = SimpleNamespace(
        evidence_id="live-old", provider="licensed", source_name="Licensed feed", source_status="LIVE",
        observation_type="cash_price", unit="USD/t", currency="USD",
        observed_at=now - timedelta(minutes=90), retrieved_at=now - timedelta(minutes=85),
        quality_json={"confidence": "high"}, licensing_json={"display_allowed": True},
        metadata_json={"freshness_max_age_minutes": 30},
    )
    demo = SimpleNamespace(
        evidence_id="demo", provider="demo", source_name="Demo", source_status="DEMO",
        observation_type="cash_price", unit="USD/t", currency="USD",
        observed_at=now, retrieved_at=now, quality_json={"synthetic": True},
        licensing_json={"display_allowed": True}, metadata_json={},
    )
    health = data_health([live_stale, demo])
    assert health["status"] == "degraded"
    assert health["confidence"] != "high"
    assert health["derived_stale_count"] == 1
    assert health["mixed_demo_and_non_demo"] is True
    stale = next(source for source in health["sources"] if source["evidence_id"] == "live-old")
    assert stale["declared_status"] == "LIVE"
    assert stale["status"] == "STALE"
    assert stale["freshness_max_age_minutes"] == 30

    manual = SimpleNamespace(
        evidence_id="manual", provider="customer", source_name="Customer input", source_status="MANUAL",
        observation_type="cash_price", unit="USD/t", currency="USD", observed_at=now, retrieved_at=now,
        quality_json={}, licensing_json={}, metadata_json={},
    )
    manual_health = data_health([manual])
    assert manual_health["confidence"] != "high"
    assert manual_health["missing_freshness_count"] == 1
