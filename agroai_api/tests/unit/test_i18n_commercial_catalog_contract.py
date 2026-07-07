import pytest

from app.api.v1.i18n import canonical_source_catalog, requested_source_catalog


def test_commercial_boundary_source_is_canonical_and_accepts_exact_subset():
    canonical = canonical_source_catalog()
    subset = {
        "commercialBoundary.title.upgrade": "Upgrade to continue",
        "commercialBoundary.body.unavailable": "This capability is not included in the organization’s current commercial state.",
        "commercialBoundary.upgradeTo": "Upgrade to {plan}",
    }
    assert all(canonical[key] == value for key, value in subset.items())
    assert requested_source_catalog(subset) == subset


def test_commercial_boundary_subset_value_drift_is_rejected():
    with pytest.raises(ValueError, match="ui_source_catalog_mismatch"):
        requested_source_catalog({"commercialBoundary.title.upgrade": "Changed outside canonical source"})


def test_commercial_boundary_placeholder_contract_is_canonical():
    canonical = canonical_source_catalog()
    assert canonical["commercialBoundary.upgradeTo"] == "Upgrade to {plan}"
    assert canonical["commercialBoundary.reasonFeatureMetric"].count("{feature}") == 1
    assert canonical["commercialBoundary.reasonFeatureMetric"].count("{metric}") == 1
