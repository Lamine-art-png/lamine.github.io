"""Crop Intelligence routes: authentication, tenant isolation, and contracts."""
from __future__ import annotations

from datetime import date, timedelta

from tests.unit.test_field_intelligence import _auth, _complete, _initiate, _process

BASE = "/v1/field-intelligence"


def _days(start: date, count: int, tmax: float = 30.0, tmin: float = 10.0) -> list[dict]:
    return [{"date": (start + timedelta(days=i)).isoformat(), "tmax_c": tmax, "tmin_c": tmin} for i in range(count)]


def test_routes_require_authentication(client):
    assert client.get(f"{BASE}/crop-profiles").status_code == 401
    assert client.post(f"{BASE}/crop-intelligence/harvest-window", json={}).status_code == 401
    assert client.post(f"{BASE}/crop-intelligence/production-estimate", json={}).status_code == 401
    assert client.post(f"{BASE}/crop-intelligence/maturity-stages", json={}).status_code == 401
    assert client.get(f"{BASE}/fields/f1/crop-condition").status_code == 401


def test_crop_profiles_are_unvalidated(client, db):
    _, _, headers = _auth(db)
    profiles = client.get(f"{BASE}/crop-profiles", headers=headers).json()["profiles"]
    assert {profile["crop_id"] for profile in profiles} >= {"corn", "almond", "wine_grape", "coffee", "tomato"}
    assert all(profile["validation_status"] == "unvalidated" for profile in profiles)


def test_harvest_window_uses_profile_method_and_refuses_without_target(client, db):
    _, _, headers = _auth(db)
    body = {
        "crop": "milho", "biofix": "2026-04-01", "biofix_type": "planting", "as_of": "2026-04-30",
        "target": {"low_gdd": 1000, "high_gdd": 1200, "source": "Hybrid sheet (test)", "source_type": "supplier_published"},
        "observed": _days(date(2026, 4, 1), 30),
        "analog_years": {str(year): _days(date(year, 1, 1), 365) for year in range(2019, 2024)},
        "weather_source": "test station", "analog_weather_source": "test station history",
    }
    result = client.post(f"{BASE}/crop-intelligence/harvest-window", json=body, headers=headers).json()
    assert result["crop_id"] == "corn"
    assert result["degree_day_method"]["method"] == "modified_average_86_50"
    assert result["status"] == "projected"
    assert result["window"]["earliest"] == "2026-07-09" and result["window"]["latest"] == "2026-07-29"

    no_target = client.post(f"{BASE}/crop-intelligence/harvest-window", json={**body, "target": None}, headers=headers).json()
    assert no_target["status"] == "insufficient_evidence"
    assert "maturity_target_required_from_supplier_grower_or_calibration" in no_target["reasons"]

    no_method = client.post(f"{BASE}/crop-intelligence/harvest-window", json={**body, "crop": "almond"}, headers=headers).json()
    assert no_method["reasons"] == ["degree_day_method_and_base_temperature_required"]

    too_many = client.post(f"{BASE}/crop-intelligence/harvest-window",
                           json={**body, "analog_years": {str(year): [] for year in range(1990, 2025)}}, headers=headers)
    assert too_many.status_code == 422


def test_production_estimate_returns_review_only_proposal(client, db):
    _, _, headers = _auth(db)
    body = {
        "unit": "vine", "object_label": "cluster", "design": "systematic_random_start", "population_units": 100,
        "sample_counts": [10, 12, 8, 11, 9], "count_source": "manual_count",
        "detection_rate": {"value": 0.8, "standard_error": 0.04}, "unit_weight_kg": {"value": 0.15, "standard_error": 0.0075},
        "area_hectares": "0.5", "include_market_proposal": True,
    }
    result = client.post(f"{BASE}/crop-intelligence/production-estimate", json=body, headers=headers).json()
    assert result["status"] == "estimated"
    assert result["expected_production_kg"]["value"] == 187.5
    assert result["market_yield_proposal"]["apply_to_production"] is False
    assert result["estimate_id"].startswith("crop-est-")

    convenience = client.post(f"{BASE}/crop-intelligence/production-estimate",
                              json={**body, "design": "walked_the_headland"}, headers=headers).json()
    assert convenience["status"] == "not_estimable"
    assert convenience["market_yield_proposal"] is None


def test_detections_route_is_tenant_scoped(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, client_capture_id="cap-det-route", idempotency_key="idem-det-route").json()["capture"]
    observation = _complete(client, headers, cap["id"]).json()["observation"]
    _process(db)
    own = client.get(f"{BASE}/observations/{observation['id']}/detections", headers=headers).json()
    assert own["detection_status"] == "not_run" and own["detections"] is None

    _, _, other_headers = _auth(db, email="other@example.com", org_id="org-other", workspace_id="ws-other")
    assert client.get(f"{BASE}/observations/{observation['id']}/detections", headers=other_headers).status_code == 404


