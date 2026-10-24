"""Integrity and scientific plausibility of the committed DMRV reference dataset."""
from __future__ import annotations

import pytest

from app.intelligence_platform.dmrv_engine import build_dmrv_analysis, load_reference
from app.intelligence_platform.geography import Gazetteer
from app.intelligence_platform.schemas import BUILTIN_SCHEMAS, validation_errors

REF = load_reference()
DATA = REF.data
GAZ = Gazetteer(DATA["gazetteer"])


def _district(geoname_id: str) -> tuple[str, str, str]:
    for country, block in DATA["gazetteer"].items():
        for item in block["districts"]:
            if str(item["id"]) == geoname_id:
                return country, block["states"][item["admin1"]]["name"], item["name"]
    raise AssertionError(geoname_id)


def _analysis(state: str, district: str, crop: str, country: str = "IN", **kw):
    return build_dmrv_analysis(country=country, state=state, district=district, crop_name=crop, reference=REF, **kw)


def test_dataset_declares_sources_licenses_and_full_coverage():
    assert DATA["dataset"] == "agroai-dmrv-reference" and DATA["generated_at"]
    for key in ("gazetteer", "climate", "soil"):
        assert DATA["sources"][key]["license"] and DATA["sources"][key]["url"].startswith("https://")
    assert DATA["unresolved_targets"] == []
    assert len(DATA["gazetteer"]["IN"]["districts"]) > 600
    assert set(DATA["climate"]) == set(DATA["soil"]) and len(DATA["climate"]) >= 40


@pytest.mark.parametrize("geoname_id", sorted(DATA["climate"]))
def test_climate_normals_are_means_of_daily_values_not_extremes(geoname_id):
    record = DATA["climate"][geoname_id]
    assert record["period"] == "2004-2023"
    annual_rain = 0.0
    for month in range(1, 13):
        row = record["monthly"][str(month)]
        assert row["days"] >= 28 * 19, "each calendar month must average about 20 years of daily values"
        assert -15 < row["tmin_c"] < row["tmean_c"] < row["tmax_c"] < 44, row  # mean daily Tmax, never a monthly extreme
        assert 2 <= row["tmax_c"] - row["tmin_c"] <= 25
        assert 5 <= row["rh_mean_pct"] <= 100 and 0 <= row["wind_2m_ms"] < 12 and 3 <= row["solar_mj_m2_day"] <= 32
        annual_rain += row["precip_mm_day"] * 30.4
    assert 50 < annual_rain < 5000


def test_known_districts_resolve_and_ambiguity_is_detected():
    gb = GAZ.resolve("IN", "Uttar Pradesh", "Gautam Buddha Nagar")
    assert gb["status"] == "resolved" and str(gb["geoname_id"]) in DATA["climate"]
    bihar, maha = GAZ.resolve("IN", "Bihar", "Aurangabad"), GAZ.resolve("IN", "Maharashtra", "Aurangabad")
    assert bihar["status"] == maha["status"] == "resolved" and bihar["geoname_id"] != maha["geoname_id"]
    assert GAZ.resolve("IN", "Uttar Pradesh", "Aurangabad")["status"] == "state_mismatch"
    assert GAZ.resolve("BD", "Rajshahi", "Bogra")["status"] == "resolved"


def test_reference_et0_and_rainfall_are_physically_plausible_for_delhi_ncr():
    result = _analysis("Uttar Pradesh", "Gautam Buddha Nagar", "wheat")
    et0_calcs = [c for c in result["calculations"] if c["tool_id"] == "fao56.et0.penman_monteith_monthly.v1"]
    assert len(et0_calcs) == 12
    annual_et0 = sum(c["output"]["et0_mm_day"] * 30.4 for c in et0_calcs)
    assert 1100 < annual_et0 < 2100  # semi-arid Indo-Gangetic plain
    june = next(c for c in et0_calcs if c["inputs"]["month"] == 6)["output"]["et0_mm_day"]
    january = next(c for c in et0_calcs if c["inputs"]["month"] == 1)["output"]["et0_mm_day"]
    assert june > 2 * january
    season = result["water_balance"]["season_etc_mm"]
    assert 250 < season < 650  # rabi wheat seasonal crop ET


def test_real_districts_produce_different_grounded_advice():
    assam = _analysis("Assam", "Nagaon", "rice")
    rajasthan = _analysis("Rajasthan", "Bikaner", "rice")
    punjab_wheat = _analysis("Punjab", "Ludhiana", "wheat")
    assert rajasthan["water_balance"]["season_net_demand_mm"] > assam["water_balance"]["season_net_demand_mm"]
    texts = [" ".join(r["action"] for r in a["structured_output"]["recommendations"]) for a in (assam, rajasthan, punjab_wheat)]
    assert len(set(texts)) == 3


@pytest.mark.parametrize("geoname_id", sorted(DATA["climate"]))
def test_every_precomputed_district_yields_a_valid_cited_contract(geoname_id):
    country, state, district = _district(geoname_id)
    crops = ("wheat", "rice", "cotton") if country == "IN" else ("wheat", "rice", "potato")
    for crop in crops:
        result = _analysis(state, district, crop, country=country)
        structured = result["structured_output"]
        assert not validation_errors(structured, BUILTIN_SCHEMAS["dmrv_advisory"])
        known = {e["id"] for e in result["evidence"]} | {c["id"] for c in result["calculations"]}
        assert all(r["evidence_ids"] and set(r["evidence_ids"]) <= known for r in structured["recommendations"])
        assert result["water_balance"] and result["water_balance"]["season_etc_mm"] > 0


def test_crop_without_a_local_season_reports_the_gap_instead_of_inventing_a_calendar():
    result = _analysis("Rajshahi", "Bogra", "cotton", country="BD")
    assert result["water_balance"] is None and result["calendar"]["planting"] is None
    assert any("crop.planted_at or crop.season" in item for item in result["structured_output"]["missing_data"])
    assert result["structured_output"]["confidence"] == "low"
    seasonal = _analysis("Rajshahi", "Bogra", "cotton", country="BD", season="kharif")
    assert seasonal["water_balance"]["season_etc_mm"] > 0
