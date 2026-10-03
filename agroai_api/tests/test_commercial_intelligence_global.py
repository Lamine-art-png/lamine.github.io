"""Global Commercial Intelligence matrix.

Seven representative markets (Brazil soy, U.S. corn, California almonds,
Australian wheat, India rice, Kenya maize, French wheat) plus the shared data
plane, materiality, alerts, provenance, licensing, tenant isolation, scenario
engine v2, risk context, grounded Ask and the scheduled cycle.

No test touches the network: shared-plane evidence is seeded through the same
persistence path the scheduled cycle uses, and adapters run on fixtures.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.deps import AuthContext, get_auth_context
from app.main import app
from app.models.market_intelligence import (
    MarketContractPosition,
    MarketDataPoint,
    MarketDataSeries,
    MarketMaterialityEvent,
    MarketObservation,
    MarketPosition,
    MarketPositionSnapshot,
    MarketProviderRun,
)
from app.models.saas import ManagedEntity, Organization, OrganizationMembership, User
from app.services import market_data_plane as plane
from app.services import market_intelligence_refresh as refresh_module
from app.services.market_data_adapters import (
    ADAPTERS,
    BCBPtaxSeries,
    CONABWeeklyPricesSeries,
    ECBReferenceRatesSeries,
    EUAgriFoodPricesSeries,
    IndiaAgmarknetSeries,
    SeriesDescriptor,
    SeriesPoint,
    USDAMyMarketNewsSeries,
    USDANASSQuickStatsSeries,
    licensing,
)
from app.services.market_intelligence import compute_position, scenario_position
from app.services.market_intelligence_ask import parse_scenario_intents, requested_language
from app.services.market_materiality import evaluate_position
from app.services.market_normalization import canonical_commodity, parse_decimal, parse_price_unit
from app.services.market_packs import infer_onboarding, resolve_pack
from app.services.market_risk import historical_move_statistics

NOW = datetime.now(timezone.utc)
PUBLIC = licensing(license_id="test-open", attribution="Test source")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Positions resolve from seeded shared evidence; nothing calls an upstream."""
    async def no_ingest(db, position, *, trigger="on_demand"):
        return {}

    monkeypatch.setattr(refresh_module, "ensure_position_evidence", no_ingest)
    yield
    app.dependency_overrides.pop(get_auth_context, None)


def identity(db, suffix, role="owner"):
    user = User(email=f"ci-{suffix}@example.com", email_verification_status="verified")
    db.add(user)
    db.flush()
    org = Organization(name=f"CI {suffix}", slug=f"ci-{suffix}", owner_user_id=user.id, verification_status="approved")
    db.add(org)
    db.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role=role, status="active")
    db.add(membership)
    db.commit()
    return user, org, membership


def act_as(user, org, membership):
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user, organization=org, membership=membership)


def series_point(series_key, value, *, provider, observation_type="physical_price", commodity=None, country=None, region=None,
                 market=None, unit="tonne", currency="USD", base=None, days_ago=1, frequency="weekly", fresh_days=14,
                 last_known_days=30, license_=None):
    descriptor = SeriesDescriptor(
        provider=provider, series_key=series_key, source_name=f"{provider} test series", observation_type=observation_type,
        commodity=commodity, country_code=country, region=region, market_name=market, unit=unit, currency=currency,
        base_currency=base, frequency=frequency, freshness_max_age_minutes=fresh_days * 1440,
        last_known_max_age_minutes=last_known_days * 1440, licensing=license_ or PUBLIC,
    )
    return SeriesPoint(descriptor=descriptor, observed_at=NOW - timedelta(days=days_ago), value=Decimal(str(value)), retrieved_at=NOW)


def seed(db, *points):
    stats = plane.persist_points(db, list(points))
    db.commit()
    return stats


def seed_fx(db, days_ago=1):
    # ECB publishes units per EUR.
    rates = {"USD": "1.08", "BRL": "5.70", "AUD": "1.62", "INR": "90.10", "GBP": "0.84"}
    seed(db, *[
        series_point(f"fx_reference:EUR:{ccy}", value, provider="fx_reference", observation_type="fx_rate", unit=f"{ccy}/EUR",
                     currency=ccy, base="EUR", days_ago=days_ago, frequency="daily_business", fresh_days=3, last_known_days=7)
        for ccy, value in rates.items()
    ])


def onboard(client, **payload):
    response = client.post("/v1/market-intelligence/onboarding", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Normalization and packs
# ---------------------------------------------------------------------------


def test_normalization_handles_global_number_unit_and_commodity_formats():
    assert parse_decimal("€244,36") == Decimal("244.36")
    assert parse_decimal("€554.00") == Decimal("554.00")
    assert parse_decimal("1.234,56") == Decimal("1234.56")
    assert parse_decimal("2,36", decimal_comma=True) == Decimal("2.36")
    assert parse_decimal("Rs. 2,300") is None  # ambiguous thousands vs decimals: refuse to guess
    assert parse_price_unit("Rs./Quintal").quantity_unit == "quintal"
    assert parse_price_unit("national currency/ton", default_currency="PLN").currency == "PLN"
    assert parse_price_unit("USD/cwt").quantity_unit == "cwt"
    assert parse_price_unit("USD/furlong") is None
    assert canonical_commodity("SOJA EM GRÃOS") == "soybean"
    assert canonical_commodity("Blé tendre") == "wheat"
    assert canonical_commodity("Maize (white, dry)") == "corn"
    assert canonical_commodity("dragonfruit") is None


@pytest.mark.parametrize("country,crop,region,pack,currency,unit,futures", [
    ("BR", "soja", "Mato Grosso", "br_grains_oilseeds", "BRL", "saca_60kg", "optional_licensed"),
    ("US", "corn", "Iowa", "us_row_crops", "USD", "bushel", "optional_licensed"),
    ("US", "almonds", "California", "us_specialty_crops", "USD", "pound", "none"),
    ("AU", "wheat", "Western Australia", "au_grains", "AUD", "tonne", "optional_licensed"),
    ("IN", "rice", "Punjab", "in_mandi", "INR", "quintal", "none"),
    ("KE", "maize", "Rift Valley", "ke_local_markets", "KES", "bag_90kg", "none"),
    ("FR", "blé", "Rouen", "eu_cereals_oilseeds", "EUR", "tonne", "optional_licensed"),
    ("SN", "onions", "Niayes", "waemu_local_markets", "XOF", "kg", "none"),
    ("BR", "coffee", "Minas Gerais", "br_coffee", "BRL", "saca_60kg", "optional_licensed"),
    ("NZ", "kiwifruit", None, "global_physical", "NZD", "tonne", "none"),
])
def test_onboarding_infers_market_structure_without_provider_identifiers(country, crop, region, pack, currency, unit, futures):
    inferred = infer_onboarding(crop=crop, country_code=country, region=region)
    assert inferred["pack_id"] == pack
    assert inferred["local_currency"] == currency
    assert inferred["quantity_unit"] == unit
    assert inferred["futures_role"] == futures
    assert "slug" not in json.dumps(inferred).lower()


def test_futures_are_never_required_evidence():
    for country, crop in (("US", "almonds"), ("IN", "rice"), ("KE", "maize"), ("SN", "onions")):
        pack = resolve_pack(country, crop)
        assert all(slot.role != "benchmark_price" for slot in pack.evidence)
    assert not any(slot.required for slot in resolve_pack("US", "corn").evidence if slot.role == "benchmark_price")


# ---------------------------------------------------------------------------
# Provider adapters (fixtures)
# ---------------------------------------------------------------------------


def test_eu_agrifood_parses_comma_and_dot_prices_and_skips_empty_products():
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        if "BLTFOUR" in url:
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "no data", {}, None)
        if "cereal" in url:
            return json.dumps([{"memberStateCode": "FR", "beginDate": "21/09/2026", "endDate": "27/09/2026", "price": "€244,36",
                                "unit": "TONNES", "productName": "Milling wheat", "marketName": "Rouen", "stageName": "Delivered to port"}])
        return json.dumps([{"memberStateCode": "FR", "beginDate": "21/09/2026", "endDate": "27/09/2026", "price": "€554.00",
                            "unit": "national currency/ton", "product": "Rapeseed", "marketStage": "FOB", "market": "Moselle"}])

    adapter = EUAgriFoodPricesSeries(fetch_text=fetch)
    points = asyncio.run(adapter.collect([{"commodity": "wheat", "member_state": "FR"}, {"commodity": "rapeseed", "member_state": "FR"}]))
    values = {p.descriptor.commodity: (p.value, p.descriptor.currency, p.descriptor.unit, p.source_status) for p in points}
    assert values["wheat"] == (Decimal("244.36"), "EUR", "tonne", "DELAYED")
    assert values["rapeseed"] == (Decimal("554.00"), "EUR", "tonne", "DELAYED")
    assert any("BLTFOUR" in url for url in calls)


