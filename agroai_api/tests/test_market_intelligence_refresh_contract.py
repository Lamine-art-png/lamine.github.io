from app.services.market_intelligence_refresh import (
    _canonical_quantity_unit,
    _quantity_unit_from_price_unit,
    _scoped_evidence_id,
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
