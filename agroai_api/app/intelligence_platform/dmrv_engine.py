"""Evidence-grounded DMRV advisory analysis.

Combines a resolved administrative location, versioned public reference data
(GeoNames, NASA POWER daily-derived monthly means, ISRIC SoilGrids), cited FAO-56 crop
parameters and optional caller measurements. Every number is produced by a
registered scientific tool, and every recommendation cites the evidence ids it
rests on. Deterministic: the same inputs and dataset give the same output.

Used by the TEST UAT preview (no model) and as grounding evidence for LIVE
``dmrv_advisory`` runs. It never prescribes fertilizer doses, never states a
carbon/emissions outcome, and labels regional values as coarse context.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.intelligence_platform.geography import Gazetteer
from app.services import crop_water_parameters as cwp
from app.services.scientific_tool_registry import get_scientific_tool_registry

ENGINE_VERSION = "dmrv-engine/2"
REFERENCE_PATH = Path(__file__).with_name("reference_data") / "dmrv_reference_v1.json"
AREAS = ("irrigation", "nutrients", "soil", "monitoring", "sustainability")
_MONTH = {index: calendar.month_name[index] for index in range(1, 13)}
_NOMINAL_YEAR = 2025


class DmrvInputError(ValueError):
    """A request the engine cannot ground; mapped to HTTP 422 by callers."""

    def __init__(self, code: str, message: str, **detail: Any):
        super().__init__(message)
        self.code = code
        self.detail = {"code": code, "message": message, **detail}


@dataclass(frozen=True)
class ReferenceData:
    data: dict[str, Any]
    sha256: str

    @property
    def gazetteer(self) -> Gazetteer:
        return Gazetteer(self.data["gazetteer"])


@lru_cache(maxsize=1)
def load_reference(path: str | None = None) -> ReferenceData:
    raw = Path(path or REFERENCE_PATH).read_bytes()
    return ReferenceData(json.loads(raw), hashlib.sha256(raw).hexdigest())


class _Run:
    """Per-request evidence and calculation ledger."""

    def __init__(self, measurement_prefix: str = "uat", measurement_label: str = "Caller-declared synthetic UAT measurement") -> None:
        self.measurement_prefix = measurement_prefix
        self.measurement_label = measurement_label
        self.registry = get_scientific_tool_registry()
        self.evidence: list[dict[str, Any]] = []
        self.calculations: list[dict[str, Any]] = []
        self.missing: list[str] = []
        self.limitations: list[str] = []

    def add_evidence(self, item: dict[str, Any]) -> str:
        if not any(existing["id"] == item["id"] for existing in self.evidence):
            self.evidence.append(item)
        return item["id"]

    def tool(self, tool_id: str, inputs: dict[str, Any], label: str) -> dict[str, Any] | None:
        result = self.registry.run(tool_id, inputs)
        calc_id = f"calc:{len(self.calculations) + 1:03d}"
        self.calculations.append({
            "id": calc_id,
            "label": label,
            "tool_id": result.tool_id,
            "tool_version": result.version,
            "status": result.status,
            "inputs": result.normalized_inputs or {k: v for k, v in inputs.items() if v is not None},
            "output": result.output,
            "missing_requirements": result.missing_requirements,
            "invalid_inputs": result.invalid_inputs,
        })
        if result.status != "COMPUTED":
            return None
        return {"id": calc_id, **result.output}

    def need(self, item: str) -> None:
        if item not in self.missing:
            self.missing.append(item)

    def limit(self, item: str) -> None:
        if item not in self.limitations:
            self.limitations.append(item)


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _resolve_location(reference: ReferenceData, run: _Run, country: str, state: str | None, district: str) -> dict[str, Any]:
    result = reference.gazetteer.resolve(country, state, district)
    status = result["status"]
    if status != "resolved":
        messages = {
            "country_not_supported": "This country is not in the DMRV reference gazetteer.",
            "state_not_found": "The state/region label did not match the gazetteer.",
            "district_not_found": "The district label did not match any district in that state/region.",
            "state_mismatch": "The district exists, but not in the supplied state/region.",
            "ambiguous": "The district label matches more than one administrative area.",
        }
        raise DmrvInputError(f"location_{status}", messages[status], resolution=result)
    gazetteer_source = reference.data["sources"]["gazetteer"]
    run.add_evidence({
        "id": f"ref:geonames:{result['geoname_id']}",
        "type": "administrative_location",
        "source": gazetteer_source["name"], "license": gazetteer_source["license"],
        "dataset_generated_at": reference.data["generated_at"],
        "summary": f"{result['district']}, {result['state']}, {result['country']} "
                   f"(representative point {result['latitude']:.3f}, {result['longitude']:.3f})",
        "precision": result["precision"],
    })
    if result["match_method"] == "rename_alias":
        run.limit("District label matched through an official rename; update stored labels to the current name.")
    return result


def _calendar(run: _Run, crop: cwp.CropWaterParameters, country: str, season: str | None,
              planted_at: date | None, as_of: date | None, stage_label: str | None,
              stage_lengths: tuple[int, int, int, int] | None) -> dict[str, Any]:
    lengths = stage_lengths or crop.stage_lengths_days
    basis = "caller_stage_lengths" if stage_lengths else ("fao56_table11" if lengths else None)
    planting: date | None = planted_at
    planting_basis = "planted_at" if planted_at else None
    season_key = (season or "").strip().casefold() or None
    months = cwp.SEASON_PLANTING_MONTH.get(country, {})
    if planting is None:
        chosen = season_key if season_key in months else None
        if season_key and chosen is None:
            run.limit(f"Season '{season}' is not a recognised season label for {country}; typical crop season used instead.")
        if chosen is None:
            chosen = next((s for s in crop.typical_seasons.get(country, ()) if s in months), None)
            planting_basis = "assumed_typical_crop_season" if chosen else None
        else:
            planting_basis = "assumed_from_season_label"
        if chosen:
            planting = date(_NOMINAL_YEAR, months[chosen], 1)
            season_key = chosen
            run.limit(f"Planting date assumed as 1 {_MONTH[planting.month]} ({chosen} season); supply crop.planted_at for a field-specific calendar.")
            run.need("crop.planted_at (actual sowing/transplanting date)")
    label_stage = cwp.stage_from_label(stage_label)
    if stage_label and label_stage is None:
        run.limit(f"Growth stage '{stage_label}' was not recognised; stage-specific advice uses the calendar only.")
    computed_stage, days_after_planting = None, None
    if planted_at and as_of and lengths:
        days_after_planting = (as_of - planted_at).days
        if days_after_planting < 0:
            computed_stage = "not_yet_planted"
        elif days_after_planting >= sum(lengths):
            computed_stage = "past_season"
        else:
            computed_stage = cwp.kc_for_day(crop, days_after_planting, lengths)[0]
    contradiction = bool(label_stage and computed_stage and computed_stage in cwp.STAGES and label_stage != computed_stage)
    if contradiction:
        run.limit(f"Contradictory evidence: reported growth stage maps to {label_stage}, but planting date and as-of date "
                  f"imply {computed_stage}. Reported stage is used; verify the planting date or the stage observation.")
    if computed_stage in {"not_yet_planted", "past_season"}:
        run.limit(f"as_of date is {computed_stage.replace('_', ' ')} for the supplied planting date.")
    if not lengths:
        run.need("stage_lengths_days for this crop (no FAO-56 Table 11 entry is used)")
    windows = []
    if lengths and planting:
        start = 0
        for stage, length in zip(cwp.STAGES, lengths):
            first = planting + timedelta(days=start)
            last = planting + timedelta(days=start + length - 1)
            windows.append({
                "stage": stage, "start_day": start, "end_day": start + length - 1,
                "start_month": _MONTH[first.month], "end_month": _MONTH[last.month],
                **({"start_date": first.isoformat(), "end_date": last.isoformat()} if planted_at else {}),
            })
            start += length
    return {
        "season": season_key,
        "planting_basis": planting_basis,
        "planting": planting,
        "stage_lengths_days": list(lengths) if lengths else None,
        "stage_lengths_basis": basis,
        "stage_lengths_source": crop.stage_lengths_source if basis == "fao56_table11" else None,
        "reported_stage": stage_label,
        "reported_stage_mapped": label_stage,
        "computed_stage": computed_stage,
        "days_after_planting": days_after_planting,
        "current_stage": label_stage or (computed_stage if computed_stage in cwp.STAGES else None),
        "stage_contradiction": contradiction,
        "stage_windows": windows,
    }


def _climate(reference: ReferenceData, run: _Run, geo: dict[str, Any]) -> dict[str, Any] | None:
    record = reference.data.get("climate", {}).get(str(geo["geoname_id"]))
    if not record:
        run.need("regional climate normals (district not yet in the precomputed reference set)")
        return None
    source = reference.data["sources"]["climate"]
    evidence_id = run.add_evidence({
        "id": f"ref:nasapower:{geo['geoname_id']}",
        "type": "climate_normals",
        "source": f"{record['source']} {record['period']}", "license": source["license"],
        "dataset_generated_at": reference.data["generated_at"],
        "summary": f"Monthly means of daily values, {record['period']}, at grid point {record['grid_point']['latitude']}, {record['grid_point']['longitude']}",
        "precision": "MERRA-2 0.5 x 0.625 degree meteorology and CERES 1 degree solar grids; long-term monthly means, not observed weather",
    })
    monthly = record["monthly"]
    elevation = record.get("elevation_m")
    months: dict[int, dict[str, Any]] = {}
    for month in range(1, 13):
        row = monthly[str(month)]
        prev_row, next_row = monthly[str((month - 2) % 12 + 1)], monthly[str(month % 12 + 1)]
        et0 = run.tool("fao56.et0.penman_monteith_monthly.v1", {
            "tmax_c": row["tmax_c"], "tmin_c": row["tmin_c"], "solar_radiation_mj_m2_day": row["solar_mj_m2_day"],
            "wind_speed_2m_ms": row["wind_2m_ms"], "rh_mean_pct": row["rh_mean_pct"], "latitude_deg": geo["latitude"],
            "elevation_m": elevation if elevation is not None else None, "month": month,
            "tmean_previous_month_c": prev_row["tmean_c"], "tmean_next_month_c": next_row["tmean_c"],
        }, f"Reference ET0, {_MONTH[month]}")
        precip_month = None if row["precip_mm_day"] is None else row["precip_mm_day"] * calendar.monthrange(_NOMINAL_YEAR, month)[1]
        peff = run.tool("water.effective_rainfall.usda_scs_monthly.v1", {"monthly_precipitation_mm": precip_month},
                        f"Effective rainfall, {_MONTH[month]}") if precip_month is not None else None
        months[month] = {
            "et0_mm_day": et0["et0_mm_day"] if et0 else None,
            "et0_calc": et0["id"] if et0 else None,
            "precip_mm_month": _round(precip_month),
            "effective_rain_mm_month": peff["effective_rainfall_mm"] if peff else None,
            "peff_calc": peff["id"] if peff else None,
            "tmax_c": row["tmax_c"], "tmin_c": row["tmin_c"], "tmean_c": row["tmean_c"],
        }
    if elevation is None:
        run.limit("Grid elevation missing from climate source; ET0 computed with sea-level pressure.")
    return {"evidence_id": evidence_id, "period": record["period"], "months": months}


def _season_water(run: _Run, crop: cwp.CropWaterParameters, cal: dict[str, Any], climate: dict[str, Any]) -> dict[str, Any] | None:
    lengths, planting = cal["stage_lengths_days"], cal["planting"]
    if not lengths or not planting:
        return None
    sums = {stage: {"et0": 0.0, "kc_et0": 0.0, "rain": 0.0, "peff": 0.0, "days": 0, "months": set()} for stage in cwp.STAGES}
    peak = (0.0, None, None)
    for offset in range(sum(lengths)):
        day = planting + timedelta(days=offset)
        month = climate["months"][day.month]
        if month["et0_mm_day"] is None or month["precip_mm_month"] is None:
            return None
        stage, kc = cwp.kc_for_day(crop, offset, tuple(lengths))
        days_in_month = calendar.monthrange(day.year, day.month)[1]
        rain_day = month["precip_mm_month"] / days_in_month
        ratio = (month["effective_rain_mm_month"] / month["precip_mm_month"]) if month["precip_mm_month"] else 0.0
        bucket = sums[stage]
        bucket["et0"] += month["et0_mm_day"]
        bucket["kc_et0"] += kc * month["et0_mm_day"]
        bucket["rain"] += rain_day
        bucket["peff"] += rain_day * ratio
        bucket["days"] += 1
        bucket["months"].add(day.month)
        if kc * month["et0_mm_day"] > peak[0]:
            peak = (kc * month["et0_mm_day"], stage, day.month)
    stages = []
    for stage in cwp.STAGES:
        bucket = sums[stage]
        if not bucket["days"]:
            continue
        kc_eff = bucket["kc_et0"] / bucket["et0"] if bucket["et0"] else crop.kc_mid
        etc = run.tool("fao56.etc.single_kc.v1", {"eto_mm": round(bucket["et0"], 3), "kc": round(kc_eff, 4)},
                       f"Crop ET, {stage.replace('_', ' ')} stage")
        etc_mm = etc["etc_mm"] if etc else None
        stages.append({
            "stage": stage, "days": bucket["days"],
            "months": [_MONTH[m] for m in sorted(bucket["months"], key=lambda m: (m - planting.month) % 12)],
            "et0_mm": _round(bucket["et0"]), "kc_effective": round(kc_eff, 3), "etc_mm": _round(etc_mm),
            "rainfall_mm": _round(bucket["rain"]), "effective_rainfall_mm": _round(bucket["peff"]),
            "net_demand_after_effective_rain_mm": _round(max(0.0, (etc_mm or 0.0) - bucket["peff"])),
            "calc": etc["id"] if etc else None,
        })
    total_etc = sum(s["etc_mm"] or 0 for s in stages)
    total_peff = sum(s["effective_rainfall_mm"] or 0 for s in stages)
    return {
        "basis": "climatological planning estimate (long-term monthly means), not an irrigation schedule",
        "stages": stages,
        "season_etc_mm": _round(total_etc),
        "season_effective_rainfall_mm": _round(total_peff),
        "season_net_demand_mm": _round(sum(s["net_demand_after_effective_rain_mm"] or 0 for s in stages)),
        "peak_etc_mm_day": _round(peak[0], 2), "peak_stage": peak[1], "peak_month": _MONTH.get(peak[2]),
    }


def _soil_reference(reference: ReferenceData, run: _Run, geo: dict[str, Any], crop: cwp.CropWaterParameters) -> dict[str, Any] | None:
    record = reference.data.get("soil", {}).get(str(geo["geoname_id"]))
    props = (record or {}).get("properties") or {}

    def value(name: str) -> float | None:
        return (props.get(name) or {}).get("value_0_30cm")

    if not record or record.get("error") or all(value(k) is None for k in ("sand", "clay", "phh2o")):
        run.need("regional soil reference (SoilGrids returned no value at the district point)")
        return None
    source = reference.data["sources"]["soil"]
    evidence_id = run.add_evidence({
        "id": f"ref:soilgrids:{geo['geoname_id']}",
        "type": "regional_soil_estimate",
        "source": record["source"], "license": source["license"],
        "dataset_generated_at": reference.data["generated_at"],
        "summary": "Predicted 0-30 cm topsoil properties at the district representative point",
        "precision": "250 m digital soil map prediction at one point; not a field measurement",
    })
    sand, silt, clay = value("sand"), value("silt"), value("clay")
    texture = cwp.usda_texture_class(sand, silt, clay) if None not in (sand, silt, clay) else None
    water = cwp.TEXTURE_WATER.get(texture or "")
    taw_range = raw_range = None
    if water:
        low = run.tool("soil.total_available_water.v1", {
            "field_capacity_vwc_fraction": water["wp"][0] + water["taw"][0], "wilting_point_vwc_fraction": water["wp"][0],
            "root_zone_depth_m": crop.root_depth_m[0]}, "Total available water, lower bound (texture class, shallow root zone)")
        high = run.tool("soil.total_available_water.v1", {
            "field_capacity_vwc_fraction": water["wp"][1] + water["taw"][1], "wilting_point_vwc_fraction": water["wp"][1],
            "root_zone_depth_m": crop.root_depth_m[1]}, "Total available water, upper bound (texture class, deep root zone)")
        if low and high:
            taw_range = (low["total_available_water_mm"], high["total_available_water_mm"], low["id"], high["id"])
            raw_low = run.tool("soil.readily_available_water.v1", {"total_available_water_mm": taw_range[0], "management_allowable_depletion_fraction": crop.depletion_fraction_p}, "Readily available water, lower bound (FAO-56 p)")
            raw_high = run.tool("soil.readily_available_water.v1", {"total_available_water_mm": taw_range[1], "management_allowable_depletion_fraction": crop.depletion_fraction_p}, "Readily available water, upper bound (FAO-56 p)")
            if raw_low and raw_high:
                raw_range = (raw_low["readily_available_water_mm"], raw_high["readily_available_water_mm"], raw_low["id"], raw_high["id"])
    elif texture:
        run.limit(f"Texture class '{texture}' has no FAO-56 Table 19 water-holding entry; soil water range not estimated.")
    ph = value("phh2o")
    soc_g_kg = value("soc")
    return {
        "evidence_id": evidence_id,
        "sand_pct": _round(sand), "silt_pct": _round(silt), "clay_pct": _round(clay), "texture_class": texture,
        "ph": _round(ph, 2), "ph_class": cwp.ph_class(ph) if ph is not None else None,
        "organic_carbon_pct": _round(soc_g_kg / 10, 2) if soc_g_kg is not None else None,
        "total_nitrogen_g_kg": _round(value("nitrogen"), 2), "cec_cmol_kg": _round(value("cec")),
        "taw_mm_range": [_round(taw_range[0]), _round(taw_range[1])] if taw_range else None,
        "raw_mm_range": [_round(raw_range[0]), _round(raw_range[1])] if raw_range else None,
        "calcs": [x for x in ((taw_range or ())[2:] + (raw_range or ())[2:])],
    }


def _measured_soil_water(run: _Run, crop: cwp.CropWaterParameters, m: dict[str, Any]) -> dict[str, Any] | None:
    water = m.get("soil_water") or {}
    if water.get("field_capacity_vwc_fraction") is None or water.get("wilting_point_vwc_fraction") is None:
        run.need("measured field capacity and wilting point (or soil moisture release curve)")
        return None
    evidence_id = run.add_evidence({"id": f"{run.measurement_prefix}:soil_water", "type": "caller_measurement", "source": run.measurement_label,
                                    "summary": "Soil water constants and current soil moisture supplied in the request",
                                    "observed_at": water.get("measured_at")})
    depth = m.get("root_zone_depth_m") or round(sum(crop.root_depth_m) / 2, 2)
    if not m.get("root_zone_depth_m"):
        run.limit(f"Root-zone depth assumed {depth} m (mid-point of FAO-56 Table 22 range); supply root_zone_depth_m.")
    taw = run.tool("soil.total_available_water.v1", {
        "field_capacity_vwc_fraction": water["field_capacity_vwc_fraction"],
        "wilting_point_vwc_fraction": water["wilting_point_vwc_fraction"], "root_zone_depth_m": depth}, "Total available water from supplied soil constants")
    if not taw:
        raise DmrvInputError("measurement_invalid", "Supplied field capacity must exceed wilting point.", field="measurements.soil_water")
    raw = run.tool("soil.readily_available_water.v1", {"total_available_water_mm": taw["total_available_water_mm"],
                   "management_allowable_depletion_fraction": crop.depletion_fraction_p}, "Readily available water (FAO-56 p)")
    result = {"evidence_id": evidence_id, "root_zone_depth_m": depth, "taw_mm": _round(taw["total_available_water_mm"]),
              "raw_mm": _round(raw["readily_available_water_mm"]) if raw else None, "calcs": [taw["id"]] + ([raw["id"]] if raw else [])}
    if water.get("current_vwc_fraction") is None:
        run.need("current volumetric soil moisture for an irrigation trigger decision")
        return result
    depletion = run.tool("soil.depletion_from_field_capacity.v1", {
        "field_capacity_vwc_fraction": water["field_capacity_vwc_fraction"], "current_vwc_fraction": water["current_vwc_fraction"],
        "root_zone_depth_m": depth}, "Root-zone depletion from supplied soil moisture")
    result["depletion_mm"] = _round(depletion["depletion_from_field_capacity_mm"]) if depletion else None
    result["calcs"].append(depletion["id"])
    if water["current_vwc_fraction"] < water["wilting_point_vwc_fraction"]:
        run.limit("Contradictory evidence: current soil moisture is below the supplied wilting point; verify sensor calibration.")
    result["trigger_reached"] = bool(raw and result["depletion_mm"] is not None and result["depletion_mm"] >= raw["readily_available_water_mm"])
    efficiency = (m.get("irrigation_system") or {}).get("efficiency")
    if result["depletion_mm"] and result["depletion_mm"] > 0 and efficiency:
        gross = run.tool("irrigation.gross_requirement.v1", {"net_requirement_mm": result["depletion_mm"], "efficiency": efficiency},
                         "Gross refill depth with supplied application efficiency")
        if gross:
            result["gross_refill_mm"] = _round(gross["gross_requirement_mm"])
            result["calcs"].append(gross["id"])
            area = m.get("field_area_ha")
            if area:
                volume = run.tool("irrigation.volume_from_depth.v1", {"depth_mm": gross["gross_requirement_mm"], "area_ha": area}, "Refill volume for supplied field area")
                if volume:
                    result["gross_refill_volume_m3"] = _round(volume["volume_m3"])
                    result["calcs"].append(volume["id"])
    elif result["depletion_mm"] and result["depletion_mm"] > 0:
        run.need("irrigation application efficiency (measured or system-specified)")
    return result


def _soil_test(run: _Run, country: str, m: dict[str, Any]) -> dict[str, Any] | None:
    test = m.get("soil_test") or {}
    present = {k: v for k, v in test.items() if v is not None and k != "sampled_at"}
    if not present:
        run.need("laboratory soil test (available N, P, K, organic carbon, pH, EC)")
        return None
    evidence_id = run.add_evidence({"id": f"{run.measurement_prefix}:soil_test", "type": "caller_measurement", "source": run.measurement_label,
                                    "summary": ", ".join(f"{k}={v}" for k, v in sorted(present.items())), "observed_at": test.get("sampled_at")})
    ratings = {}
    if country == "IN":
        for key in cwp.SHC_THRESHOLDS:
            if test.get(key) is not None:
                ratings[key] = cwp.shc_rating(key, float(test[key]))
    else:
        run.limit("Soil-test rating classes are loaded for India only; values are reported without a rating for this country.")
    return {"evidence_id": evidence_id, "values": present, "ratings": ratings,
            "ph_class": cwp.ph_class(float(test["ph"])) if test.get("ph") is not None else None}


def _heat_risk(crop: cwp.CropWaterParameters, cal: dict[str, Any], climate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not climate or crop.heat_threshold_tmax_c is None or not cal["stage_windows"]:
        return None
    window = next((w for w in cal["stage_windows"] if w["stage"] == crop.heat_threshold_stage), None)
    if not window:
        return None
    planting = cal["planting"]
    months = sorted({(planting + timedelta(days=d)).month for d in range(window["start_day"], window["end_day"] + 1)},
                    key=lambda m: (m - planting.month) % 12)
    exceed = [{"month": _MONTH[m], "mean_tmax_c": climate["months"][m]["tmax_c"]} for m in months
              if (climate["months"][m]["tmax_c"] or -99) >= crop.heat_threshold_tmax_c]
    return {"threshold_c": crop.heat_threshold_tmax_c, "stage": window["stage"], "months_checked": [_MONTH[m] for m in months],
            "exceeding_months": exceed, "source": crop.heat_threshold_source}


_CROP_PRACTICES: dict[str, dict[str, list[tuple[str, str, list[str]]]]] = {
    # category -> [(action, rationale, required evidence)] ; general agronomic practice, not site-validated.
    "rice": {
        "sustainability": [("Evaluate alternate wetting and drying (AWD) with field water tubes after crop establishment, keeping flooding around flowering.",
                            "Continuous flooding drives paddy methane emissions; AWD is an established water-saving and methane-mitigation practice where soils and water control allow it.",
                            ["field water-level tube readings with dates", "irrigation event log", "applicable methane methodology baseline"])],
        "monitoring": [("Record field water depth on a fixed schedule and every irrigation/drainage event.", "Water regime is the main activity variable for paddy methane and for verifying AWD adoption.",
                        ["water-level tube readings", "drainage event dates"])],
    },
    "wheat": {
        "sustainability": [("Retain or incorporate preceding-crop residue instead of burning, and document the method used.",
                            "Residue burning in rice-wheat systems causes air pollution and loss of soil organic matter; residue retention is a verifiable practice change.",
                            ["residue management records", "dated field photographs", "machinery or service records"])],
    },
    "cotton": {
        "monitoring": [("Install pheromone traps for bollworm monitoring from squaring onward and record weekly counts.",
                        "Trap counts give dated, auditable pest-pressure evidence and support threshold-based rather than calendar spraying.",
                        ["weekly trap counts", "trap locations", "scouting records"])],
    },
    "sugarcane": {
        "sustainability": [("Retain cane trash as mulch where pest pressure allows, rather than burning it.",
                            "Trash mulching conserves soil moisture and organic matter and avoids burning emissions.",
                            ["trash management records", "dated field photographs"])],
    },
}


def _legume_note(crop: cwp.CropWaterParameters) -> tuple[str, str, list[str]] | None:
    if crop.family != "legume":
        return None
    return ("Use crop-specific Rhizobium seed inoculation and account for biological nitrogen fixation in the nutrient plan.",
            f"{crop.display_name} is a legume; its nitrogen requirement is normally lower than a cereal's when nodulation is effective.",
            ["seed treatment/inoculant record", "nodulation check at early flowering"])


def _rec(category: str, action: str, rationale: str, priority: str, timing: str, evidence: list[str], required: list[str]) -> dict[str, Any]:
    return {"category": category, "action": action, "rationale": rationale, "priority": priority, "timing": timing,
            "requires_human_approval": True, "evidence_ids": [e for e in dict.fromkeys(evidence) if e][:20], "required_evidence": required[:30]}


def _stage_timing(cal: dict[str, Any], stage: str) -> str:
    window = next((w for w in cal["stage_windows"] if w["stage"] == stage), None)
    if not window:
        return "before field implementation"
    if "start_date" in window:
        return f"{stage.replace('_', ' ')} stage, {window['start_date']} to {window['end_date']}"
    return f"{stage.replace('_', ' ')} stage, about {window['start_month']} to {window['end_month']} (days {window['start_day']}-{window['end_day']} after planting)"


def build_dmrv_analysis(
    *, country: str, state: str | None, district: str, crop_name: str, variety: str | None = None,
    season: str | None = None, growth_stage: str | None = None, planted_at: date | None = None,
    as_of: date | None = None, areas: list[str] | None = None, measurements: dict[str, Any] | None = None,
    reference: ReferenceData | None = None, measurement_prefix: str = "uat",
    measurement_label: str = "Caller-declared synthetic UAT measurement",
) -> dict[str, Any]:
    reference = reference or load_reference()
    run = _Run(measurement_prefix, measurement_label)
    measurements = measurements or {}
    selected = [a for a in dict.fromkeys(areas or AREAS)]
    geo = _resolve_location(reference, run, country, state, district)
    crop = cwp.resolve_crop(crop_name)
    if crop is None:
        raise DmrvInputError("crop_not_supported", "This crop has no cited crop-water parameter set yet.",
                             supported_crops=cwp.supported_crops())
    crop_evidence = run.add_evidence({
        "id": f"ref:fao56:{crop.crop_id}", "type": "crop_parameters", "source": cwp.FAO56, "license": "Published reference (citation)",
        "summary": f"{crop.display_name}: Kc ini/mid/end {crop.kc_ini}/{crop.kc_mid}/{crop.kc_end}; root depth {crop.root_depth_m[0]}-{crop.root_depth_m[1]} m; p {crop.depletion_fraction_p}",
        "parameter_version": cwp.PARAMETER_VERSION,
    })
    for note in crop.notes:
        run.limit(note)
    if variety:
        run.limit(f"Variety '{variety}' recorded; FAO-56 parameters are not variety-specific, so variety did not change the calculations.")
    stage_lengths = measurements.get("stage_lengths_days")
    cal = _calendar(run, crop, geo["country"], season, planted_at, as_of, growth_stage, tuple(stage_lengths) if stage_lengths else None)
    climate = _climate(reference, run, geo)
    water = _season_water(run, crop, cal, climate) if climate else None
    soil = _soil_reference(reference, run, geo, crop)
    measured_water = _measured_soil_water(run, crop, measurements)
    soil_test = _soil_test(run, geo["country"], measurements)
    heat = _heat_risk(crop, cal, climate)
    if (measurements.get("irrigation_system") or {}).get("efficiency") is None:
        run.need("irrigation system type and application efficiency")
    run.need("field boundary or georeferenced field location (district point is regional context only)")
    run.need("dated field observations from the current season")

    clim_id = climate["evidence_id"] if climate else None
    soil_id = soil["evidence_id"] if soil else None
    geo_id = f"ref:geonames:{geo['geoname_id']}"
    recs: dict[str, list[dict[str, Any]]] = {area: [] for area in AREAS}

    # Irrigation
    if water:
        stage_calcs = [s["calc"] for s in water["stages"]]
        demand_share = (water["season_net_demand_mm"] or 0) / (water["season_etc_mm"] or 1)
        raw_text = f" Readily available water for this soil and crop is roughly {soil['raw_mm_range'][0]}-{soil['raw_mm_range'][1]} mm, so irrigation intervals should be set from measured depletion against that range." if soil and soil.get("raw_mm_range") else ""
        recs["irrigation"].append(_rec(
            "irrigation",
            f"Plan seasonal water supply for about {water['season_etc_mm']:.0f} mm of crop evapotranspiration, of which about "
            f"{water['season_effective_rainfall_mm']:.0f} mm is typically met by effective rainfall (net demand about {water['season_net_demand_mm']:.0f} mm); "
            f"peak demand is about {water['peak_etc_mm_day']} mm/day during the {str(water['peak_stage']).replace('_', ' ')} stage in {water['peak_month']}.{raw_text}",
            f"FAO-56 Penman-Monteith reference ET from {climate['period']} NASA POWER climate normals for {geo['district']}, multiplied by FAO-56 {crop.display_name} crop coefficients over the stage calendar. "
            "This is a climatological planning estimate for typical seasons, not an irrigation prescription for a specific field or year.",
            "high" if demand_share > 0.5 else ("medium" if demand_share > 0.15 else "low"),
            "season planning, before sowing",
            [clim_id, crop_evidence, *stage_calcs, *(soil.get("calcs", []) if soil else [])],
            ["measured soil moisture", "irrigation system efficiency", "dated rainfall and ET0 for the current season", "water allocation or rights"],
        ))
        sensitive = [s for s in crop.water_sensitive_stages]
        recs["irrigation"].append(_rec(
            "irrigation",
            f"Prioritise avoiding water stress during the {', '.join(s.replace('_', ' ') for s in sensitive)} stage"
            + (f" ({'; '.join(_stage_timing(cal, s) for s in sensitive)})." if cal["stage_windows"] else "."),
            f"{crop.display_name} yield is most sensitive to water deficit in these stages (FAO-56/FAO-33 crop water-stress sensitivity).",
            "high" if cal["current_stage"] in sensitive else "medium",
            _stage_timing(cal, sensitive[0]),
            [crop_evidence, clim_id], ["soil moisture readings during sensitive stages", "irrigation event log"],
        ))
    if measured_water and measured_water.get("depletion_mm") is not None:
        if measured_water.get("trigger_reached"):
            refill = f" Gross refill depth at the supplied efficiency is about {measured_water['gross_refill_mm']} mm" if measured_water.get("gross_refill_mm") else ""
            volume = f" ({measured_water['gross_refill_volume_m3']} m3 for the supplied area)" if measured_water.get("gross_refill_volume_m3") else ""
            action = (f"Irrigation trigger reached: measured root-zone depletion {measured_water['depletion_mm']} mm exceeds readily available water "
                      f"{measured_water['raw_mm']} mm. Net refill to field capacity is {measured_water['depletion_mm']} mm.{refill}{volume}.")
            priority = "high"
        else:
            action = (f"No irrigation needed yet: measured depletion {measured_water['depletion_mm']} mm is below readily available water "
                      f"{measured_water['raw_mm']} mm; re-measure before the next decision.")
            priority = "low"
        recs["irrigation"].insert(0, _rec("irrigation", action,
                                          "Computed from the supplied soil water constants and current moisture with FAO-56 depletion and p; quantities apply only to the measured field.",
                                          priority, "at next irrigation decision", [measured_water["evidence_id"], crop_evidence, *measured_water["calcs"]],
                                          ["sensor calibration record", "measurement timestamp"]))
    if not recs["irrigation"]:
        recs["irrigation"].append(_rec("irrigation", "Collect soil moisture, rainfall and ET0 evidence before setting irrigation timing or depth.",
                                       "Regional climate normals were not available for this district, so no water demand was calculated.",
                                       "medium", "before field implementation", [geo_id, crop_evidence],
                                       ["soil moisture observations", "dated rainfall and ET0", "irrigation efficiency"]))

    # Nutrients
    if soil_test:
        low = sorted(k for k, v in soil_test["ratings"].items() if v == "low")
        rated = "; ".join(f"{k.replace('_kg_ha', '').replace('_', ' ')} {v}" for k, v in sorted(soil_test["ratings"].items()))
        recs["nutrients"].append(_rec(
            "nutrients",
            (f"Base the {crop.display_name} nutrient plan on the soil test ({rated}). "
             + (f"Prioritise correcting {', '.join(k.replace('available_', '').replace('_kg_ha', '').replace('_', ' ').upper() if k.startswith('available_') else k.replace('_', ' ') for k in low)} "
                "using the state agricultural university or Soil Health Card recommendation for this crop." if low else
                "No nutrient is rated low; follow maintenance recommendations from the state agricultural university.")) if rated else
            f"Base the {crop.display_name} nutrient plan on the supplied soil test using the applicable regional recommendation.",
            f"Ratings use {cwp.SHC_SOURCE}. AGRO-AI does not set fertilizer doses; doses must come from the regional recommendation and the crop's yield target.",
            "high" if low else "medium", "before sowing / basal application",
            [soil_test["evidence_id"]], ["fertilizer product analysis", "yield target", "regional recommendation document"],
        ))
    ph_value = (soil_test or {}).get("values", {}).get("ph") if soil_test else None
    ph_cls = (soil_test or {}).get("ph_class") or (soil or {}).get("ph_class")
    ph_display = ph_value if ph_value is not None else (soil or {}).get("ph")
    if ph_cls in {"strongly_acidic", "strongly_alkaline", "moderately_alkaline", "moderately_acidic"}:
        measured = ph_value is not None
        recs["nutrients"].append(_rec(
            "nutrients",
            f"{'Measured' if measured else 'Regional (SoilGrids)'} topsoil pH is {ph_display} ({ph_cls.replace('_', ' ')}); "
            + ("assess liming need with a lime-requirement test." if "acidic" in ph_cls else
               "check phosphorus and micronutrient (especially zinc) availability" + (" and sodicity (ESP) before planning amendments." if ph_cls == "strongly_alkaline" else ".")),
            "Soil reaction controls nutrient availability; " + ("this regional estimate must be confirmed by a field soil test." if not measured else "amendment rates require laboratory tests."),
            "high" if ph_cls.startswith("strongly") else "medium", "before sowing",
            [soil_test["evidence_id"] if measured else soil_id], ["field soil pH", "lime requirement or ESP test"],
        ))
    legume = _legume_note(crop)
    if legume:
        recs["nutrients"].append(_rec("nutrients", legume[0], legume[1], "medium", "at sowing", [crop_evidence], legume[2]))
    if not soil_test:
        recs["nutrients"].append(_rec(
            "nutrients", f"Obtain a laboratory soil test (available N, P, K, organic carbon, pH, EC) for each field before planning {crop.display_name} nutrients.",
            "Fertilizer quantities cannot be determined from district labels or regional soil maps; no dose is provided.",
            "high", "before sowing", [soil_id or geo_id], ["soil test report with sampling date and method"],
        ))

    # Soil
    if soil:
        texture = soil["texture_class"]
        oc = soil["organic_carbon_pct"]
        oc_note = f" Regional topsoil organic carbon is about {oc}%" + (f" ({cwp.shc_rating('organic_carbon_pct', oc)} on the Soil Health Card scale)" if geo["country"] == "IN" and oc is not None else "") + "." if oc is not None else ""
        texture_advice = {
            "sand": "Expect low water holding: use shorter irrigation intervals with smaller depths and build organic matter.",
            "loamy sand": "Expect low water holding: use shorter irrigation intervals with smaller depths and build organic matter.",
            "sandy loam": "Moderate water holding: avoid over-irrigation and leaching losses.",
            "clay": "High water holding but slow infiltration: watch for waterlogging and plan drainage.",
            "silty clay": "High water holding but slow infiltration: watch for waterlogging and plan drainage.",
        }.get(texture or "", "Manage irrigation depth to the root zone and maintain soil cover.")
        recs["soil"].append(_rec(
            "soil",
            f"Regional topsoil texture is {texture} (sand {soil['sand_pct']}%, silt {soil['silt_pct']}%, clay {soil['clay_pct']}%). {texture_advice}{oc_note} "
            "Confirm texture and organic carbon with field sampling before relying on them.",
            "SoilGrids 250 m prediction at the district point; field soils can differ substantially within a district.",
            "medium", "before season planning", [soil_id, *soil.get("calcs", [])], ["field soil texture", "organic carbon test", "bulk density"],
        ))
    recs["soil"].append(_rec(
        "soil", "Maintain soil cover and avoid burning residues; record tillage, residue and organic input practices for each field.",
        "Management history is required evidence for soil-health and soil-carbon related DMRV claims.",
        "medium", "every season", [soil_id or geo_id], ["management history", "dated field photographs", "input records"],
    ))

    # Monitoring
    for stage in crop.water_sensitive_stages[:1]:
        recs["monitoring"].append(_rec(
            "monitoring", f"Schedule dated, georeferenced crop observations at the start and middle of the {stage.replace('_', ' ')} stage ({_stage_timing(cal, stage)}), including canopy condition and visible stress.",
            "Stage-anchored observations make yield-sensitive periods auditable and link advice to field evidence.",
            "medium", _stage_timing(cal, stage), [crop_evidence, clim_id or geo_id], ["geotagged photographs", "observation timestamps", "sampling protocol"],
        ))
    if heat and heat["exceeding_months"]:
        months = ", ".join(f"{m['month']} ({m['mean_tmax_c']} °C)" for m in heat["exceeding_months"])
        recs["monitoring"].append(_rec(
            "monitoring", f"Heat-stress risk: mean maximum temperature reaches or exceeds {heat['threshold_c']} °C during the {heat['stage'].replace('_', ' ')} stage in {months}. "
            "Track forecasts in that window and consider sowing date or variety choices that move flowering earlier.",
            heat["source"], "high", _stage_timing(cal, heat["stage"]), [clim_id, crop_evidence], ["daily maximum temperature during flowering", "variety heat tolerance"],
        ))
    elif heat:
        recs["monitoring"].append(_rec(
            "monitoring", f"Climate normals do not show mean maximum temperature reaching {heat['threshold_c']} °C in the {heat['stage'].replace('_', ' ')} stage ({', '.join(heat['months_checked'])}); monitor daily extremes, which averages hide.",
            heat["source"], "low", _stage_timing(cal, heat["stage"]), [clim_id, crop_evidence], ["daily maximum temperature records"],
        ))
    for action, rationale, required in _CROP_PRACTICES.get(crop.crop_id, {}).get("monitoring", []):
        recs["monitoring"].append(_rec("monitoring", action, rationale + " General agronomic practice; validate with local extension guidance.", "medium", "through the season", [crop_evidence], required))

    # Sustainability
    for action, rationale, required in _CROP_PRACTICES.get(crop.crop_id, {}).get("sustainability", []):
        recs["sustainability"].append(_rec("sustainability", action, rationale + " General agronomic practice; validate with local extension guidance.", "medium", "through the season", [crop_evidence], required))
    recs["sustainability"].append(_rec(
        "sustainability",
        "Establish a field-level baseline (soil organic carbon sampling, input use, water use, yield) under the applicable approved DMRV methodology before claiming any change.",
        "Regional reference data supports planning only; a recommendation does not establish verified emissions reductions, removals or carbon credits.",
        "medium", "before project start", [soil_id or geo_id], ["approved methodology", "baseline sampling records", "independent verification evidence"],
    ))

    recommendations = [r for area in selected for r in recs[area]][:20]
    grounded = bool(climate and soil)
    confidence = "medium" if grounded and cal["current_stage"] and not cal["stage_contradiction"] else "low"
    run.limit("District-level values are regional context at an administrative point; they are not field measurements.")
    run.limit("Climate values are long-term monthly means; they are not current-season weather observations or forecasts.")
    run.limit("No fertilizer dose, carbon quantity or emissions outcome has been calculated or verified.")
    used = {e for r in recommendations for e in r["evidence_ids"]}
    summary_bits = [f"{crop.display_name} in {geo['district']}, {geo['state']}"]
    if water:
        summary_bits.append(f"season crop ET about {water['season_etc_mm']:.0f} mm with net demand about {water['season_net_demand_mm']:.0f} mm after effective rain")
    if soil:
        summary_bits.append(f"regional topsoil {soil['texture_class']}, pH {soil['ph']}")
    if cal["current_stage"]:
        summary_bits.append(f"current stage {cal['current_stage'].replace('_', ' ')}")
    structured = {
        "summary": "; ".join(summary_bits) + ". Grounded in public reference data and FAO-56 calculations; confirm with field evidence.",
        "recommendations": recommendations,
        "confidence": confidence,
        "missing_data": run.missing[:30],
        "limitations": run.limitations[:30],
    }
    return {
        "engine_version": ENGINE_VERSION,
        "reference_dataset": {"version": reference.data.get("version"), "generated_at": reference.data.get("generated_at"), "sha256": reference.sha256},
        "geography": geo,
        "crop": {"crop_id": crop.crop_id, "display_name": crop.display_name, "variety": variety, "parameter_version": cwp.PARAMETER_VERSION,
                 "kc": {"initial": crop.kc_ini, "mid_season": crop.kc_mid, "late_season": crop.kc_end},
                 "root_depth_m": list(crop.root_depth_m), "depletion_fraction_p": crop.depletion_fraction_p},
        "calendar": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in cal.items()},
        "water_balance": water,
        "soil_reference": {k: v for k, v in soil.items() if k != "calcs"} if soil else None,
        "measured_soil_water": {k: v for k, v in measured_water.items() if k != "calcs"} if measured_water else None,
        "soil_test": soil_test,
        "heat_risk": heat,
        "coverage": {"location": "resolved", "climate": bool(climate), "soil": bool(soil), "stage_calendar": bool(cal["stage_windows"]),
                     "measurements": sorted(k for k in ("soil_water", "soil_test", "irrigation_system") if measurements.get(k))},
        "evidence": [e for e in run.evidence if e["id"] in used or e["id"].startswith(("ref:geonames", "ref:fao56"))],
        "calculations": run.calculations,
        "structured_output": structured,
    }