CONAB_FIXTURE = [
    "produto;classificao_produto;id_produto;uf;regiao;ano;mes;data_inicial_final_semana;semana;dsc_nivel_comercializacao;valor_produto_kg\n",
    "SOJA ;EM GRÃOS ;1;MT ;CENTRO-OESTE ;2026;9;21-09-2026 - 25-09-2026 ;4;PREÇO RECEBIDO P/ PR;2,36\n",
    "SOJA ;EM GRÃOS ;1;MT ;CENTRO-OESTE ;2026;9;21-09-2026 - 25-09-2026 ;4;VAREJO;3,90\n",
    "MILHO ;DE PIPOCA ;2;MT ;CENTRO-OESTE ;2026;9;21-09-2026 - 25-09-2026 ;4;PREÇO RECEBIDO P/ PR;1,72\n",
    "MILHO ;EM GRÃOS ;3;PR ;SUL ;2026;9;21-09-2026 - 25-09-2026 ;4;PREÇO RECEBIDO P/ PR;0,98\n",
    "00-18-18 ;NÃO INFORMADO ;4;MT ;CENTRO-OESTE ;2026;9;21-09-2026 - 25-09-2026 ;4;PREÇO PAGO PELO PROD;2,41\n",
    "SOJA ;EM GRÃOS ;1;GO ;CENTRO-OESTE ;2026;9;21-09-2026 - 25-09-2026 ;4;PREÇO RECEBIDO P/ PR;2,30\n",
]


def test_conab_keeps_only_producer_received_prices_for_requested_states():
    adapter = CONABWeeklyPricesSeries(iter_lines=lambda url, timeout: iter(CONAB_FIXTURE))
    points = asyncio.run(adapter.collect([{"commodity": "soybean", "uf": "MT"}, {"commodity": "corn", "uf": "MT"}]))
    assert [(p.descriptor.commodity, p.descriptor.region, p.value) for p in points] == [("soybean", "MT", Decimal("2.36"))]
    point = points[0]
    assert point.descriptor.currency == "BRL" and point.descriptor.unit == "kg"
    assert point.descriptor.price_basis == "producer_received"
    assert point.observed_at.date().isoformat() == "2026-09-25"


def test_conab_refuses_a_changed_publication_header():
    adapter = CONABWeeklyPricesSeries(iter_lines=lambda url, timeout: iter(["produto;uf;valor\n", "SOJA;MT;2,36\n"]))
    with pytest.raises(ValueError, match="header changed"):
        asyncio.run(adapter.collect([{"commodity": "soybean", "uf": "MT"}]))


def test_ptax_and_ecb_emit_delayed_central_bank_reference_rates():
    ptax = BCBPtaxSeries(fetch_text=lambda url, timeout: json.dumps({"value": [
        {"cotacaoCompra": 5.2232, "cotacaoVenda": 5.2238, "dataHoraCotacao": "2026-10-02 13:03:16.123"},
    ]}))
    [point] = asyncio.run(ptax.collect([]))
    assert point.value == Decimal("5.2238") and point.descriptor.unit == "BRL/USD" and point.source_status == "DELAYED"
    assert point.observed_at == datetime(2026, 10, 2, 16, 3, 16, tzinfo=timezone.utc)
    xml = ('<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
           '<Cube><Cube time="2026-10-02"><Cube currency="USD" rate="1.0812"/><Cube currency="BRL" rate="5.6481"/></Cube></Cube></gesmes:Envelope>')
    points = asyncio.run(ECBReferenceRatesSeries(fetch_text=lambda url, timeout: xml).collect([]))
    assert {(p.descriptor.series_key, p.value) for p in points} == {("fx_reference:EUR:USD", Decimal("1.0812")), ("fx_reference:EUR:BRL", Decimal("5.6481"))}