def test_field_crop_condition_summarizes_and_isolates_tenants(client, db):
    _, _, headers = _auth(db)
    for index in range(2):
        cap = _initiate(client, headers, client_capture_id=f"cap-field-{index}", idempotency_key=f"idem-field-{index}",
                        field_id="field-north").json()["capture"]
        _complete(client, headers, cap["id"])
    _process(db)
    summary = client.get(f"{BASE}/fields/field-north/crop-condition", headers=headers).json()
    assert summary["summary_status"] == "ok"
    assert summary["observations_considered"] == 2
    assert summary["latest"]["freshness"] in {"fresh", "unknown"}

    _, _, other_headers = _auth(db, email="other2@example.com", org_id="org-other-2", workspace_id="ws-other-2")
    foreign = client.get(f"{BASE}/fields/field-north/crop-condition", headers=other_headers).json()
    assert foreign["summary_status"] == "no_observations"


def test_nonfinite_numbers_are_rejected_at_the_route(client, db):
    """Audit finding 2: pydantic accepts "NaN"/"Infinity" unless told not to."""
    _, _, headers = _auth(db)
    base = {
        "unit": "vine", "object_label": "cluster", "design": "simple_random", "population_units": 100,
        "sample_counts": [10, 12, 8, 11, 9], "count_source": "manual_count",
        "detection_rate": {"value": 0.8, "standard_error": 0.04}, "unit_weight_kg": {"value": 0.15, "standard_error": 0.0075},
    }
    variants = [
        {**base, "sample_counts": [10, "NaN", 8, 11, 9]},
        {**base, "sample_counts": [10, "Infinity", 8, 11, 9]},
        {**base, "unit_weight_kg": {"value": "NaN", "standard_error": 0.01}},
        {**base, "unit_weight_kg": {"value": 0.15, "standard_error": "Infinity"}},
        {**base, "detection_rate": {"value": "-Infinity", "standard_error": 0.01}},
        {**base, "area_hectares": "NaN"},
    ]
    for body in variants:
        response = client.post(f"{BASE}/crop-intelligence/production-estimate", json=body, headers=headers)
        assert response.status_code == 422, body
    raw_nan = '{"unit":"vine","object_label":"cluster","design":"simple_random","population_units":100,' \
              '"sample_counts":[10,NaN,8,11,9],"count_source":"manual_count"}'
    response = client.post(f"{BASE}/crop-intelligence/production-estimate", content=raw_nan,
                           headers={**headers, "Content-Type": "application/json"})
    # Raw NaN is not JSON; the 422 must still serialize, echoing the rejected value as a string.
    assert response.status_code == 422, response.text
    assert any(error.get("input") == "NaN" for error in response.json()["detail"])
    raw_infinity = raw_nan.replace("NaN", "Infinity").replace('"count_source"', '"area_hectares":-Infinity,"count_source"')
    response = client.post(f"{BASE}/crop-intelligence/production-estimate", content=raw_infinity,
                           headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    inputs = {error.get("input") for error in response.json()["detail"]}
    assert "Infinity" in inputs

    window = {
        "biofix": "2026-04-01", "biofix_type": "planting", "as_of": "2026-04-30", "base_c": "NaN",
        "degree_day_method": "simple_average", "observed": [{"date": "2026-04-01", "tmax_c": "Infinity", "tmin_c": 10}],
    }
    assert client.post(f"{BASE}/crop-intelligence/harvest-window", json=window, headers=headers).status_code == 422



def test_self_attested_detector_validation_is_rejected_at_the_route(client, db):
    _, _, headers = _auth(db)
    body = {
        "unit": "vine", "object_label": "cluster", "design": "simple_random", "population_units": 100,
        "sample_counts": [10, 12, 8, 11, 9], "count_source": "validated_detector", "detector_validation_id": "trust-me",
        "detection_rate": {"value": 0.8, "standard_error": 0.04}, "unit_weight_kg": {"value": 0.15, "standard_error": 0.0075},
    }
    result = client.post(f"{BASE}/crop-intelligence/production-estimate", json=body, headers=headers).json()
    assert result["status"] == "not_estimable"
    assert "detector_evaluation_not_in_server_registry" in result["reasons"]


def test_almond_hull_split_maturity_route(client, db):
    _, _, headers = _auth(db)
    body = {
        "crop": "Almonds", "design": "simple_random", "count_source": "manual_count",
        "samples": [{"unit_id": f"tree-{i}", "counts": {"hull_split": s, "hull_intact": 10 - s}} for i, s in enumerate((2, 4, 6, 3, 5))],
        "readiness": {"ready_stages": ["hull_split", "hull_open_dry"], "threshold_share": 0.5, "source": "Grower plan (test)"},
    }
    result = client.post(f"{BASE}/crop-intelligence/maturity-stages", json=body, headers=headers).json()
    assert result["crop_id"] == "almond" and result["status"] == "estimated"
    assert result["stage_shares"]["hull_split"]["share"] == 0.4
    assert result["readiness"]["status"] == "uncertain"
    bad = {**body, "samples": [{"unit_id": "t", "counts": {"hull_split": "NaN"}}]}
    assert client.post(f"{BASE}/crop-intelligence/maturity-stages", json=bad, headers=headers).status_code == 422
    unsupported = client.post(f"{BASE}/crop-intelligence/maturity-stages", json={**body, "crop": "dragonfruit"}, headers=headers).json()
    assert unsupported["reasons"] == ["crop_profile_not_supported"]


def test_stratified_production_route_uses_stratum_weights(client, db):
    """Second review: stratified designs must not use the pooled sample mean."""
    _, _, headers = _auth(db)
    body = {
        "unit": "tree", "object_label": "fruit", "design": "stratified_random", "population_units": 100,
        "count_source": "manual_count",
        "strata": [{"stratum_id": "high-load", "population_units": 10, "sample_counts": [10, 10, 10, 10, 10]},
                   {"stratum_id": "low-load", "population_units": 90, "sample_counts": [1, 1, 1, 1, 1]}],
    }
    result = client.post(f"{BASE}/crop-intelligence/production-estimate", json=body, headers=headers).json()
    assert result["extrapolated_visible_objects"]["value"] == 190.0
    assert result["variance_method"] == "stratified_expansion_satterthwaite_df"
    pooled = {**body, "strata": None, "sample_counts": [10] * 5 + [1] * 5}
    refused = client.post(f"{BASE}/crop-intelligence/production-estimate", json=pooled, headers=headers).json()
    assert refused["status"] == "not_estimable"
    assert "stratified_random_requires_at_least_2_strata_with_population_and_samples" in refused["reasons"]


def test_out_of_range_estimate_inputs_are_rejected_at_the_route(client, db):
    """Products and squares of unbounded inputs overflowed into a 500."""
    _, _, headers = _auth(db)
    base = {
        "unit": "vine", "object_label": "cluster", "design": "simple_random", "population_units": 100,
        "sample_counts": [10, 12, 8, 11, 9], "count_source": "manual_count",
        "detection_rate": {"value": 0.8, "standard_error": 0.04}, "unit_weight_kg": {"value": 0.15, "standard_error": 0.0075},
    }
    for body in (
        {**base, "sample_counts": [10, 1e200, 8, 11, 9]},
        {**base, "sample_counts": [10, -1, 8, 11, 9]},
        {**base, "unit_weight_kg": {"value": 1e300, "standard_error": 1e300}},
        {**base, "design": "stratified_random", "sample_counts": [],
         "strata": [{"stratum_id": "a", "population_units": 50, "sample_counts": [1e200, 1]},
                    {"stratum_id": "b", "population_units": 50, "sample_counts": [1, 2]}]},
    ):
        response = client.post(f"{BASE}/crop-intelligence/production-estimate", json=body, headers=headers)
        assert response.status_code == 422, body
    stages = {
        "crop": "almond", "design": "simple_random", "count_source": "manual_count",
        "samples": [{"unit_id": f"tree-{i}", "counts": {"hull_split": 1e200, "hull_intact": 1}} for i in range(5)],
    }
    assert client.post(f"{BASE}/crop-intelligence/maturity-stages", json=stages, headers=headers).status_code == 422


def test_zero_variance_stratified_route_is_flagged_and_gets_no_market_proposal(client, db):
    _, _, headers = _auth(db)
    body = {
        "unit": "tree", "object_label": "fruit", "design": "stratified_random", "population_units": 100,
        "count_source": "manual_count", "area_hectares": "1", "include_market_proposal": True,
        "detection_rate": {"value": 0.8, "standard_error": 0.04}, "unit_weight_kg": {"value": 0.15, "standard_error": 0.0075},
        "strata": [{"stratum_id": "high-load", "population_units": 10, "sample_counts": [10, 10, 10, 10, 10]},
                   {"stratum_id": "low-load", "population_units": 90, "sample_counts": [1, 1, 1, 1, 1]}],
    }
    result = client.post(f"{BASE}/crop-intelligence/production-estimate", json=body, headers=headers).json()
    assert result["status"] == "estimated"
    assert result["interval_reliability"] == "unreliable_zero_sample_variance"
    assert result["market_yield_proposal"] is None
