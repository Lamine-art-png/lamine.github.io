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
        "weather_source": "test station",
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