def test_key_required_adapters_are_not_configured_without_credentials(monkeypatch):
    for env in ("USDA_MMN_API_KEY", "USDA_NASS_API_KEY", "DATA_GOV_IN_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    for provider_id in ("usda_mymarketnews", "usda_nass", "india_agmarknet"):
        assert ADAPTERS[provider_id].status() == "NOT_CONFIGURED"
        assert asyncio.run(ADAPTERS[provider_id].collect([{"commodity": "corn", "region": "Iowa", "state": "IOWA"}])) == []
    for provider_id in ("cme_futures", "b3_futures", "euronext_futures", "asx_futures", "ice_futures", "cepea_indicators"):
        catalog = ADAPTERS[provider_id].catalog()
        assert catalog["status"] == "NOT_CONFIGURED" and catalog["licensing"]["display_allowed"] is False
    assert ADAPTERS["kenya_kamis"].status() == "NOT_CONFIGURED"
    assert ADAPTERS["local_market_manual"].status() == "MANUAL"


def test_keyed_adapters_parse_documented_payloads():
    agmarknet = IndiaAgmarknetSeries(api_key="k", fetch_text=lambda url, timeout: json.dumps({"records": [
        {"state": "Punjab", "district": "Ludhiana", "market": "Khanna", "commodity": "Paddy(Dhan)(Common)", "variety": "Common",
         "arrival_date": "02/10/2026", "min_price": "2300", "max_price": "2400", "modal_price": "2369"},
    ]}))
    [point] = asyncio.run(agmarknet.collect([{"commodity": "rice", "state": "Punjab"}]))
    assert (point.value, point.descriptor.unit, point.descriptor.currency, point.descriptor.price_basis) == (Decimal("2369"), "quintal", "INR", "mandi_modal")
    nass = USDANASSQuickStatsSeries(api_key="k", fetch_text=lambda url, timeout: json.dumps({"data": [
        {"Value": "211.0", "year": 2025, "unit_desc": "BU / ACRE", "short_desc": "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE"},
    ]}))
    [stat] = asyncio.run(nass.collect([{"commodity": "corn", "state": "Iowa"}]))
    assert stat.descriptor.observation_type == "reference_statistic" and stat.descriptor.unit == "bushel/acre" and stat.value == Decimal("211.0")
    usda = USDAMyMarketNewsSeries(api_key="k", fetch_text=lambda url, headers, timeout: json.dumps({"results": [
        {"commodity": "Yellow Corn", "price_unit": "$/bu", "avg_price": "4.21", "report_date": "10/01/2026", "location": "Northwest Iowa"},
        {"commodity": "Yellow Corn", "price_unit": "$/bu", "avg_price": "4.19", "report_date": "10/01/2026", "location": "Central Iowa"},
    ]}))
    first = asyncio.run(usda.collect([{"commodity": "corn", "region": "Iowa"}]))
    second = asyncio.run(usda.collect([{"commodity": "corn", "region": "Iowa"}]))
    assert {p.descriptor.series_key for p in first} == {p.descriptor.series_key for p in second}
    assert len({p.descriptor.series_key for p in first}) == 2  # stable identity per location, not per row order


# ---------------------------------------------------------------------------
# Shared data plane
# ---------------------------------------------------------------------------


def test_ingestion_is_idempotent_and_tracks_revisions(db):
    point = series_point("t:a", "100", provider="eu_agrifood", commodity="wheat", country="FR")
    first = seed(db, point)
    second = seed(db, point)
    assert (first.inserted, second.inserted, second.duplicates) == (1, 0, 1)
    revised = SeriesPoint(descriptor=point.descriptor, observed_at=point.observed_at, value=Decimal("101"), retrieved_at=NOW)
    third = seed(db, revised)
    assert third.revised == 1
    stored = db.query(MarketDataPoint).one()
    assert stored.value == Decimal("101") and int(stored.revision) == 1
    assert stored.quality_json["revisions"][0]["previous_value"].startswith("100")
    assert db.query(MarketDataSeries).count() == 1


def test_licence_controls_storage_and_calculation_use(db):
    no_storage = licensing(license_id="x", attribution="", storage_allowed=False)
    seed(db, series_point("t:nostore", "5", provider="eu_agrifood", license_=no_storage))
    assert db.query(MarketDataSeries).filter_by(series_key="t:nostore").count() == 0


def test_freshness_transitions_and_provider_outage_never_fabricate(db):
    seed(db, series_point("t:fresh", "1", provider="eu_agrifood", days_ago=2),
         series_point("t:stale", "1", provider="eu_agrifood", days_ago=20),
         series_point("t:dead", "1", provider="eu_agrifood", days_ago=60))
    states = {}
    for key in ("t:fresh", "t:stale", "t:dead"):
        series = db.query(MarketDataSeries).filter_by(series_key=key).one()
        states[key] = plane.point_state(series, plane.latest_point(db, series.id))[0]
    assert states == {"t:fresh": "DELAYED", "t:stale": "STALE", "t:dead": "UNAVAILABLE"}

    class Broken(EUAgriFoodPricesSeries):
        async def collect(self, selectors):
            raise TimeoutError("upstream timeout")

    result = asyncio.run(plane.ingest(db, "eu_agrifood", [{"commodity": "wheat", "member_state": "FR"}], adapter=Broken()))
    assert result["status"] == "unavailable" and result["error"] == "TimeoutError"
    run = db.query(MarketProviderRun).filter_by(provider="eu_agrifood").order_by(MarketProviderRun.started_at.desc()).first()
    assert run.status == "unavailable"
    assert plane.provider_due(db, Broken(), run.demand_key) is False  # backoff: not hammered every cycle


def test_demand_is_deduplicated_across_tenants(client, db):
    seed_fx(db)
    for suffix in ("tenant-a", "tenant-b"):
        act_as(*identity(db, suffix))
        onboard(client, crop="soja", country_code="BR", region="Mato Grosso", season="2027", expected_production="1000", reporting_currency="USD")
    demand = plane.demand_set(db)
    assert demand["conab_precos"] == [{"commodity": "soybean", "uf": "MT"}]
    assert len(demand["fx_reference"]) == 1 and len(demand["bcb_ptax"]) == 1


def test_fx_resolution_prefers_official_ptax_and_derives_cfa_exactly(db):
    seed_fx(db)
    seed(db, series_point("bcb_ptax:USD:BRL", "5.2238", provider="bcb_ptax", observation_type="fx_rate", unit="BRL/USD",
                          currency="BRL", base="USD", frequency="daily_business", fresh_days=3, last_known_days=7))
    usd_per_brl = plane.resolve_fx(db, "BRL", "USD")
    assert usd_per_brl.method == "bcb_ptax_official" and usd_per_brl.state == "DELAYED"
    assert usd_per_brl.rate == (Decimal(1) / Decimal("5.2238")).quantize(Decimal("0.0000000001"))
    aud_to_usd = plane.resolve_fx(db, "AUD", "USD")
    assert aud_to_usd.method == "ecb_cross_via_eur" and aud_to_usd.rate == (Decimal("1.08") / Decimal("1.62")).quantize(Decimal("0.0000000001"))
    xof_to_eur = plane.resolve_fx(db, "XOF", "EUR")
    assert xof_to_eur.rate == (Decimal(1) / Decimal("655.957")).quantize(Decimal("0.0000000001"))
    assert plane.resolve_fx(db, "KES", "USD").state == "UNAVAILABLE"  # KES is not published by any configured source


def test_stale_fx_is_labelled_and_expired_fx_is_not_used(db):
    seed_fx(db, days_ago=5)
    stale = plane.resolve_fx(db, "AUD", "USD")
    assert stale.state == "STALE" and stale.rate is not None
    db.query(MarketDataPoint).update({MarketDataPoint.observed_at: datetime.utcnow() - timedelta(days=9)})
    db.commit()
    assert plane.resolve_fx(db, "AUD", "USD").state == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Representative global positions (end to end through the API)
# ---------------------------------------------------------------------------


def test_brazil_soy_physical_price_ptax_and_usd_linked_contract(client, db):
    seed_fx(db)
    seed(db,
         series_point("conab_precos:soybean:em graos:MT:producer_received", "2.36", provider="conab_precos", commodity="soybean",
                      country="BR", region="MT", market="MT state average", unit="kg", currency="BRL"),
         series_point("bcb_ptax:USD:BRL", "5.20", provider="bcb_ptax", observation_type="fx_rate", unit="BRL/USD", currency="BRL",
                      base="USD", frequency="daily_business", fresh_days=3, last_known_days=7))
    act_as(*identity(db, "br-soy"))
    created = onboard(client, crop="Soja", country_code="BR", region="Mato Grosso", season="2027", expected_production="10000",
                      production_cost_per_unit="90", reporting_currency="BRL",
                      contracts=[{"buyer": "Trading Co", "quantity": "3000", "price": "27.50", "currency": "USD"}])
    position = created["position"]
    assert created["inferred"]["pack_id"] == "br_grains_oilseeds" and position["quantity_unit"] == "saca_60kg"
    assert position["current_realizable_price"] == "141.60000000"  # 2.36 BRL/kg x 60 kg
    assert created["refresh"]["price"]["outcome"] == "promoted"
    # USD contract converted with the official PTAX rate: 3000 x 27.50 x 5.20
    assert position["locked_revenue"] == "429000.00"
    assert position["exposed_revenue"] == "991200.00"  # 7000 x 141.60
    scenario = client.post("/v1/market-intelligence/scenarios/compare", json={
        "position_id": created["id"], "scenarios": [{"label": "BRL -5%", "fx_pct": "-5"}],
    }).json()["scenarios"][0]
    assert scenario["delta"]["locked_revenue"] == "-21450.00"  # only the USD-linked revenue moves with FX


def test_us_corn_bushels_local_cash_and_basis_scenario(client, db):
    seed(db, series_point("usda_mymarketnews:2850:corn:northwest iowa:bushel", "4.21", provider="usda_mymarketnews", commodity="corn",
                          country="US", region="Iowa", market="Northwest Iowa", unit="bushel", currency="USD", frequency="daily_business",
                          fresh_days=4, last_known_days=14))
    act_as(*identity(db, "us-corn"))
    created = onboard(client, crop="corn", country_code="US", region="Northwest Iowa", season="2026", expected_production="200000",
                      production_cost_per_unit="3.80", storage_per_unit="0.05",
                      contracts=[{"quantity": "50000", "price": "4.35", "currency": "USD"}])
    position = created["position"]
    assert position["quantity_unit"] == "bushel" and position["current_realizable_price"] == "4.21000000"
    basis = client.post("/v1/market-intelligence/scenarios/compare", json={
        "position_id": created["id"], "scenarios": [{"label": "basis -0.15", "basis_per_unit_delta": "-0.15"}],
    }).json()["scenarios"][0]
    assert basis["result"]["current_realizable_price"] == "4.06000000"
    assert basis["delta"]["exposed_revenue"] == "-22500.00"  # 150000 bu x -0.15


def test_california_almonds_need_no_futures_and_keep_manual_price(client, db):
    act_as(*identity(db, "ca-almond"))
    created = onboard(client, crop="almonds", country_code="US", region="California", season="2026", expected_production="2000000",
                      quantity_unit="pound", local_price="2.38", production_cost_per_unit="1.72",
                      contracts=[{"quantity": "600000", "price": "2.31"}])
    assert created["inferred"]["futures_role"] == "none"
    assert all(slot["role"] != "benchmark_price" for slot in created["evidence_plan"])
    assert created["refresh"]["price"]["policy"] == "manual"
    assert created["position"]["current_realizable_price"] == "2.38000000"
    assert created["position"]["projected_margin"] is not None


def test_australian_wheat_in_aud_tonnes_converts_with_ecb_cross(client, db):
    seed_fx(db)
    act_as(*identity(db, "au-wheat"))
    created = onboard(client, crop="wheat", country_code="AU", region="Western Australia", season="2026", expected_production="5000",
                      local_price="355", reporting_currency="USD", production_cost_per_unit="250")
    position = created["position"]
    assert position["quantity_unit"] == "tonne" and created["inferred"]["local_currency"] == "AUD"
    expected = (Decimal("355") * (Decimal("1.08") / Decimal("1.62")).quantize(Decimal("0.0000000001"))).quantize(Decimal("0.00000001"))
    assert Decimal(position["current_realizable_price"]) == expected
    provenance = client.get(f"/v1/market-intelligence/positions/{created['id']}/provenance").json()
    assert provenance["numbers"]["fx_rate_to_reporting"]["method"] == "ecb_cross_via_eur"
    assert provenance["numbers"]["current_realizable_price"]["origin"] == "customer"


def test_india_rice_mandi_quintals_in_inr(client, db):
    seed(db, *[series_point(f"india_agmarknet:punjab:ludhiana:{m}:rice:common", v, provider="india_agmarknet", commodity="rice",
                            country="IN", region="Punjab", market=f"{m}, Ludhiana", unit="quintal", currency="INR",
                            frequency="daily", fresh_days=4, last_known_days=14)
               for m, v in (("khanna", "2369"), ("jagraon", "2350"), ("samrala", "2400"))])
    act_as(*identity(db, "in-rice"))
    created = onboard(client, crop="paddy", country_code="IN", region="Punjab", season="kharif-2026", expected_production="800")
    position = created["position"]
    assert position["quantity_unit"] == "quintal" and position["reporting_currency"] == "INR"
    assert position["current_realizable_price"] == "2369.00000000"  # median of three mandis
    provenance = client.get(f"/v1/market-intelligence/positions/{created['id']}/provenance").json()
    assert provenance["numbers"]["current_realizable_price"]["origin"] == "governed_shared_evidence"
    assert len([s for s in provenance["sources"] if s["observation_type"] == "physical_price"]) == 3


def test_kenya_maize_keeps_customer_fx_when_no_governed_kes_source(client, db):
    seed_fx(db)
    act_as(*identity(db, "ke-maize"))
    created = onboard(client, crop="maize", country_code="KE", region="Rift Valley", season="long-rains-2026", expected_production="400",
                      local_price="4200", reporting_currency="USD", fx_rate_to_reporting="0.00775")
    position_id = created["id"]
    assert created["position"]["quantity_unit"] == "bag_90kg"
    assert created["refresh"]["fx"]["outcome"] == "kept_customer_rate"
    refreshed = client.post(f"/v1/market-intelligence/positions/{position_id}/refresh").json()
    assert refreshed["fx"]["outcome"] == "kept_customer_rate"
    assert db.get(MarketPosition, position_id).fx_rate_to_reporting == Decimal("0.0077500000")


def test_french_wheat_eur_physical_with_exact_market_match(client, db):
    seed(db,
         series_point("eu_agrifood:FR:BLTPAN:rouen:port", "244.36", provider="eu_agrifood", commodity="wheat", country="FR", region="Rouen",
                      market="Rouen", currency="EUR"),
         series_point("eu_agrifood:FR:BLTPAN:la pallice:port", "241.10", provider="eu_agrifood", commodity="wheat", country="FR",
                      region="La Pallice", market="La Pallice", currency="EUR"))
    act_as(*identity(db, "fr-wheat"))
    created = onboard(client, crop="blé tendre", country_code="FR", region="Rouen", season="2026/27", expected_production="1200",
                      production_cost_per_unit="190")
    assert created["position"]["current_realizable_price"] == "244.36000000"
    assert created["refresh"]["price"]["method"] == "exact_market_match"


# ---------------------------------------------------------------------------
# Price policy, materiality and alerts
# ---------------------------------------------------------------------------


def _brazil_position(client, db, suffix, *, price="2.36"):
    seed(db, series_point("conab_precos:soybean:em graos:MT:producer_received", price, provider="conab_precos", commodity="soybean",
                          country="BR", region="MT", unit="kg", currency="BRL"))
    act_as(*identity(db, suffix))
    return onboard(client, crop="soja", country_code="BR", region="Mato Grosso", season="2027", expected_production="10000",
                   production_cost_per_unit="100", reporting_currency="BRL",
                   contracts=[{"quantity": "2000", "price": "140", "currency": "BRL"}])


def _age_snapshots(db, position_id, hours=26):
    db.query(MarketPositionSnapshot).filter_by(position_id=position_id).update(
        {MarketPositionSnapshot.computed_at: datetime.utcnow() - timedelta(hours=hours)})
    db.commit()


def _move_conab(db, value):
    series = db.query(MarketDataSeries).filter_by(series_key="conab_precos:soybean:em graos:MT:producer_received").one()
    db.add(MarketDataPoint(series_id=series.id, observed_at=datetime.utcnow() - timedelta(hours=2), value=Decimal(value), source_status="DELAYED",
                           retrieved_at=datetime.utcnow(), content_hash=f"h{value}", revision=Decimal(0), quality_json={}))
    db.commit()


def test_material_price_drop_alerts_with_exact_driver_attribution_and_dedupe(client, db):
    created = _brazil_position(client, db, "mat-drop")
    position_id = created["id"]
    _age_snapshots(db, position_id)
    _move_conab(db, "2.12")  # -10.2% physical price
    asyncio.run(refresh_module.refresh_position_market_data(db, db.get(MarketPosition, position_id)))
    first = evaluate_position(db, db.get(MarketPosition, position_id))
    db.commit()
    events = db.query(MarketMaterialityEvent).filter_by(position_id=position_id).all()
    assert len(events) == 1 and events[0].kind == "commercial_change" and events[0].level in {"HIGH", "CRITICAL"}
    impact = events[0].impact_json
    assert impact["direction"] == "down" and impact["basis"] == "projected_margin"
    contributions = sum(Decimal(d["contribution"]) for d in impact["drivers"])
    assert contributions == Decimal(impact["change"])
    assert {d["driver"] for d in impact["drivers"]} == {"price"}
    codes = {r["code"] for r in events[0].reasons_json}
    assert {"economic_change", "price_change", "exposure"} <= codes
    # Re-evaluating the same state never duplicates the alert.
    evaluate_position(db, db.get(MarketPosition, position_id))
    db.commit()
    assert db.query(MarketMaterialityEvent).filter_by(position_id=position_id).count() == 1
    assert first["status"] == "evaluated"


def test_small_moves_do_not_alert_and_stale_evidence_suppresses_economic_alerts(client, db):
    created = _brazil_position(client, db, "mat-noise")
    position_id = created["id"]
    _age_snapshots(db, position_id)
    _move_conab(db, "2.35")  # -0.4%: noise
    asyncio.run(refresh_module.refresh_position_market_data(db, db.get(MarketPosition, position_id)))
    evaluate_position(db, db.get(MarketPosition, position_id))
    db.commit()
    assert db.query(MarketMaterialityEvent).filter_by(position_id=position_id).count() == 0

    position = db.get(MarketPosition, position_id)
    position.metadata_json = {**position.metadata_json, "price_state": "STALE"}
    position.current_realizable_price = Decimal("100")
    db.commit()
    _age_snapshots(db, position_id)
    evaluate_position(db, db.get(MarketPosition, position_id))
    db.commit()
    kinds = {(e.kind, e.level) for e in db.query(MarketMaterialityEvent).filter_by(position_id=position_id)}
    assert ("data_quality", "MEDIUM") in kinds
    assert not any(kind == "commercial_change" for kind, _ in kinds)


def test_over_contracting_and_margin_turning_negative_escalate(client, db):
    created = _brazil_position(client, db, "mat-over")
    position_id = created["id"]
    _age_snapshots(db, position_id)
    position = db.get(MarketPosition, position_id)
    position.production_cost_per_unit = Decimal("160")  # margin turns negative
    db.commit()
    evaluate_position(db, position)
    db.commit()
    levels = {e.level for e in db.query(MarketMaterialityEvent).filter_by(position_id=position_id)}
    assert "CRITICAL" in levels


def test_alerts_api_ack_and_cross_tenant_isolation(client, db):
    created = _brazil_position(client, db, "alerts-a")
    position_id = created["id"]
    _age_snapshots(db, position_id)
    _move_conab(db, "1.90")
    asyncio.run(refresh_module.refresh_position_market_data(db, db.get(MarketPosition, position_id)))
    evaluate_position(db, db.get(MarketPosition, position_id))
    db.commit()
    alerts = client.get("/v1/market-intelligence/alerts").json()["alerts"]
    assert len(alerts) == 1
    home = client.get("/v1/market-intelligence/home").json()
    assert home["status"] == "attention" and home["material_change_count"] == 1
    alert_id = alerts[0]["id"]

    act_as(*identity(db, "alerts-b"))
    assert client.get("/v1/market-intelligence/alerts").json()["alerts"] == []
    assert client.post(f"/v1/market-intelligence/alerts/{alert_id}/acknowledge").status_code == 404
    for path in (f"/positions/{position_id}/provenance", f"/positions/{position_id}/risk", f"/changes?position_id={position_id}"):
        assert client.get(f"/v1/market-intelligence{path}").status_code == 404, path
    assert client.post(f"/v1/market-intelligence/positions/{position_id}/yield-estimates",
                       json={"yield_per_area": "60", "quantity_unit": "saca"}).status_code == 404
    assert client.post("/v1/market-intelligence/scenarios/compare",
                       json={"position_id": position_id, "scenarios": [{"price_pct": "-5"}]}).status_code == 404


def test_viewer_cannot_acknowledge_or_onboard(client, db):
    created = _brazil_position(client, db, "viewer-owner")
    user, org, _ = identity(db, "viewer-only")
    viewer = OrganizationMembership(organization_id=db.get(MarketPosition, created["id"]).organization_id, user_id=user.id, role="viewer", status="active")
    db.add(viewer)
    db.commit()
    act_as(user, db.get(Organization, viewer.organization_id), viewer)
    assert client.post("/v1/market-intelligence/onboarding", json={"crop": "corn", "country_code": "US", "season": "2026",
                                                                   "expected_production": "1"}).status_code == 403
    assert client.get("/v1/market-intelligence/home").status_code == 200


def test_customer_observations_are_always_manual(client, db):
    created = _brazil_position(client, db, "manual-only")
    response = client.post("/v1/market-intelligence/observations", json={
        "position_id": created["id"], "evidence_id": "spoof-delayed", "observation_type": "physical_price",
        "provider": "usda_mymarketnews", "source_name": "Spoofed government report", "source_status": "DELAYED",
        "value": "9.99", "observed_at": NOW.isoformat(),
    })
    assert response.status_code == 201 and response.json()["source_status"] == "MANUAL"


def test_manual_price_is_never_overwritten_by_automation(client, db):
    created = _brazil_position(client, db, "policy")
    position_id = created["id"]
    patched = client.patch(f"/v1/market-intelligence/positions/{position_id}", json={"current_realizable_price": "150"})
    assert patched.status_code == 200
    _move_conab(db, "2.50")
    result = client.post(f"/v1/market-intelligence/positions/{position_id}/refresh").json()
    assert result["price"]["outcome"] == "kept_customer_price"
    assert db.get(MarketPosition, position_id).current_realizable_price == Decimal("150")


# ---------------------------------------------------------------------------
# Field-to-commercial linkage
# ---------------------------------------------------------------------------


def test_yield_estimate_on_linked_fields_recalculates_production_and_exposure(client, db):
    created = _brazil_position(client, db, "fields")
    position_id = created["id"]
    org_id = db.get(MarketPosition, position_id).organization_id
    real = ManagedEntity(organization_id=org_id, entity_type="platform_field", display_name="Talhão 1", status="active",
                         metadata_json={"crop": "soja", "area_hectares": 120})
    demo = ManagedEntity(organization_id=org_id, entity_type="platform_field", display_name="Demo", status="active",
                         metadata_json={"crop": "soja", "area_hectares": 999, "data_class": "simulated_or_evaluation"})
    db.add_all([real, demo])
    db.commit()
    linked = client.put(f"/v1/market-intelligence/positions/{position_id}/fields", json={"field_ids": [real.id, demo.id]}).json()
    assert linked["linked_area_hectares"] == "120"
    assert {f["counted"] for f in linked["fields"]} == {True, False}
    _age_snapshots(db, position_id)
    estimate = client.post(f"/v1/market-intelligence/positions/{position_id}/yield-estimates",
                           json={"yield_per_area": "55", "quantity_unit": "saca", "source": "field_intelligence"}).json()
    assert estimate["applied_to_expected_production"] is True
    assert Decimal(estimate["expected_production"]) == Decimal("6600")  # 120 ha x 55 sacas/ha
    assert estimate["materiality"]["status"] == "evaluated"
    drivers = db.query(MarketMaterialityEvent).filter_by(position_id=position_id, kind="commercial_change").one().impact_json["drivers"]
    assert {d["driver"] for d in drivers} == {"production"}

    other = identity(db, "fields-foreign")
    foreign = ManagedEntity(organization_id=other[1].id, entity_type="platform_field", display_name="Foreign", status="active",
                            metadata_json={"area_hectares": 10})
    db.add(foreign)
    db.commit()
    assert client.put(f"/v1/market-intelligence/positions/{position_id}/fields", json={"field_ids": [foreign.id]}).status_code == 404


# ---------------------------------------------------------------------------
# Scenarios, risk, journal
# ---------------------------------------------------------------------------


def _scenario_position():
    return SimpleNamespace(
        id="p", position_key="k", name="n", commodity="soybean", season="2027", country_code="BR", region="MT", market_structure="hybrid",
        reporting_currency="BRL", quantity_unit="saca_60kg", expected_production=Decimal("10000"), inventory_quantity=Decimal("1000"),
        production_cost_per_unit=Decimal("100"), current_realizable_price=Decimal("140"), price_currency="BRL", fx_rate_to_reporting=None,
        freight_per_unit=Decimal("5"), storage_per_unit=Decimal("2"), metadata_json={"inventory_cost_per_unit": "95"},
    )


def test_scenario_v2_levers_and_exact_zero_change():
    position = _scenario_position()
    contracts = [{"status": "active", "quantity": "3000", "quantity_unit": "saca_60kg", "price": "138", "currency": "BRL"}]
    zero = scenario_position(position, contracts, {key: 0 for key in (
        "price_pct", "basis_per_unit_delta", "yield_pct", "inventory_pct", "fx_pct", "production_cost_pct", "freight_per_unit_delta",
        "storage_per_unit_delta", "carry_months", "carry_cost_per_unit_month", "contracted_volume_pct", "sell_pct_now")})
    assert zero["zero_change_invariant"] is True and zero["result"] == zero["baseline"] and zero["not_a_forecast"] is True
    carry = scenario_position(position, contracts, {"carry_months": "3", "carry_cost_per_unit_month": "1.5"})
    assert carry["delta"]["projected_cost"] == "49500.00"  # 11000 x 4.5
    lock = scenario_position(position, contracts, {"sell_pct_now": "50", "sell_price_per_unit": "150"})
    assert lock["result"]["scenario_volume_locked_now"] == "4000.00000000"
    assert lock["delta"]["projected_revenue"] == "40000.00"  # 4000 x (150 - 140)
    renegotiate = scenario_position(position, contracts, {"contracted_volume_pct": "-50"})
    assert renegotiate["delta"]["locked_revenue"] == "-207000.00"
    with pytest.raises(Exception):
        scenario_position(position, contracts, {"basis_per_unit_delta": "-200"})


def test_compare_endpoint_models_10_25_40_percent_commitments(client, db):
    created = _brazil_position(client, db, "compare")
    body = client.post("/v1/market-intelligence/scenarios/compare", json={"position_id": created["id"], "scenarios": [
        {"label": "10%", "sell_pct_now": "10"}, {"label": "25%", "sell_pct_now": "25"}, {"label": "40%", "sell_pct_now": "40"}]}).json()
    exposed = [Decimal(item["result"]["exposed_percent"]) for item in body["scenarios"]]
    assert exposed == sorted(exposed, reverse=True) and body["not_a_forecast"] is True


def test_risk_requires_history_and_reports_methodology():
    assert historical_move_statistics([Decimal("100")] * 10, horizon_periods=4, frequency="weekly")["status"] == "insufficient_history"
    prices = [Decimal(str(100 + 5 * ((i * 7) % 11) - 20)) for i in range(60)]
    stats = historical_move_statistics(prices, horizon_periods=4, frequency="weekly")
    assert stats["status"] == "ok" and stats["observations"] == 60
    moves = stats["horizon_moves_percent"]
    assert Decimal(moves["p5"]) <= Decimal(moves["p50"]) <= Decimal(moves["p95"])
    assert stats["band_calibration"]["tested_windows"] > 0


def test_risk_endpoint_stress_uses_governed_series(client, db):
    seed(db, *[series_point("conab_precos:soybean:em graos:MT:producer_received", str(2.0 + 0.01 * ((i * 7) % 13)), provider="conab_precos",
                            commodity="soybean", country="BR", region="MT", unit="kg", currency="BRL", days_ago=7 * i)
               for i in range(40)])
    act_as(*identity(db, "risk"))
    created = onboard(client, crop="soja", country_code="BR", region="MT", season="2027", expected_production="10000",
                      production_cost_per_unit="100", reporting_currency="BRL")
    risk = client.get(f"/v1/market-intelligence/positions/{created['id']}/risk").json()
    assert risk["status"] == "ok" and risk["not_a_forecast"] is True and risk["methodology_version"]
    assert set(risk["stress"]) == {"p5", "p95"}


def test_decision_journal_v2_freezes_evidence_and_compares_outcome(client, db):
    created = _brazil_position(client, db, "journal")
    entry = client.post("/v1/market-intelligence/decision-journal", json={
        "position_id": created["id"], "decision": "Commit 20% more to the cooperative", "action_taken": "Signed contract C-77",
    })
    assert entry.status_code == 201
    entries = client.get("/v1/market-intelligence/decision-journal").json()["entries"]
    snapshot = entries[0]["evidence_snapshot"]
    assert snapshot["position"]["projected_margin"] is not None and snapshot["calculation_version"]
    modelled = Decimal(snapshot["position"]["projected_margin"])
    outcome = client.patch(f"/v1/market-intelligence/decision-journal/{entry.json()['id']}",
                           json={"outcome": {"actual_margin": str(modelled - 1000)}}).json()
    assert outcome["outcome"]["comparison"]["difference"] == "-1000.00"


# ---------------------------------------------------------------------------
# Ask AGRO-AI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("question,expected", [
    ("What happens if soybean prices fall another 8%?", [{"price_pct": "-8"}]),
    ("E se o preço cair 8%?", [{"price_pct": "-8"}]),
    ("Et si le prix baisse de 8 % ?", [{"price_pct": "-8"}]),
    ("¿Qué pasa si el rendimiento cae 7%?", [{"yield_pct": "-7"}]),
    ("What if expected yield drops 7%?", [{"yield_pct": "-7"}]),
    ("Show me the difference between selling another 10%, 25%, and 40%.", [{"sell_pct_now": "10"}, {"sell_pct_now": "25"}, {"sell_pct_now": "40"}]),
    ("What changed since yesterday?", []),
])
def test_ask_parses_what_if_questions_deterministically(question, expected):
    intents = parse_scenario_intents(question, {"reporting_currency": "USD", "price_currency": "BRL"})
    assert [{k: v for k, v in item.items() if k != "label"} for item in intents] == expected


