"""Worldwide onboarding and localization truth for Commercial Intelligence.

2. Any ISO 3166-1 country and ISO 4217 currency is accepted; countries without
   a specific Market Pack resolve to global_physical and never fail.
3. Customer-visible Commercial Intelligence text is shipped as identifiers the
   portal renders through the 60-locale catalog, never as English prose; the
   deterministic Ask fallback carries language-neutral facts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.market_data_adapters import ADAPTERS
from app.services.market_intelligence import compute_position
from app.services.market_intelligence_ai import deterministic_brief
from app.services.market_intelligence_ask import SCENARIO_PARSE_LANGUAGES, deterministic_context_facts, scenario_parse_status
from app.services.market_normalization import (
    _COMMODITIES,
    _UNIT_ALIASES,
    country_default_currency,
    country_registry,
    country_timezone,
    currency_registry,
    validate_country_code,
    validate_currency_code,
)
from app.services.market_packs import _PACKS, infer_onboarding
from tests.test_commercial_intelligence_global import act_as, identity, no_network, onboard  # noqa: F401 - no_network is an autouse fixture

REPO = Path(__file__).resolve().parents[2]
COPY_SOURCE = (REPO / "figma-enterprise-v4" / "src" / "app" / "components" / "commercialCopy.ts").read_text(encoding="utf-8")


def _ts_record(name: str) -> dict[str, str]:
    match = re.search(rf"export const {name}: Record<string, string> = \{{(.*?)\}};", COPY_SOURCE, re.S)
    assert match, name
    return dict(re.findall(r'([A-Za-z0-9_]+): "([^"]+)"', match.group(1)))


# ---------------------------------------------------------------------------
# 2. Worldwide onboarding
# ---------------------------------------------------------------------------


def test_registries_cover_every_iso_country_and_tender_currency():
    countries, currencies = country_registry(), currency_registry()
    assert len([c for c in countries.values() if c["iso3166_assigned"]]) == 249
    assert len(currencies) >= 150
    assert all(row["default_currency"] in currencies for row in countries.values() if row["default_currency"])
    assert {"XOF", "XAF", "ZWG", "SLE", "VES", "NPR", "MNT", "FJD"} <= set(currencies)
    assert country_default_currency("BG") == "EUR"  # euro since 2026-01-01


@pytest.mark.parametrize("country,currency", [
    ("NP", "NPR"), ("MN", "MNT"), ("FJ", "FJD"), ("ZW", "USD"), ("UZ", "UZS"), ("HT", "HTG"),
    ("PG", "PGK"), ("BD", "BDT"), ("BO", "BOB"), ("LA", "LAK"), ("MW", "MWK"), ("XK", "EUR"),
])
def test_previously_omitted_countries_infer_safely_to_the_global_pack(country, currency):
    inferred = infer_onboarding(crop="maize", country_code=country)
    assert inferred["pack_id"] == "global_physical"
    assert inferred["local_currency"] == currency and inferred["reporting_currency"] == currency
    assert inferred["warnings"] == []
    assert country_timezone(country) != "UTC"


def test_country_without_a_currency_still_onboards_with_an_explicit_warning():
    inferred = infer_onboarding(crop="wheat", country_code="AQ")
    assert inferred["pack_id"] == "global_physical" and inferred["local_currency"] is None
    assert inferred["warnings"] == ["currency_not_inferred"]


def test_registry_validation_rejects_unknown_codes():
    assert validate_country_code("np") == "NP" and validate_currency_code("zwg") == "ZWG"
    for bad in ("ZZ", "EU", "UK", "1A"):
        with pytest.raises(ValueError):
            validate_country_code(bad)
    for bad in ("ABC", "BGN_", "EURO", "BTC"):
        with pytest.raises(ValueError):
            validate_currency_code(bad)


def test_onboarding_api_accepts_any_country_and_rejects_invalid_codes(client, db):
    act_as(*identity(db, "worldwide"))
    created = onboard(client, crop="rice", country_code="NP", region="Chitwan", season="2026", expected_production="40", quantity_unit="tonne",
                      contracts=[{"quantity": "10", "price": "300", "currency": "USD"}])
    assert created["position"]["reporting_currency"] == "NPR" and created["inferred"]["pack_id"] == "global_physical"
    assert client.post("/v1/market-intelligence/onboarding/infer", json={"crop": "rice", "country_code": "ZZ"}).status_code == 422
    bad_currency = client.post("/v1/market-intelligence/onboarding", json={
        "crop": "rice", "country_code": "NP", "season": "2026", "expected_production": "1", "reporting_currency": "ABC"})
    assert bad_currency.status_code == 422
    bad_contract = client.post("/v1/market-intelligence/onboarding", json={
        "crop": "rice", "country_code": "NP", "season": "2026", "expected_production": "1", "contracts": [{"quantity": "1", "price": "1", "currency": "XYZ"}]})
    assert bad_contract.status_code == 422


# ---------------------------------------------------------------------------
# 3. Localization truth
# ---------------------------------------------------------------------------


def test_inference_ships_identifiers_not_english_prose():
    inferred = infer_onboarding(crop="unknown-crop", country_code="BR", region="Atlantis")
    assert "pack_name" not in inferred and "notes" not in inferred
    assert all(set(slot) == {"role", "provider_id"} for slot in inferred["evidence_plan"])
    assert all(re.fullmatch(r"[a-z_]+", code) for code in inferred["warnings"])


def test_portal_copy_covers_every_backend_identifier():
    assert set(_ts_record("PACK_LABELS")) == {pack.pack_id for pack in _PACKS}
    assert set(_ts_record("PROVIDER_LABELS")) == set(ADAPTERS)
    assert set(_ts_record("COMMODITY_LABELS")) == set(_COMMODITIES)
    assert set(_ts_record("UNIT_LABELS")) == set(_UNIT_ALIASES.values())
    access = {adapter.access for adapter in ADAPTERS.values()} - {"public_no_key"}
    assert access <= set(_ts_record("ACCESS_HINTS"))
    economics = (REPO / "agroai_api" / "app" / "services" / "market_intelligence.py").read_text(encoding="utf-8")
    assert set(re.findall(r'missing_inputs\.append\("([a-z_]+)"\)', economics)) == set(_ts_record("MISSING_INPUT_LABELS"))
    warnings = set(re.findall(r'warning_codes\.append\("([a-z_]+)"\)', economics))
    packs = (REPO / "agroai_api" / "app" / "services" / "market_packs.py").read_text(encoding="utf-8")
    warnings |= set(re.findall(r'warnings\.append\("([a-z_]+)"\)', packs)) | {"calculation_error"}
    assert warnings <= set(_ts_record("WARNING_LABELS"))
    api = (REPO / "agroai_api" / "app" / "api" / "v1" / "market_intelligence.py").read_text(encoding="utf-8")
    assert set(re.findall(r'"code": "([a-z_]+)",\n\s+"params"', api)) <= set(re.findall(r"^  ([a-z_]+): \{ title:", COPY_SOURCE, re.M))


def test_every_portal_copy_label_is_in_the_authored_locale_source():
    source = set(json.loads((REPO / "shared" / "localization" / "source.json").read_text(encoding="utf-8"))["catalog"].values())
    names = ("PACK_LABELS", "PROVIDER_LABELS", "ACCESS_HINTS", "UNIT_LABELS", "COMMODITY_LABELS", "WARNING_LABELS", "MISSING_INPUT_LABELS",
             "EVIDENCE_LABELS", "LEVER_LABELS", "STATE_LABELS", "LEVEL_LABELS", "DRIVER_LABELS", "IMPORTANCE_LABELS")
    missing = sorted(value for name in names for value in _ts_record(name).values() if value not in source)
    templates = re.findall(r'^  [a-z_]+: "([^"]+)",$', re.search(r"const FACT_TEMPLATES = \{(.*?)\n\} as const;", COPY_SOURCE, re.S).group(1), re.M)
    missing += [value for value in templates if value not in source]
    assert missing == []  # each would render in English in every locale


def test_every_economics_warning_has_a_stable_code():
    position = SimpleNamespace(
        reporting_currency="USD", price_currency="BRL", local_currency="BRL", fx_rate_to_reporting=None, expected_production="100",
        inventory_quantity="50", quantity_unit="tonne", production_cost_per_unit="10", current_realizable_price="20",
        freight_per_unit="0", storage_per_unit="0", metadata_json={"cost_currency": "EUR"}, id="p", organization_id="o", name="n",
    )
    contracts = [SimpleNamespace(status="active", quantity="500", quantity_unit="tonne", price="1", currency="EUR", fx_rate_to_reporting=None)]
    payload = compute_position(position, contracts).payload
    assert len(payload["warning_codes"]) == len(payload["warnings"]) >= 4
    assert {"over_contracted", "contract_fx_missing", "market_fx_missing", "cost_fx_missing"} <= set(payload["warning_codes"])


def test_deterministic_fallback_carries_facts_for_locales_without_server_templates():
    position = {"exposed_percent": "80.00", "projected_margin_percent": "12.50", "warnings": ["x"], "warning_codes": ["over_contracted"]}
    context = {
        "reporting_currency": "BRL",
        "scenarios": [{"status": "ok", "assumptions": {"price_pct": "-8"}, "projected_margin": "100.00", "delta_projected_margin": "-20.00", "exposed_revenue": "50.00"}],
        "data_states": [{"evidence": "contract_fx:USD-1", "state": "UNAVAILABLE"}],
        "material_changes": [{"level": "HIGH", "position_name": "Soja"}],
        "price_source": {"provider": "conab_precos", "source_name": "CONAB", "state": "DELAYED", "observed_at": "2026-09-25T00:00:00Z"},
    }
    japanese = deterministic_brief(position, question="?", language="ja-JP", context=context)
    assert japanese["client_render_required"] is True and japanese["requested_language"] == "ja"
    codes = [fact["code"] for fact in japanese["facts"]]
    assert codes == ["exposed", "margin", "position_warnings", "scenario", "not_forecast", "stale", "change", "source"]
    rendered = set(re.findall(r'case "([a-z_]+)":', COPY_SOURCE))
    assert set(codes) | {"scenario_no_margin", "missing_data"} <= rendered  # every fact code renders in the portal
    portuguese = deterministic_brief(position, question="?", language="pt-BR", context=context)
    assert portuguese["client_render_required"] is False and "Cenário" in portuguese["summary"]
    assert deterministic_context_facts(context)[0]["params"]["assumptions"] == {"price_pct": "-8"}


def test_free_text_scenario_parsing_reports_unsupported_languages_explicitly():
    assert scenario_parse_status("価格が8%下がったら?", "ja", [])["status"] == "unsupported_language"
    assert scenario_parse_status("What if price falls 8%?", "en", [{"status": "ok"}])["status"] == "parsed"
    assert scenario_parse_status("Where does my price come from?", "ja", [])["status"] == "not_requested"
    assert scenario_parse_status("Preço cai 8%", "pt-BR", [])["status"] == "not_understood"
    assert scenario_parse_status("x 5%", "de", [])["supported_languages"] == list(SCENARIO_PARSE_LANGUAGES)


def test_ask_response_includes_parse_status_and_facts(client, db, monkeypatch):
    monkeypatch.setattr("app.services.market_intelligence_ai.ModelRouter.mode", lambda _self: "offline")
    act_as(*identity(db, "ask-ja"))
    created = onboard(client, crop="corn", country_code="US", region="Iowa", season="2026", expected_production="1000",
                      production_cost_per_unit="3", local_price="4.4")
    response = client.post("/v1/market-intelligence/ask", json={"position_id": created["id"], "question": "価格が8%下がったら?", "language": "ja"}).json()
    assert response["scenario_parse"]["status"] == "unsupported_language"
    assert response["intelligence"]["status"] == "deterministic" and response["intelligence"]["client_render_required"] is True
    assert response["intelligence"]["facts"]


@pytest.mark.parametrize("component", ["CommercialIntelligenceHome.tsx", "CommercialOnboarding.tsx", "MarketIntelligence.tsx", "MarketIntelligenceV2.tsx"])
def test_every_declared_market_intelligence_copy_string_is_authored(component):
    # Lowercase, hyphenated or acronym-led copy ("tonnes", "Break-even",
    # "AGRO-AI will use") used to escape extraction and render in English.
    text = (REPO / "figma-enterprise-v4" / "src" / "app" / "components" / component).read_text(encoding="utf-8")
    block = re.search(r"const COPY = \[(.*?)\] as const;", text, re.S)
    assert block, component
    declared = [json.loads(f'"{value}"') for value in re.findall(r'"((?:[^"\\]|\\.)*)"', block.group(1))]
    source = set(json.loads((REPO / "shared" / "localization" / "source.json").read_text(encoding="utf-8"))["catalog"].values())
    assert [value for value in declared if " ".join(value.split()) not in source] == []



def test_fx_availability_is_judged_for_the_actual_currency_pair(client, db):
    act_as(*identity(db, "fx-pairs"))
    def plan(country, reporting=None):
        body = client.post("/v1/market-intelligence/onboarding/infer", json={"crop": "maize", "country_code": country, **({"reporting_currency": reporting} if reporting else {})}).json()
        return {slot["provider_id"]: slot["status"] for slot in body["evidence_plan"] if slot["role"] == "fx_rate"}
    # ECB has no UGX rate: the portal must ask for the customer's own rate.
    assert plan("UG", "USD") == {"fx_reference": "NOT_COVERED"}
    assert plan("BR", "USD") == {"bcb_ptax": "DELAYED", "fx_reference": "DELAYED"}
    assert plan("SN", "USD")["fx_reference"] == "DELAYED"  # CFA franc via exact EUR parity
    assert plan("BR", "BRL") == {"bcb_ptax": "NOT_REQUIRED", "fx_reference": "NOT_REQUIRED"}


def test_unsupported_onboarding_units_are_rejected_not_stored_as_null(client, db):
    act_as(*identity(db, "units"))
    base = {"crop": "rice", "country_code": "NP", "season": "2026", "expected_production": "10"}
    assert client.post("/v1/market-intelligence/onboarding", json={**base, "quantity_unit": "furlong"}).status_code == 422
    bad_contract = client.post("/v1/market-intelligence/onboarding", json={**base, "contracts": [{"quantity": "1", "price": "1", "quantity_unit": "furlong"}]})
    assert bad_contract.status_code == 422
    ok = client.post("/v1/market-intelligence/onboarding", json={**base, "quantity_unit": "Quintals", "contracts": [{"quantity": "1", "price": "1", "quantity_unit": "kg"}]})
    assert ok.status_code == 201 and ok.json()["inferred"]["quantity_unit"] == "quintal"
