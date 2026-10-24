"""DMRV grounding engine: scientific correctness, differentiation, provenance and safety."""
from __future__ import annotations

import re
from datetime import date

import pytest

from app.intelligence_platform.dmrv_engine import DmrvInputError, build_dmrv_analysis
from app.intelligence_platform.geography import Gazetteer, normalize
from app.intelligence_platform.schemas import BUILTIN_SCHEMAS, validation_errors
from app.services import crop_water_parameters as cwp
from app.services.scientific_tool_registry import get_scientific_tool_registry
from tests.unit.dmrv_reference_fixture import DATA, synthetic_reference

REF = synthetic_reference()


def _run(**overrides):
    args = {"country": "IN", "state": "Uttar Pradesh", "district": "Gautam Buddha Nagar", "crop_name": "wheat", "reference": REF}
    args.update(overrides)
    return build_dmrv_analysis(**args)


def _calc(result, calc_id):
    return next(c for c in result["calculations"] if c["id"] == calc_id)


# ---------------------------------------------------------------- scientific tools

def test_penman_monteith_matches_fao56_example_17():
    # FAO-56 Example 17 (Bangkok, April): ET0 = 5.72 mm/day, Rn = 14.33, Ra = 38.06.
    result = get_scientific_tool_registry().run("fao56.et0.penman_monteith_monthly.v1", {
        "tmax_c": 34.8, "tmin_c": 25.6, "solar_radiation_mj_m2_day": 22.65, "wind_speed_2m_ms": 2.0,
        "latitude_deg": 13.73, "elevation_m": 2, "month": 4, "day_of_year": 105,
        "actual_vapour_pressure_kpa": 2.85, "tmean_previous_month_c": 29.2,
    })
    assert result.status == "COMPUTED"
    assert result.output["et0_mm_day"] == pytest.approx(5.72, abs=0.02)
    assert result.output["net_radiation_mj_m2_day"] == pytest.approx(14.33, abs=0.02)
    assert result.output["extraterrestrial_radiation_mj_m2_day"] == pytest.approx(38.06, abs=0.02)
    assert result.output["soil_heat_flux_mj_m2_day"] == pytest.approx(0.14, abs=0.001)


@pytest.mark.parametrize("bad", [
    {"tmin_c": 40},  # Tmin above Tmax
    {"rh_mean_pct": None},  # neither RH nor ea
    {"latitude_deg": 80},
    {"wind_speed_2m_ms": -1},
    {"month": 13},
    {"tmax_c": float("nan")},
    {"tmax_c": True},
])
def test_penman_monteith_fails_closed(bad):
    inputs = {"tmax_c": 30, "tmin_c": 15, "solar_radiation_mj_m2_day": 18, "wind_speed_2m_ms": 2, "latitude_deg": 28,
              "elevation_m": 200, "month": 3, "rh_mean_pct": 55}
    inputs.update(bad)
    assert get_scientific_tool_registry().run("fao56.et0.penman_monteith_monthly.v1", inputs).status in {"INVALID_INPUT", "NOT_COMPUTABLE"}


def test_effective_rainfall_usda_scs_is_continuous_and_bounded():
    run = get_scientific_tool_registry().run
    assert run("water.effective_rainfall.usda_scs_monthly.v1", {"monthly_precipitation_mm": 0}).output["effective_rainfall_mm"] == 0
    assert run("water.effective_rainfall.usda_scs_monthly.v1", {"monthly_precipitation_mm": 100}).output["effective_rainfall_mm"] == pytest.approx(84.0)
    below = run("water.effective_rainfall.usda_scs_monthly.v1", {"monthly_precipitation_mm": 249.999}).output["effective_rainfall_mm"]
    at = run("water.effective_rainfall.usda_scs_monthly.v1", {"monthly_precipitation_mm": 250}).output["effective_rainfall_mm"]
    assert below == pytest.approx(at, abs=0.01) == pytest.approx(150.0, abs=0.01)
    for total in (10, 80, 200, 400, 900):
        assert run("water.effective_rainfall.usda_scs_monthly.v1", {"monthly_precipitation_mm": total}).output["effective_rainfall_mm"] <= total
    assert run("water.effective_rainfall.usda_scs_monthly.v1", {"monthly_precipitation_mm": -5}).status == "INVALID_INPUT"


@pytest.mark.parametrize(("sand", "silt", "clay", "expected"), [
    (92, 4, 4, "sand"), (82, 12, 6, "loamy sand"), (65, 25, 10, "sandy loam"), (40, 40, 20, "loam"),
    (20, 65, 15, "silt loam"), (5, 88, 7, "silt"), (60, 12, 28, "sandy clay loam"), (35, 30, 35, "clay loam"),
    (10, 55, 35, "silty clay loam"), (50, 5, 45, "sandy clay"), (5, 45, 50, "silty clay"), (20, 20, 60, "clay"),
])
def test_usda_texture_triangle(sand, silt, clay, expected):
    assert cwp.usda_texture_class(sand, silt, clay) == expected


