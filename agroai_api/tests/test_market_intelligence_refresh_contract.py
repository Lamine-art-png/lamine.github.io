from datetime import datetime, timezone
from decimal import Decimal

from app.services.market_data_providers import ProviderObservation
from app.services.market_intelligence_refresh import (
    _canonical_quantity_unit,
    _quantity_unit_from_price_unit,
    _scoped_evidence_id,
    _select_unambiguous_latest_price,
)


def test_market_price_units_reconcile_only_when_unambiguous():
    assert _quantity_unit_from_price_unit("USD/bu") == "bushel"
    assert _quantity_unit_from_price_unit("$/lb") == "pound"
    assert _quantity_unit_from_price_unit("USD/kg") == "kg"
    assert _quantity_unit_from_price_unit("USD/t") == "tonne"
    assert _quantity_unit_from_price_unit("USD/cwt") is None
    assert _quantity_unit_from_price_unit(None) is None


def test_provider_evidence_is_position_scoped_without_losing_upstream_identity():
    upstream = "ecb-fx-USDEUR-2026-09-17"
    first = _scoped_evidence_id("position-a", upstream)
    second = _scoped_evidence_id("position-b", upstream)
    assert first != second
    assert first.endswith(upstream)
    assert second.endswith(upstream)


def test_position_quantity_unit_aliases_reconcile_to_provider_units():
    assert _canonical_quantity_unit("bu") == "bushel"
    assert _canonical_quantity_unit("bushels") == "bushel"
    assert _canonical_quantity_unit("lbs") == "pound"
    assert _canonical_quantity_unit("kilograms") == "kg"
    assert _canonical_quantity_unit("metric_tonne") == "tonne"
    assert _canonical_quantity_unit("unsupported") is None


def _price_observation(evidence_id: str, value: str, hour: int = 12) -> ProviderObservation:
    observed = datetime(2026, 9, 17, hour, 0, tzinfo=timezone.utc)
    return ProviderObservation(
        evidence_id=evidence_id,
        observation_type="cash_price",
        provider="usda_mymarketnews",
        source_name="USDA test",
        source_status="DELAYED",
        value=Decimal(value),
        unit="USD/bu",
        currency="USD",
        observed_at=observed,
        retrieved_at=observed,
        metadata={"upstream_request_verified": True},
    )


def test_latest_provider_price_must_be_unambiguous_before_promotion():
    one, error = _select_unambiguous_latest_price([_price_observation("a", "4.62")])
    assert error is None
    assert one is not None and one.value == Decimal("4.62")

    ambiguous, error = _select_unambiguous_latest_price([
        _price_observation("a", "4.62", 9),
        _price_observation("b", "4.78", 16),
    ])
    assert ambiguous is None
    assert error == "ambiguous_latest_market_observations"

    duplicate_value, error = _select_unambiguous_latest_price([
        _price_observation("a", "4.62", 9),
        _price_observation("b", "4.62", 16),
    ])
    assert error is None
    assert duplicate_value is not None and duplicate_value.value == Decimal("4.62")
