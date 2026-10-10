"""Crop profiles: the per-crop vocabulary and parameters Crop Intelligence may use.

A profile states what can be *seen* and counted for a crop, which published
maturity scale applies, and which degree-day method is conventional. It
never supplies a variety-specific maturity target: degree days to harvest
depend on variety or hybrid, region and management, so that number must come
from the grower, the seed supplier, or a fitted calibration with provenance.

``validation_status`` is ``unvalidated`` for every profile until a detector
and a reviewed, held-out dataset exist for that crop. ``benchmark_only``
marks a crop used only as a technical benchmark, never as a launch promise.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PROFILE_VERSION = "crop-profiles/1"


@dataclass(frozen=True)
class DegreeDayMethod:
    """A conventional degree-day method; thresholds in degrees Celsius."""

    method: str
    base_c: float
    upper_cutoff_c: float | None
    source: str


@dataclass(frozen=True)
class CropProfile:
    crop_id: str
    display_name: str
    aliases: tuple[str, ...]
    detection_labels: tuple[str, ...]
    maturity_scale: str | None = None
    maturity_stages: tuple[str, ...] = ()
    degree_day_method: DegreeDayMethod | None = None
    validation_status: str = "unvalidated"
    benchmark_only: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "crop_id": self.crop_id,
            "display_name": self.display_name,
            "detection_labels": list(self.detection_labels),
            "maturity_scale": self.maturity_scale,
            "maturity_stages": list(self.maturity_stages),
            "degree_day_method": None if self.degree_day_method is None else {
                "method": self.degree_day_method.method,
                "base_c": self.degree_day_method.base_c,
                "upper_cutoff_c": self.degree_day_method.upper_cutoff_c,
                "source": self.degree_day_method.source,
            },
            "validation_status": self.validation_status,
            "benchmark_only": self.benchmark_only,
            "notes": list(self.notes),
            "profile_version": PROFILE_VERSION,
        }


_PROFILES: tuple[CropProfile, ...] = (
    CropProfile(
        crop_id="corn",
        display_name="Corn (maize)",
        aliases=("corn", "maize", "milho", "maíz", "maiz"),
        detection_labels=("plant", "ear", "tassel", "lodged_plant", "visible_damage"),
        maturity_scale="leaf-collar V/R staging",
        maturity_stages=("VE", "V(n)", "VT", "R1", "R2", "R3", "R4", "R5", "R6"),
        degree_day_method=DegreeDayMethod(
            method="modified_average_86_50",
            base_c=10.0,
            upper_cutoff_c=30.0,
            source="Conventional 86/50 °F corn growing degree day method (Tmax capped at 30 °C, Tmin raised to 10 °C).",
        ),
        notes=("Degree days to black layer (R6) are hybrid-specific and must be supplied.",),
    ),
    CropProfile(
        crop_id="almond",
        display_name="Almond",
        aliases=("almond", "almonds", "amêndoa", "amendoa", "almendra"),
        detection_labels=("nut", "nut_hull_split", "blossom", "visible_damage"),
        maturity_scale="visible hull split",
        maturity_stages=("hull_intact", "hull_split", "hull_open_dry"),
        notes=("Hull-split timing is variety-specific; no degree-day default is supplied.",),
    ),
    CropProfile(
        crop_id="wine_grape",
        display_name="Wine grape",
        aliases=("grape", "grapes", "wine grape", "wine grapes", "vineyard", "uva", "uvas", "videira"),
        detection_labels=("cluster", "berry", "damaged_cluster", "visible_damage"),
        maturity_scale="visible veraison (E-L system context)",
        maturity_stages=("pre_veraison", "veraison", "post_veraison"),
        notes=(
            "Sugar, acid and harvest readiness require sampling or refractometry; imagery only shows color change.",
        ),
    ),
    CropProfile(
        crop_id="coffee",
        display_name="Coffee (arabica/robusta)",
        aliases=("coffee", "café", "cafe", "cafeeiro"),
        detection_labels=("cherry", "visible_damage"),
        maturity_scale="cherry ripeness classes used in Brazilian harvest assessment",
        maturity_stages=("green", "yellow_green", "ripe_cherry", "overripe_raisin", "dry"),
        notes=("Ripeness shares from visible cherries describe the sampled branches, not the whole plot.",),
    ),
    CropProfile(
        crop_id="tomato",
        display_name="Tomato",
        aliases=("tomato", "tomatoes", "tomate", "tomates"),
        detection_labels=("fruit", "flower_cluster", "damaged_fruit", "visible_damage"),
        maturity_scale="USDA fresh tomato color classification",
        maturity_stages=("green", "breakers", "turning", "pink", "light_red", "red"),
        benchmark_only=True,
        notes=("Technical benchmark only; not a commercial launch commitment.",),
    ),
)

_BY_ID = {profile.crop_id: profile for profile in _PROFILES}


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", folded.casefold().strip())


_ALIASES = {_normalize(alias): profile for profile in _PROFILES for alias in (profile.crop_id, *profile.aliases)}


def all_profiles() -> tuple[CropProfile, ...]:
    return _PROFILES


def get_profile(crop_id: str) -> CropProfile | None:
    return _BY_ID.get(crop_id)


def resolve_profile(crop: str | None) -> CropProfile | None:
    """Resolve free-text crop names ("Almonds", "milho") to a profile."""
    if not crop:
        return None
    normalized = _normalize(str(crop))
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    singular = normalized[:-1] if normalized.endswith("s") else normalized
    return _ALIASES.get(singular)