def test_kc_curve_follows_fao56_shape():
    wheat = cwp.resolve_crop("wheat")
    lengths = wheat.stage_lengths_days
    assert cwp.kc_for_day(wheat, 0, lengths) == ("initial", wheat.kc_ini)
    assert cwp.kc_for_day(wheat, 44, lengths)[1] == pytest.approx(wheat.kc_mid)
    assert cwp.kc_for_day(wheat, 60, lengths) == ("mid_season", wheat.kc_mid)
    assert cwp.kc_for_day(wheat, sum(lengths) - 1, lengths)[1] == pytest.approx(wheat.kc_end)
    assert cwp.resolve_crop("Paddy").crop_id == "rice"
    assert cwp.resolve_crop("Bengal gram").crop_id == "chickpea"
    assert cwp.resolve_crop("quinoa") is None
    assert cwp.stage_from_label("Grain filling") == "mid_season"
    assert cwp.stage_from_label("tillering") == "development"
    assert cwp.stage_from_label("physiological maturity") == "late_season"


# ---------------------------------------------------------------- geography

def test_geography_resolution_and_disclosed_precision():
    gaz = Gazetteer(DATA["gazetteer"])
    hit = gaz.resolve("IN", "UP", "Gautam Buddha Nagar District")
    assert hit["status"] == "resolved" and hit["state"] == "Uttar Pradesh" and hit["precision"] == "administrative_representative_point"
    assert gaz.resolve("IN", "Bihar", "aurangabad")["geoname_id"] == 102
    assert gaz.resolve("IN", "Maharashtra", "Aurangabad")["geoname_id"] == 103
    mismatch = gaz.resolve("IN", "Uttar Pradesh", "Aurangabad")
    assert mismatch["status"] == "state_mismatch" and {c["geoname_id"] for c in mismatch["candidates"]} == {102, 103}
    renamed = gaz.resolve("IN", "Uttar Pradesh", "Allahabad")
    assert renamed["status"] == "resolved" and renamed["district"] == "Prayagraj" and renamed["match_method"] == "rename_alias"
    typo = gaz.resolve("IN", "Uttar Pradesh", "Gautam Budha Nagar")
    assert typo["status"] == "district_not_found" and "Gautam Buddha Nagar" in typo["suggestions"]
    assert gaz.resolve("IN", "Atlantis", "Meerut")["status"] == "state_not_found"
    assert gaz.resolve("US", "California", "Fresno")["status"] == "country_not_supported"
    assert normalize("  Bogra  Zila ") == "bogra"


@pytest.mark.parametrize(("state", "district", "code"), [
    ("Uttar Pradesh", "Aurangabad", "location_state_mismatch"),
    ("Uttar Pradesh", "Nowhere", "location_district_not_found"),
    ("Narnia", "Meerut", "location_state_not_found"),
    ("Uttar Pradesh", "'; DROP TABLE districts; --", "location_district_not_found"),
])
def test_unresolvable_locations_are_machine_readable_errors(state, district, code):
    with pytest.raises(DmrvInputError) as failure:
        _run(state=state, district=district)
    assert failure.value.code == code
    assert failure.value.detail["resolution"]["status"] != "resolved"


def test_unsupported_crop_is_explicit():
    with pytest.raises(DmrvInputError) as failure:
        _run(crop_name="quinoa")
    assert failure.value.code == "crop_not_supported"
    assert "wheat" in failure.value.detail["supported_crops"]


# ---------------------------------------------------------------- differentiation

def _all_text(result) -> str:
    return " ".join(r["action"] for r in result["structured_output"]["recommendations"])


def test_different_crops_in_one_district_get_different_grounded_advice():
    wheat, rice, cotton = _run(), _run(crop_name="paddy"), _run(crop_name="cotton")
    assert wheat["water_balance"]["season_etc_mm"] != rice["water_balance"]["season_etc_mm"] != cotton["water_balance"]["season_etc_mm"]
    assert len({_all_text(wheat), _all_text(rice), _all_text(cotton)}) == 3
    assert "alternate wetting and drying" in _all_text(rice).lower()
    assert "pheromone" in _all_text(cotton).lower()
    assert "residue" in _all_text(wheat).lower()
    assert wheat["calendar"]["season"] == "rabi" and rice["calendar"]["season"] == "kharif"


