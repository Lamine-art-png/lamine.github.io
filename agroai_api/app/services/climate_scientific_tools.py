"""Reference evapotranspiration and effective rainfall tools.

Registered in the existing fail-closed scientific tool registry. Every input is
explicit; nothing is filled from a location or crop label. Equations and
constants are FAO Irrigation and Drainage Paper 56 (Allen et al., 1998) and the
USDA Soil Conservation Service monthly effective-rainfall method as implemented
in FAO CROPWAT.
"""
from __future__ import annotations

import math
from typing import Any, Callable

_FAO56 = [{"authority": "FAO", "reference": "Allen et al. (1998) Crop evapotranspiration, FAO Irrigation and Drainage Paper 56, eqs. 6-44"}]
_USDA_SCS = [{"authority": "FAO", "reference": "FAO CROPWAT effective rainfall, USDA Soil Conservation Service monthly method"}]
SOLAR_CONSTANT = 0.0820  # MJ m-2 min-1
STEFAN_BOLTZMANN = 4.903e-9  # MJ K-4 m-2 day-1


def _value(inputs: dict[str, Any], name: str, low: float, high: float) -> float:
    value = inputs.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name)
    number = float(value)
    if not math.isfinite(number) or number < low or number > high:
        raise ValueError(name)
    return number


def _optional(inputs: dict[str, Any], name: str, low: float, high: float) -> float | None:
    return None if inputs.get(name) is None else _value(inputs, name, low, high)


def saturation_vapour_pressure(temperature_c: float) -> float:
    """FAO-56 eq. 11 (kPa)."""
    return 0.6108 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))


