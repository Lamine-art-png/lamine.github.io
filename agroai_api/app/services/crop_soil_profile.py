"""Crop-soil profile — per-crop, per-soil agronomic thresholds.

Replaces hardcoded constants in WaterStateEngine with configurable
profiles. Falls back to sensible defaults for unknown combinations.

No database dependency — pure lookup. Profiles can be extended
from a database table later without changing the interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class CropSoilProfile:
    """Agronomic thresholds for a crop + soil combination."""
    crop_type: str
    soil_type: str
    field_capacity: float       # VWC at field capacity
    wilting_point: float        # Permanent wilting point VWC
    stress_threshold: float     # VWC below which crop stress begins
    saturation: float           # VWC at full saturation
    root_depth_mm: float        # Effective root zone depth
    mad: float                  # Management allowable depletion (0-1)
    kc: float                   # Crop coefficient (mid-season)


# Built-in profiles: (crop_type, soil_type) → CropSoilProfile
# Sources: FAO 56, USDA soil surveys, standard agronomy references
_PROFILES: Dict[Tuple[str, str], CropSoilProfile] = {}


def _register(crop: str, soil: str, fc: float, wp: float, stress: float,
              sat: float, root: float, mad: float, kc: float):
    _PROFILES[(crop.lower(), soil.lower())] = CropSoilProfile(
        crop_type=crop.lower(), soil_type=soil.lower(),
        field_capacity=fc, wilting_point=wp, stress_threshold=stress,
        saturation=sat, root_depth_mm=root, mad=mad, kc=kc,
    )


# Corn
_register("corn", "loam",       0.36, 0.12, 0.20, 0.45, 800, 0.55, 1.15)
_register("corn", "clay",       0.40, 0.18, 0.25, 0.50, 800, 0.55, 1.15)
_register("corn", "sandy_loam", 0.28, 0.08, 0.14, 0.40, 700, 0.50, 1.15)
_register("corn", "sand",       0.20, 0.05, 0.10, 0.35, 600, 0.45, 1.15)

# Wheat
_register("wheat", "loam",       0.36, 0.12, 0.18, 0.45, 600, 0.60, 1.10)
_register("wheat", "clay",       0.40, 0.18, 0.24, 0.50, 600, 0.60, 1.10)
_register("wheat", "sandy_loam", 0.28, 0.08, 0.14, 0.40, 500, 0.55, 1.10)

# Vegetables (general)
_register("vegetables", "loam",       0.36, 0.12, 0.22, 0.45, 400, 0.40, 1.00)
_register("vegetables", "clay",       0.40, 0.18, 0.27, 0.50, 400, 0.40, 1.00)
_register("vegetables", "sandy_loam", 0.28, 0.08, 0.16, 0.40, 350, 0.35, 1.00)

# Trees / orchards
_register("trees", "loam",       0.36, 0.12, 0.18, 0.45, 1000, 0.65, 0.95)
_register("trees", "clay",       0.40, 0.18, 0.24, 0.50, 1000, 0.65, 0.95)
_register("trees", "sandy_loam", 0.28, 0.08, 0.14, 0.40, 900, 0.60, 0.95)

# Vineyard
_register("vineyard", "loam",       0.34, 0.12, 0.18, 0.44, 800, 0.55, 0.70)
_register("vineyard", "clay",       0.38, 0.18, 0.24, 0.48, 800, 0.55, 0.70)
_register("vineyard", "sandy_loam", 0.26, 0.08, 0.14, 0.38, 700, 0.50, 0.70)

# Almonds
_register("almonds", "loam",       0.34, 0.12, 0.18, 0.44, 900, 0.60, 0.90)
_register("almonds", "clay",       0.38, 0.18, 0.24, 0.48, 900, 0.60, 0.90)
_register("almonds", "sandy_loam", 0.26, 0.08, 0.14, 0.38, 800, 0.55, 0.90)

# Default
DEFAULT_PROFILE = CropSoilProfile(
    crop_type="default", soil_type="default",
    field_capacity=0.36, wilting_point=0.12,
    stress_threshold=0.20, saturation=0.45,
    root_depth_mm=600, mad=0.50, kc=1.00,
)


def get_profile(crop_type: Optional[str], soil_type: Optional[str]) -> CropSoilProfile:
    """Look up profile for crop+soil combination. Falls back gracefully."""
    if crop_type and soil_type:
        key = (crop_type.lower(), soil_type.lower())
        if key in _PROFILES:
            return _PROFILES[key]

    # Try crop with default soil
    if crop_type:
        for (c, s), profile in _PROFILES.items():
            if c == crop_type.lower():
                return profile

    # Try soil with default crop
    if soil_type:
        for (c, s), profile in _PROFILES.items():
            if s == soil_type.lower():
                return profile

    return DEFAULT_PROFILE


def list_profiles() -> list:
    """Return all available profiles for API exposure."""
    return [
        {
            "crop_type": p.crop_type,
            "soil_type": p.soil_type,
            "field_capacity": p.field_capacity,
            "wilting_point": p.wilting_point,
            "stress_threshold": p.stress_threshold,
            "saturation": p.saturation,
            "root_depth_mm": p.root_depth_mm,
            "mad": p.mad,
            "kc": p.kc,
        }
        for p in _PROFILES.values()
    ]