def test_same_crop_in_different_districts_reflects_local_climate_and_soil():
    north = _run(crop_name="rice")
    east = _run(crop_name="rice", state="Bihar", district="Aurangabad")
    desert = _run(crop_name="rice", state="Rajasthan", district="Bikaner")
    assert north["water_balance"]["season_net_demand_mm"] > east["water_balance"]["season_net_demand_mm"]
    assert north["soil_reference"]["texture_class"] == "loam"
    assert east["soil_reference"]["texture_class"] == "clay"
    assert desert["soil_reference"]["texture_class"] in {"sand", "loamy sand"}
    assert "waterlogging" in _all_text(east) and "low water holding" in _all_text(desert).lower()
    assert north["geography"]["geoname_id"] != east["geography"]["geoname_id"]


def test_season_and_planting_date_change_the_calendar_and_water_demand():
    kharif = _run(crop_name="maize", season="kharif")
    rabi = _run(crop_name="maize", season="rabi")
    planted = _run(crop_name="maize", planted_at=date(2026, 2, 15))
    assert kharif["calendar"]["planting_basis"] == "assumed_from_season_label"
    assert planted["calendar"]["planting_basis"] == "planted_at"
    assert "start_date" in planted["calendar"]["stage_windows"][0]
    demands = {kharif["water_balance"]["season_net_demand_mm"], rabi["water_balance"]["season_net_demand_mm"], planted["water_balance"]["season_net_demand_mm"]}
    assert len(demands) == 3


def test_growth_stage_from_dates_and_contradiction_is_reported():
    computed = _run(planted_at=date(2025, 11, 10), as_of=date(2025, 12, 5))  # day 25 -> development
    assert computed["calendar"]["computed_stage"] == "development"
    assert computed["calendar"]["current_stage"] == "development"
    clash = _run(planted_at=date(2025, 11, 10), as_of=date(2025, 12, 5), growth_stage="harvest")
    assert clash["calendar"]["stage_contradiction"] is True
    assert clash["structured_output"]["confidence"] == "low"
    assert any("Contradictory evidence" in item for item in clash["structured_output"]["limitations"])
    future = _run(planted_at=date(2026, 3, 1), as_of=date(2026, 1, 1))
    assert future["calendar"]["computed_stage"] == "not_yet_planted"


def test_heat_risk_uses_stage_months_and_published_threshold():
    timely = _run(planted_at=date(2025, 11, 10))
    late = _run(planted_at=date(2025, 12, 25))
    assert timely["heat_risk"]["exceeding_months"] == []
    assert [m["month"] for m in late["heat_risk"]["exceeding_months"]] == ["April"]  # fixture March Tmax 30 < 32
    assert any(r["priority"] == "high" and "Heat-stress risk" in r["action"] for r in late["structured_output"]["recommendations"])


# ---------------------------------------------------------------- calculations and provenance

def test_every_number_traces_to_a_registered_tool_and_evidence_resolves():
    result = _run(crop_name="rice")
    structured = result["structured_output"]
    assert not validation_errors(structured, BUILTIN_SCHEMAS["dmrv_advisory"])
    known = {e["id"] for e in result["evidence"]} | {c["id"] for c in result["calculations"]}
    for rec in structured["recommendations"]:
        assert rec["evidence_ids"], rec["action"]
        assert set(rec["evidence_ids"]) <= known
        assert rec["requires_human_approval"] is True
    stage_total = sum(_calc(result, s["calc"])["output"]["etc_mm"] for s in result["water_balance"]["stages"])
    assert result["water_balance"]["season_etc_mm"] == pytest.approx(stage_total, abs=0.1)
    registry_ids = {spec.tool_id for spec in get_scientific_tool_registry().specs()}
    assert {c["tool_id"] for c in result["calculations"]} <= registry_ids
    assert all(c["status"] == "COMPUTED" for c in result["calculations"])
    sources = {e["id"]: e for e in result["evidence"]}
    assert sources["ref:soilgrids:101"]["license"] == "CC BY 4.0"
    assert result["reference_dataset"]["sha256"] == REF.sha256


def test_engine_is_deterministic():
    assert _run(crop_name="cotton", season="kharif") == _run(crop_name="cotton", season="kharif")


_DOSE = re.compile(r"\b(apply|use|add)\b[^.]{0,40}\b\d+(\.\d+)?\s*(kg|g|t|bags?)\b", re.IGNORECASE)
# Positive outcome claims only; the engine's own disclaimers ("does not establish verified ...") are expected.
_CARBON_CLAIM = re.compile(r"(tco2|t co2e?\b|carbon credits? (earned|generated|issued)|(reduces|reduced|cuts) emissions by|(achieves|delivers|generates) (verified )?(emission|carbon))", re.IGNORECASE)


