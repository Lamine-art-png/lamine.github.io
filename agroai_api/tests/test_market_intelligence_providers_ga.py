import asyncio
from decimal import Decimal

from app.services.market_data_providers import (
    ECBReferenceFXProvider,
    MarketDataRequest,
    USDAMyMarketNewsProvider,
)


def test_ecb_reference_fx_uses_reporting_per_source_convention():
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <Envelope xmlns='http://www.gesmes.org/xml/2002-08-01'
      xmlns:gesmes='http://www.gesmes.org/xml/2002-08-01'>
      <Cube xmlns='http://www.ecb.int/vocabulary/2002-08-01/eurofxref'>
        <Cube time='2026-09-16'>
          <Cube currency='USD' rate='1.2000'/>
          <Cube currency='BRL' rate='6.6000'/>
        </Cube>
      </Cube>
    </Envelope>"""

    def fake_fetch(_url, **_kwargs):
        return xml

    provider = ECBReferenceFXProvider(fetch_text=fake_fetch)
    rows = asyncio.run(provider.observations(MarketDataRequest(
        commodity="soybeans",
        country_code="BR",
        source_currency="USD",
        reporting_currency="BRL",
    )))

    assert len(rows) == 1
    row = rows[0]
    assert row.source_status == "DELAYED"
    assert row.value == Decimal("5.5000000000")
    assert row.unit == "BRL/USD"
    assert row.metadata["quote_convention"] == "reporting_currency_per_source_currency"
    assert row.metadata["upstream_request_verified"] is True
    assert row.licensing["display_allowed"] is True


def test_ecb_reference_fx_same_currency_needs_no_observation():
    provider = ECBReferenceFXProvider(fetch_text=lambda *_args, **_kwargs: "should-not-be-used")
    rows = asyncio.run(provider.observations(MarketDataRequest(
        commodity="corn",
        country_code="US",
        source_currency="USD",
        reporting_currency="USD",
    )))
    assert rows == []


def test_usda_mymarketnews_adapter_emits_governed_delayed_cash_observation():
    payload = {
        "results": [
            {
                "report_begin_date": "2026-09-15",
                "commodity": "Corn",
                "weighted_average": "4.62",
                "price_unit": "USD/bu",
            },
            {
                "report_begin_date": "2026-09-15",
                "commodity": "Soybeans",
                "weighted_average": "10.11",
                "price_unit": "USD/bu",
            },
        ]
    }
    calls = []

    def fake_fetch(url, **kwargs):
        calls.append((url, kwargs))
        return payload

    provider = USDAMyMarketNewsProvider("test-key", fetch_json=fake_fetch)
    rows = asyncio.run(provider.observations(MarketDataRequest(
        commodity="corn",
        country_code="US",
        region="Iowa",
        reporting_currency="USD",
    )))

    assert len(rows) == 1
    row = rows[0]
    assert row.provider == "usda_mymarketnews"
    assert row.source_status == "DELAYED"
    assert row.value == Decimal("4.62")
    assert row.currency == "USD"
    assert row.unit == "USD/bu"
    assert row.quality["provider_quality"] == "high"
    assert row.metadata["upstream_request_verified"] is True
    assert row.licensing["attribution_required"] is True
    assert "/2850?allSections=true" in calls[0][0]
    assert calls[0][1]["headers"]["Authorization"].startswith("Basic ")


def test_usda_adapter_refuses_to_invent_coverage_outside_supported_request():
    provider = USDAMyMarketNewsProvider("test-key", fetch_json=lambda *_args, **_kwargs: {"results": []})
    assert asyncio.run(provider.observations(MarketDataRequest(
        commodity="corn",
        country_code="BR",
        region="Mato Grosso",
    ))) == []
    assert asyncio.run(provider.observations(MarketDataRequest(
        commodity="almonds",
        country_code="US",
        region="California",
        metadata={},
    ))) == []