def test_currency_strength_maps_to_quote_convention():
    usd_reporting = parse_scenario_intents("What happens if BRL strengthens 5%?", {"reporting_currency": "USD", "price_currency": "BRL"})
    assert usd_reporting[0]["fx_pct"] == "5"
    brl_reporting = parse_scenario_intents("What happens if BRL strengthens 5%?", {"reporting_currency": "BRL", "price_currency": "USD"})
    assert brl_reporting[0]["fx_pct"] == "-5"
    assert requested_language("Explain this to me in Portuguese") == "pt"


def test_offline_ask_answers_what_if_with_deterministic_numbers(client, db, monkeypatch):
    monkeypatch.setattr("app.services.market_intelligence_ai.ModelRouter.mode", lambda _self: "offline")
    created = _brazil_position(client, db, "ask")
    body = client.post("/v1/market-intelligence/ask", json={
        "position_id": created["id"], "question": "What happens if prices fall 8%? Explain in Portuguese",
    }).json()
    scenario = body["scenarios"][0]
    assert scenario["status"] == "ok" and scenario["assumptions"]["price_pct"] == "-8"
    intelligence = body["intelligence"]
    assert intelligence["response_language"] == "pt"
    assert scenario["projected_margin"] in intelligence["summary"]
    assert body["evidence"]["scenario_1.projected_margin"] == scenario["projected_margin"]


