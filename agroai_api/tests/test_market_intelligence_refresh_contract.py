from app.services.market_intelligence_refresh import _quantity_unit_from_price_unit, _scoped_evidence_id


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
