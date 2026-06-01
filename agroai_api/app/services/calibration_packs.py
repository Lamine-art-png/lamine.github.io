from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal


CALIBRATION_PACK_VERSION = "agroai_calibration_pack_v0.2"

CalibrationStatus = Literal[
    "calibrated_context",
    "partial_calibration",
    "assumptions_required",
    "insufficient_context",
]


@dataclass(frozen=True)
class CropCalibration:
    label: str
    crop_coefficient: float
    root_zone_depth_mm: float
    management_allowable_depletion: float


@dataclass(frozen=True)
class SoilCalibration:
    label: str
    available_water_mm_per_m: float


@dataclass(frozen=True)
class IrrigationCalibration:
    label: str
    efficiency: float


CROPS: Dict[str, CropCalibration] = {
    "wine grapes": CropCalibration("wine grapes", crop_coefficient=0.72, root_zone_depth_mm=600, management_allowable_depletion=0.45),
    "almonds": CropCalibration("almonds", crop_coefficient=1.05, root_zone_depth_mm=900, management_allowable_depletion=0.50),
    "citrus": CropCalibration("citrus", crop_coefficient=0.85, root_zone_depth_mm=700, management_allowable_depletion=0.45),
    "vegetables": CropCalibration("vegetables", crop_coefficient=0.95, root_zone_depth_mm=450, management_allowable_depletion=0.35),
    "generic specialty crop": CropCalibration("generic specialty crop", crop_coefficient=0.82, root_zone_depth_mm=550, management_allowable_depletion=0.40),
}

SOILS: Dict[str, SoilCalibration] = {
    "sand": SoilCalibration("sand", available_water_mm_per_m=80),
    "loam": SoilCalibration("loam", available_water_mm_per_m=150),
    "clay loam": SoilCalibration("clay loam", available_water_mm_per_m=170),
    "clay": SoilCalibration("clay", available_water_mm_per_m=190),
    "unknown": SoilCalibration("unknown", available_water_mm_per_m=135),
}

IRRIGATION_METHODS: Dict[str, IrrigationCalibration] = {
    "drip": IrrigationCalibration("drip", efficiency=0.90),
    "micro-sprinkler": IrrigationCalibration("micro-sprinkler", efficiency=0.82),
    "sprinkler": IrrigationCalibration("sprinkler", efficiency=0.75),
    "flood": IrrigationCalibration("flood", efficiency=0.60),
    "unknown": IrrigationCalibration("unknown", efficiency=0.70),
}

SOIL_ALIASES = {
    "sandy loam": "loam",
    "silt loam": "loam",
    "silty clay loam": "clay loam",
}

METHOD_ALIASES = {
    "micro": "micro-sprinkler",
    "microsprinkler": "micro-sprinkler",
    "micro sprinkler": "micro-sprinkler",
}


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def crop_defaults(crop_type: Any) -> tuple[CropCalibration, list[str], bool]:
    key = _clean(crop_type)
    found = key in CROPS
    if not found:
        key = "generic specialty crop"
    return CROPS[key], ([] if found else ["crop_type assumed as generic specialty crop"]), found


def soil_defaults(soil_type: Any) -> tuple[SoilCalibration, list[str], bool]:
    key = SOIL_ALIASES.get(_clean(soil_type), _clean(soil_type))
    found = key in SOILS and key != "unknown"
    if key not in SOILS:
        key = "unknown"
    return SOILS[key], ([] if found else ["soil_type assumed as unknown"]), found


def irrigation_defaults(method: Any) -> tuple[IrrigationCalibration, list[str], bool]:
    key = METHOD_ALIASES.get(_clean(method), _clean(method))
    found = key in IRRIGATION_METHODS and key != "unknown"
    if key not in IRRIGATION_METHODS:
        key = "unknown"
    return IRRIGATION_METHODS[key], ([] if found else ["irrigation_method assumed as unknown"]), found


def resolve_calibration(crop_type: Any, soil_type: Any, irrigation_method: Any, has_weather: bool) -> Dict[str, Any]:
    crop, crop_assumptions, crop_known = crop_defaults(crop_type)
    soil, soil_assumptions, soil_known = soil_defaults(soil_type)
    method, method_assumptions, method_known = irrigation_defaults(irrigation_method)
    assumptions = crop_assumptions + soil_assumptions + method_assumptions

    known = sum([crop_known, soil_known, method_known, has_weather])
    if known == 4:
        status: CalibrationStatus = "calibrated_context"
    elif known >= 2:
        status = "partial_calibration"
    elif known >= 1:
        status = "assumptions_required"
    else:
        status = "insufficient_context"

    return {
        "version": CALIBRATION_PACK_VERSION,
        "status": status,
        "crop": crop,
        "soil": soil,
        "irrigation": method,
        "assumptions_used": assumptions,
        "known_inputs": {
            "crop_type": crop_known,
            "soil_type": soil_known,
            "irrigation_method": method_known,
            "weather_context": has_weather,
        },
    }