def extraterrestrial_radiation(latitude_deg: float, day_of_year: int) -> float:
    """FAO-56 eqs. 21-25 (MJ m-2 day-1)."""
    phi = math.radians(latitude_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    omega = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    return 24 * 60 / math.pi * SOLAR_CONSTANT * dr * (
        omega * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(omega)
    )


def _et0_monthly(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    tmax = _value(inputs, "tmax_c", -60, 60)
    tmin = _value(inputs, "tmin_c", -70, 50)
    if tmin > tmax:
        raise ValueError("tmin_c_exceeds_tmax_c")
    rs = _value(inputs, "solar_radiation_mj_m2_day", 0, 45)
    u2 = _value(inputs, "wind_speed_2m_ms", 0, 30)
    latitude = _value(inputs, "latitude_deg", -66, 66)
    elevation = _value(inputs, "elevation_m", -500, 6000)
    month = int(_value(inputs, "month", 1, 12))
    day_of_year = int(_optional(inputs, "day_of_year", 1, 366) or int(30.4 * month - 15))  # eq. 25 note
    rh_mean = _optional(inputs, "rh_mean_pct", 0, 100)
    ea_supplied = _optional(inputs, "actual_vapour_pressure_kpa", 0, 10)
    if rh_mean is None and ea_supplied is None:
        raise ValueError("rh_mean_pct_or_actual_vapour_pressure_kpa_required")
    t_prev = _optional(inputs, "tmean_previous_month_c", -60, 60)
    t_next = _optional(inputs, "tmean_next_month_c", -60, 60)

    tmean = (tmax + tmin) / 2
    pressure = 101.3 * ((293 - 0.0065 * elevation) / 293) ** 5.26  # eq. 7
    gamma = 0.000665 * pressure  # eq. 8
    es = (saturation_vapour_pressure(tmax) + saturation_vapour_pressure(tmin)) / 2  # eq. 12
    ea = ea_supplied if ea_supplied is not None else rh_mean / 100 * es  # eq. 19
    delta = 4098 * saturation_vapour_pressure(tmean) / (tmean + 237.3) ** 2  # eq. 13
    ra = extraterrestrial_radiation(latitude, day_of_year)
    rso = (0.75 + 2e-5 * elevation) * ra  # eq. 37
    rns = 0.77 * rs  # eq. 38, albedo 0.23
    ratio = min(rs / rso, 1.0) if rso > 0 else 1.0
    rnl = STEFAN_BOLTZMANN * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * math.sqrt(ea)) * (1.35 * ratio - 0.35)  # eq. 39
    rn = rns - rnl
    if t_prev is not None and t_next is not None:
        soil_heat = 0.07 * (t_next - t_prev)  # eq. 43
        g_method = "eq43"
    elif t_prev is not None:
        soil_heat = 0.14 * (tmean - t_prev)  # eq. 44
        g_method = "eq44"
    else:
        soil_heat = 0.0
        g_method = "assumed_zero"
    et0 = (0.408 * delta * (rn - soil_heat) + gamma * 900 / (tmean + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))  # eq. 6
    output = {
        "et0_mm_day": round(max(et0, 0.0), 3),
        "net_radiation_mj_m2_day": round(rn, 3),
        "soil_heat_flux_mj_m2_day": round(soil_heat, 3),
        "vapour_pressure_deficit_kpa": round(es - ea, 3),
        "extraterrestrial_radiation_mj_m2_day": round(ra, 3),
        "soil_heat_flux_method": g_method,
    }
    normalized = {
        "tmax_c": tmax, "tmin_c": tmin, "solar_radiation_mj_m2_day": rs, "wind_speed_2m_ms": u2,
        "latitude_deg": latitude, "elevation_m": elevation, "month": month, "day_of_year": day_of_year,
        "rh_mean_pct": rh_mean, "actual_vapour_pressure_kpa": ea_supplied,
    }
    return output, normalized


def _effective_rainfall(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    total = _value(inputs, "monthly_precipitation_mm", 0, 5000)
    effective = total * (125 - 0.2 * total) / 125 if total < 250 else 125 + 0.1 * total
    return {"effective_rainfall_mm": round(effective, 3)}, {"monthly_precipitation_mm": total}


def register_climate_tools(register: Callable[..., None]) -> None:
    register(
        tool_id="fao56.et0.penman_monteith_monthly.v1", domain="crop_water",
        description="Compute monthly-mean daily reference evapotranspiration (FAO-56 Penman-Monteith) from explicit monthly climate values.",
        required_inputs=["tmax_c", "tmin_c", "solar_radiation_mj_m2_day", "wind_speed_2m_ms", "latitude_deg", "elevation_m", "month"],
        optional_inputs=["rh_mean_pct", "actual_vapour_pressure_kpa", "tmean_previous_month_c", "tmean_next_month_c", "day_of_year"],
        expected_units={"tmax_c": "degC", "tmin_c": "degC", "solar_radiation_mj_m2_day": "MJ m-2 day-1", "wind_speed_2m_ms": "m/s at 2 m",
                        "latitude_deg": "decimal degrees", "elevation_m": "m", "rh_mean_pct": "%", "actual_vapour_pressure_kpa": "kPa"},
        valid_ranges={"latitude_deg": "-66..66 (sunset hour angle defined)", "month": "1..12", "rh_mean_pct": "0..100; one of rh_mean_pct or actual_vapour_pressure_kpa"},
        output_schema={"et0_mm_day": "number", "net_radiation_mj_m2_day": "number", "soil_heat_flux_mj_m2_day": "number", "vapour_pressure_deficit_kpa": "number"},
        calculation_method="FAO-56 eq. 6 with eqs. 7-8, 11-13, 19, 21-25, 37-40; monthly soil heat flux eq. 43/44; mid-month day of year J = INT(30.4M - 15).",
        runner=_et0_monthly,
        assumptions=["Grass reference surface (albedo 0.23).", "Inputs are monthly means for the same location."],
        limitations=["Actual vapour pressure from mean relative humidity (eq. 19) is less accurate than from dewpoint or RHmax/RHmin.",
                     "Climatological means describe a typical month, not a specific season or day."],
        provenance=_FAO56,
    )
    register(
        tool_id="water.effective_rainfall.usda_scs_monthly.v1", domain="water_balance",
        description="Estimate monthly effective rainfall from explicit total monthly precipitation (USDA SCS method).",
        required_inputs=["monthly_precipitation_mm"], expected_units={"monthly_precipitation_mm": "mm per month"},
        valid_ranges={"monthly_precipitation_mm": ">= 0"}, output_schema={"effective_rainfall_mm": "number"},
        calculation_method="Peff = P(125 - 0.2P)/125 for P < 250 mm; Peff = 125 + 0.1P for P >= 250 mm",
        runner=_effective_rainfall,
        limitations=["Empirical monthly method; ignores soil infiltration, slope, intensity and paddy bunding."],
        provenance=_USDA_SCS,
    )