def test_portfolio_ask_focuses_on_the_position_needing_attention(client, db, monkeypatch):
    monkeypatch.setattr("app.services.market_intelligence_ai.ModelRouter.mode", lambda _self: "offline")
    _brazil_position(client, db, "ask-portfolio")
    body = client.post("/v1/market-intelligence/ask", json={"question": "Which position deserves the most attention?"}).json()
    assert body["scope"] == "portfolio_focus" and body["position_id"]


def test_model_answer_hides_serving_vendor(monkeypatch):
    from app.services import market_intelligence_ai as ai

    class Router:
        def mode(self):
            return "openai_compatible"

        async def run(self, **kwargs):
            payload = {"summary": "Exposure is material.", "insights": [], "confidence": "medium", "limitations": [], "actions": []}
            return SimpleNamespace(status="ok", content=json.dumps(payload), provider="vendor-x", model="vendor-model-9", error=None), \
                SimpleNamespace(model="vendor-model-9", profile="fast")

    monkeypatch.setattr(ai, "ModelRouter", Router)
    monkeypatch.setattr(ai, "assess_market_position", lambda *a, **k: {})
    monkeypatch.setattr(ai, "advisory_context", lambda *a, **k: {})
    result = asyncio.run(ai.generate_market_brief({"exposed_percent": "10"}, {}, question="q"))
    assert result["model_trace"] == {"provider": "agroai", "model": "agroai-intelligence-1", "grounded": True}
    assert "vendor" not in json.dumps(result)


