import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.market_data_providers import ProviderObservation
from app.services.market_intelligence import (
    MarketCalculationError,
    compute_position,
    convert_quantity,
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


def test_position_math_is_deterministic_decimal_economics():
    result = compute_position(position(), [contract()]).payload
    assert result["contracted_quantity"] == "30000.00000000"
    assert result["uncontracted_quantity"] == "70000.00000000"
    assert result["contracted_percent"] == "30.0000"
    assert result["projected_revenue"] == "447000.00"
    assert result["projected_cost"] == "365000.00"
    assert result["projected_margin"] == "82000.00"
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
    result = compute_position(position(expected_production=Decimal("100")), [contract(quantity=Decimal("120"))]).payload
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
        scenario_position(position(expected_production=Decimal("0")), [], {"sell_pct_now": 25})


def test_specialty_crop_does_not_require_futures_market():
    almonds = position(
        commodity="almonds", market_structure="physical", quantity_unit="pound",
        expected_production=Decimal("1000000"), current_realizable_price=Decimal("2.30"),
        production_cost_per_unit=Decimal("1.65"), freight_per_unit=Decimal("0.08"), storage_per_unit=Decimal("0.03"),
    )
    almond_contract = contract(quantity=Decimal("250000"), quantity_unit="pound", price=Decimal("2.25"))
    result = compute_position(almonds, [almond_contract]).payload
    assert result["market_structure"] == "physical"
    assert result["projected_margin"] is not None
    assert result["contracted_percent"] == "25.0000"


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


def test_all_model_outage_keeps_deterministic_brief_available(monkeypatch):
    monkeypatch.setattr("app.services.market_intelligence_ai.ModelRouter.mode", lambda _self: "offline")
    computed = compute_position(position(), [contract()])
    result = asyncio.run(generate_market_brief(computed.payload, computed.evidence, question="What matters?"))
    assert result["status"] == "deterministic"
    assert result["model_trace"]["provider"] == "deterministic"
    assert result["model_trace"]["grounded"] is True


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