@pytest.mark.parametrize("crop", cwp.supported_crops())
def test_no_fertilizer_doses_or_carbon_claims_for_any_crop(crop):
    measurements = {"stage_lengths_days": [20, 30, 40, 20], "soil_test": {"available_n_kg_ha": 150, "available_p_kg_ha": 8, "ph": 9.0}}
    result = _run(crop_name=crop, measurements=measurements)
    for rec in result["structured_output"]["recommendations"]:
        text = f"{rec['action']} {rec['rationale']}"
        assert not _DOSE.search(text), text
        assert not _CARBON_CLAIM.search(text), text
    assert any("No fertilizer dose, carbon quantity or emissions outcome" in item for item in result["structured_output"]["limitations"])


def test_missing_inputs_are_reported_not_invented():
    result = _run()
    missing = " ".join(result["structured_output"]["missing_data"])
    for needed in ("planted_at", "soil test", "efficiency", "field boundary"):
        assert needed in missing
    assert result["measured_soil_water"] is None and result["soil_test"] is None
    assert not any("trigger" in r["action"].lower() for r in result["structured_output"]["recommendations"])
    chickpea = _run(crop_name="chickpea")
    assert chickpea["water_balance"] is None
    assert any("stage_lengths_days" in m for m in chickpea["structured_output"]["missing_data"])
    supplied = _run(crop_name="chickpea", measurements={"stage_lengths_days": [20, 30, 40, 20]})
    assert supplied["calendar"]["stage_lengths_basis"] == "caller_stage_lengths" and supplied["water_balance"]


def test_district_without_precomputed_climate_degrades_honestly():
    result = _run(district="Prayagraj")
    assert result["coverage"]["climate"] is False and result["water_balance"] is None
    assert result["structured_output"]["confidence"] == "low"
    assert any("climate normals" in m for m in result["structured_output"]["missing_data"])


def test_measured_soil_water_drives_event_level_numbers_with_registered_tools():
    measurements = {
        "soil_water": {"field_capacity_vwc_fraction": 0.30, "wilting_point_vwc_fraction": 0.13, "current_vwc_fraction": 0.19},
        "irrigation_system": {"efficiency": 0.75}, "field_area_ha": 2.0, "root_zone_depth_m": 1.0,
    }
    result = _run(measurements=measurements)
    water = result["measured_soil_water"]
    assert water["taw_mm"] == pytest.approx(170.0)
    assert water["raw_mm"] == pytest.approx(170.0 * 0.55)
    assert water["depletion_mm"] == pytest.approx(110.0)
    assert water["trigger_reached"] is True
    assert water["gross_refill_mm"] == pytest.approx(110.0 / 0.75, abs=0.1)
    assert water["gross_refill_volume_m3"] == pytest.approx(110.0 / 0.75 * 2.0 * 10, abs=1)
    first = result["structured_output"]["recommendations"][0]
    assert first["category"] == "irrigation" and "Irrigation trigger reached" in first["action"] and "uat:soil_water" in first["evidence_ids"]
    wet = _run(measurements={**measurements, "soil_water": {**measurements["soil_water"], "current_vwc_fraction": 0.28}})
    assert wet["measured_soil_water"]["trigger_reached"] is False
    assert "No irrigation needed yet" in wet["structured_output"]["recommendations"][0]["action"]
    with pytest.raises(DmrvInputError):
        _run(measurements={"soil_water": {"field_capacity_vwc_fraction": 0.10, "wilting_point_vwc_fraction": 0.20}})
    implausible = _run(measurements={"soil_water": {"field_capacity_vwc_fraction": 0.30, "wilting_point_vwc_fraction": 0.13, "current_vwc_fraction": 0.05}})
    assert any("below the supplied wilting point" in item for item in implausible["structured_output"]["limitations"])


def test_soil_test_ratings_follow_soil_health_card_classes():
    result = _run(measurements={"soil_test": {"available_n_kg_ha": 200, "available_p_kg_ha": 30, "available_k_kg_ha": 150, "organic_carbon_pct": 0.4, "ph": 8.8}})
    ratings = result["soil_test"]["ratings"]
    assert ratings == {"available_n_kg_ha": "low", "available_p_kg_ha": "high", "available_k_kg_ha": "medium", "organic_carbon_pct": "low"}
    nutrient = [r for r in result["structured_output"]["recommendations"] if r["category"] == "nutrients"]
    assert nutrient[0]["priority"] == "high" and "uat:soil_test" in nutrient[0]["evidence_ids"]
    assert any("strongly alkaline" in r["action"] and "sodicity" in r["action"] for r in nutrient)
    legume = _run(crop_name="soybean", season="kharif")
    assert any("Rhizobium" in r["action"] for r in legume["structured_output"]["recommendations"])


def test_area_selection_limits_categories():
    result = _run(areas=["irrigation", "sustainability"])
    assert {r["category"] for r in result["structured_output"]["recommendations"]} == {"irrigation", "sustainability"}