# ---------------------------------------------------------------------------
# Scheduled cycle
# ---------------------------------------------------------------------------


def test_scheduled_cycle_ingests_shared_evidence_once_and_alerts(client, db, monkeypatch):
    from app.services import market_intelligence_cycle as cycle

    seed_fx(db)
    created = _brazil_position(client, db, "cycle")
    position_id = created["id"]
    _age_snapshots(db, position_id)
    calls = []

    class FixtureConab(CONABWeeklyPricesSeries):
        async def collect(self, selectors):
            calls.append(selectors)
            line = "SOJA ;EM GRÃOS ;1;MT ;CENTRO-OESTE ;2026;10;{} - {} ;1;PREÇO RECEBIDO P/ PR;1,95\n"
            day = datetime.utcnow().strftime("%d-%m-%Y")
            return self._parse(iter([CONAB_FIXTURE[0], line.format(day, day)]), {("soybean", "MT")}, datetime.now(timezone.utc))

    monkeypatch.setitem(ADAPTERS, "conab_precos", FixtureConab())
    for provider_id in ("fx_reference", "bcb_ptax"):
        monkeypatch.setattr(ADAPTERS[provider_id], "configured", lambda: False)

    class SessionFactory:
        def __call__(self):
            return db

    monkeypatch.setattr(cycle, "SessionLocal", SessionFactory())
    monkeypatch.setattr(db, "close", lambda: None)
    result = asyncio.run(cycle.run_cycle(time_budget_seconds=120))
    assert result["status"] == "ok", result
    assert result["providers"]["conab_precos"]["status"] == "ok"
    assert len(calls) == 1 and calls[0] == [{"commodity": "soybean", "uf": "MT"}]
    events = db.query(MarketMaterialityEvent).filter_by(position_id=position_id).all()
    assert events and events[0].level in {"HIGH", "CRITICAL"}
    assert result["organization_results"][db.get(MarketPosition, position_id).organization_id]["notifications"]["status"] in {"disabled", "nothing_urgent"}
    # A second cycle inside the refresh interval does not re-fetch CONAB.
    again = asyncio.run(cycle.run_cycle(time_budget_seconds=120))
    assert again["providers"]["conab_precos"]["status"] == "fresh_enough" and len(calls) == 1


def test_mixed_clause_what_if_assigns_each_percentage_to_its_own_lever():
    intents = parse_scenario_intents("What happens if prices fall 8% and BRL strengthens 5%?", {"reporting_currency": "USD", "price_currency": "BRL"})
    assert [{k: v for k, v in item.items() if k != "label"} for item in intents] == [{"price_pct": "-8"}, {"fx_pct": "5"}]
    falls = parse_scenario_intents("What if prices fall 5% or 10%?", {"reporting_currency": "USD"})
    assert [item["price_pct"] for item in falls] == ["-5", "-10"]


def test_local_currency_costs_convert_with_the_governed_price_fx(client, db):
    seed_fx(db)
    seed(db,
         series_point("conab_precos:soybean:em graos:MT:producer_received", "2.36", provider="conab_precos", commodity="soybean",
                      country="BR", region="MT", unit="kg", currency="BRL"),
         series_point("bcb_ptax:USD:BRL", "5.00", provider="bcb_ptax", observation_type="fx_rate", unit="BRL/USD", currency="BRL",
                      base="USD", frequency="daily_business", fresh_days=3, last_known_days=7))
    act_as(*identity(db, "cost-ccy"))
    created = onboard(client, crop="soja", country_code="BR", region="Mato Grosso", season="2027", expected_production="1000",
                      production_cost_per_unit="100", reporting_currency="USD")
    position = created["position"]
    assert position["cost_currency"] == "BRL"
    assert position["current_realizable_price"] == "28.32000000"  # 141.60 BRL / 5.00
    assert position["break_even_price"] == "20.00000000"  # 100 BRL / 5.00
    assert position["projected_margin"] == "8320.00"  # 1000 x (28.32 - 20.00)
    stale_cost = compute_position(SimpleNamespace(**{**_scenario_position().__dict__, "reporting_currency": "USD", "price_currency": "BRL",
                                                    "fx_rate_to_reporting": None, "metadata_json": {"cost_currency": "BRL", "inventory_cost_per_unit": "95"}}), [])
    assert "cost_fx" in stale_cost.payload["missing_inputs"] and stale_cost.payload["projected_margin"] is None


def test_deterministic_scenario_labels_follow_the_answer_language():
    from app.services.market_intelligence_ask import scenario_label

    assert scenario_label({"price_pct": "-8"}, "pt") == "preço -8%"
    assert scenario_label({"fx_pct": "5"}, "fr") == "change +5%"
    assert scenario_label({"sell_pct_now": "25"}, "es") == "comprometer más volumen 25%"


def test_display_restricted_licence_redacts_price_but_keeps_derived_values(client, db, monkeypatch):
    monkeypatch.setattr("app.services.market_intelligence_ai.ModelRouter.mode", lambda _self: "offline")
    restricted = licensing(license_id="licensed-feed", attribution="Vendor", display_allowed=False)
    seed(db, series_point("licensed:corn:iowa", "4.40", provider="usda_mymarketnews", commodity="corn", country="US", region="Iowa",
                          market="Iowa", unit="bushel", currency="USD", frequency="daily_business", fresh_days=4, last_known_days=14,
                          license_=restricted))
    act_as(*identity(db, "licence"))
    created = onboard(client, crop="corn", country_code="US", region="Iowa", season="2026", expected_production="1000",
                      production_cost_per_unit="3")
    position_id = created["id"]
    assert created["refresh"]["price"]["outcome"] == "promoted"
    for body in (client.get(f"/v1/market-intelligence/positions/{position_id}").json(),
                 next(p for p in client.get("/v1/market-intelligence/home").json()["positions"] if p["position_id"] == position_id)):
        assert body["current_realizable_price"] is None and body["redacted_fields"] == ["current_realizable_price"]
        assert body["projected_margin"] == "1400.00"  # derived values remain: 1000 x (4.40 - 3.00)
    provenance = client.get(f"/v1/market-intelligence/positions/{position_id}/provenance").json()
    assert provenance["numbers"]["current_realizable_price"]["value"] is None
    assert all(s["value"] is None and s["redacted"] for s in provenance["sources"] if s["provider"] == "usda_mymarketnews")
    ask = client.post("/v1/market-intelligence/ask", json={"position_id": position_id, "question": "What is my price?"}).json()
    assert "4.40" not in json.dumps(ask)


def test_display_restricted_price_never_leaks_through_scenarios_or_changes(client, db):
    restricted = licensing(license_id="licensed-feed", attribution="Vendor", display_allowed=False)
    seed(db, series_point("licensed:corn:iowa2", "4.40", provider="usda_mymarketnews", commodity="corn", country="US", region="Iowa",
                          market="Iowa", unit="bushel", currency="USD", frequency="daily_business", fresh_days=4, last_known_days=14,
                          license_=restricted))
    act_as(*identity(db, "licence-2"))
    position_id = onboard(client, crop="corn", country_code="US", region="Iowa", season="2026", expected_production="1000",
                          production_cost_per_unit="3")["id"]
    compare = client.post("/v1/market-intelligence/scenarios/compare", json={"position_id": position_id, "scenarios": [{"price_pct": "-5"}]}).json()
    saved = client.post("/v1/market-intelligence/scenarios", json={"position_id": position_id, "price_pct": "-5"}).json()
    for body in (compare, saved):
        assert "4.40" not in json.dumps(body) and "4.18" not in json.dumps(body)
    assert compare["scenarios"][0]["result"]["projected_margin"] == "1180.00"  # derived value still available
