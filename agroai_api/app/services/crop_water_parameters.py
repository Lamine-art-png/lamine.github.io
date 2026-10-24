"""Published crop-water and soil reference parameters for advisory grounding.

Every value is a tabulated reference with its citation; none is a
site-calibrated parameter. Consumers must disclose that FAO-56 tabulated
values describe standard conditions (sub-humid climate, RHmin ~45 %,
u2 ~2 m/s, non-stressed, well-managed crops) and that stage lengths are a
representative regional entry, not a variety calendar.

Kept separate from ``crop_profiles`` (imagery/maturity vocabulary) and
``crop_soil_profile`` (water-state engine thresholds): this module is the
cited FAO-56 staged parameter table those modules do not contain.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PARAMETER_VERSION = "crop-water-parameters/1"
FAO56 = "Allen et al. (1998) FAO Irrigation and Drainage Paper 56"
STAGES = ("initial", "development", "mid_season", "late_season")


@dataclass(frozen=True)
class CropWaterParameters:
    crop_id: str
    display_name: str
    aliases: tuple[str, ...]
    family: str
    kc_ini: float
    kc_mid: float
    kc_end: float
    root_depth_m: tuple[float, float]
    depletion_fraction_p: float
    stage_lengths_days: tuple[int, int, int, int] | None
    stage_lengths_source: str | None
    water_sensitive_stages: tuple[str, ...]
    heat_threshold_tmax_c: float | None = None
    heat_threshold_stage: str | None = None
    heat_threshold_source: str | None = None
    typical_seasons: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    p_relative_to_saturation: bool = False  # FAO-56 Table 22 paddy convention

    @property
    def season_length_days(self) -> int | None:
        return sum(self.stage_lengths_days) if self.stage_lengths_days else None


_T12 = f"{FAO56}, Table 12 (single crop coefficients)"
_T22 = f"{FAO56}, Table 22 (rooting depth and depletion fraction p)"

CROPS: tuple[CropWaterParameters, ...] = (
    CropWaterParameters(
        crop_id="wheat", display_name="Wheat (spring)", aliases=("wheat", "spring wheat", "gehun", "gehu"), family="cereal",
        kc_ini=0.30, kc_mid=1.15, kc_end=0.25, root_depth_m=(1.5, 1.8), depletion_fraction_p=0.55,
        stage_lengths_days=(20, 25, 60, 30), stage_lengths_source=f"{FAO56}, Table 11: spring wheat, November planting, Central India",
        water_sensitive_stages=("mid_season",), heat_threshold_tmax_c=32.0, heat_threshold_stage="mid_season",
        heat_threshold_source="Indicative terminal-heat threshold for wheat anthesis and grain filling (Porter & Gawith 1999 review); variety tolerance differs.",
        typical_seasons={"IN": ("rabi",), "BD": ("rabi",)},
        notes=("Kc end 0.25 assumes harvest at dry maturity (FAO-56 range 0.25-0.40).",),
    ),
    CropWaterParameters(
        crop_id="rice", display_name="Rice (paddy)", aliases=("rice", "paddy", "dhan", "chawal", "aman", "boro", "aus"), family="cereal",
        kc_ini=1.05, kc_mid=1.20, kc_end=0.75, root_depth_m=(0.5, 1.0), depletion_fraction_p=0.20,
        stage_lengths_days=(30, 30, 60, 30), stage_lengths_source=f"{FAO56}, Table 11: rice, tropics (150 days)",
        water_sensitive_stages=("mid_season",), heat_threshold_tmax_c=35.0, heat_threshold_stage="mid_season",
        heat_threshold_source="Indicative spikelet-sterility threshold at anthesis (Jagadish et al. 2007); variety tolerance differs.",
        typical_seasons={"IN": ("kharif", "rabi"), "BD": ("aman", "boro", "aus")},
        notes=("Kc end shown is the mid-point of the FAO-56 range 0.90-0.60.",
               "Crop ET excludes land preparation, puddling, standing-water and percolation losses.",
               "Depletion fraction p is relative to saturation for paddy."),
        p_relative_to_saturation=True,
    ),
    CropWaterParameters(
        crop_id="maize", display_name="Maize (grain)", aliases=("maize", "corn", "makka", "makki", "bhutta"), family="cereal",
        kc_ini=0.30, kc_mid=1.20, kc_end=0.35, root_depth_m=(1.0, 1.7), depletion_fraction_p=0.55,
        stage_lengths_days=(20, 35, 40, 30), stage_lengths_source=f"{FAO56}, Table 11: grain maize, October planting, India (dry, cool)",
        water_sensitive_stages=("mid_season",), heat_threshold_tmax_c=35.0, heat_threshold_stage="mid_season",
        heat_threshold_source="Indicative pollen-viability threshold at silking/tasseling; hybrid tolerance differs.",
        typical_seasons={"IN": ("kharif", "rabi"), "BD": ("rabi",)},
        notes=("Kc end 0.35 assumes harvest of dry grain (FAO-56 range 0.60-0.35).",),
    ),
    CropWaterParameters(
        crop_id="cotton", display_name="Cotton", aliases=("cotton", "kapas", "narma"), family="fibre",
        kc_ini=0.35, kc_mid=1.18, kc_end=0.60, root_depth_m=(1.0, 1.7), depletion_fraction_p=0.65,
        stage_lengths_days=(30, 50, 60, 55), stage_lengths_source=f"{FAO56}, Table 11: cotton, March-May planting, Egypt/Pakistan/California",
        water_sensitive_stages=("mid_season",), typical_seasons={"IN": ("kharif",)},
        notes=("Kc mid and end are mid-points of FAO-56 ranges 1.15-1.20 and 0.70-0.50.",),
    ),
    CropWaterParameters(
        crop_id="sugarcane", display_name="Sugarcane (plant crop)", aliases=("sugarcane", "sugar cane", "ganna", "ikh"), family="perennial_grass",
        kc_ini=0.40, kc_mid=1.25, kc_end=0.75, root_depth_m=(1.2, 2.0), depletion_fraction_p=0.65,
        stage_lengths_days=(35, 60, 190, 120), stage_lengths_source=f"{FAO56}, Table 11: virgin sugarcane, low latitudes (405 days)",
        water_sensitive_stages=("development", "mid_season"), typical_seasons={"IN": ("spring", "autumn")},
        notes=("Ratoon crops follow a different FAO-56 stage table; supply stage lengths for ratoons.",),
    ),
    CropWaterParameters(
        crop_id="soybean", display_name="Soybean", aliases=("soybean", "soybeans", "soya", "soyabean", "soya bean"), family="legume",
        kc_ini=0.40, kc_mid=1.15, kc_end=0.50, root_depth_m=(0.6, 1.3), depletion_fraction_p=0.50,
        stage_lengths_days=(15, 15, 40, 15), stage_lengths_source=f"{FAO56}, Table 11: soybean, tropics (85 days); Indian cultivars are often longer",
        water_sensitive_stages=("mid_season",), typical_seasons={"IN": ("kharif",)},
    ),
    CropWaterParameters(
        crop_id="chickpea", display_name="Chickpea", aliases=("chickpea", "chick pea", "gram", "bengal gram", "chana"), family="legume",
        kc_ini=0.40, kc_mid=1.00, kc_end=0.35, root_depth_m=(0.6, 1.0), depletion_fraction_p=0.50,
        stage_lengths_days=None, stage_lengths_source=None,
        water_sensitive_stages=("mid_season",), heat_threshold_tmax_c=35.0, heat_threshold_stage="mid_season",
        heat_threshold_source="Indicative flowering/pod-set heat threshold (Devasirvatham et al. 2012); cultivar tolerance differs.",
        typical_seasons={"IN": ("rabi",)},
        notes=("No FAO-56 Table 11 stage lengths are used for chickpea; supply stage lengths to compute a seasonal schedule.",),
    ),
    CropWaterParameters(
        crop_id="potato", display_name="Potato", aliases=("potato", "potatoes", "aloo", "alu"), family="tuber",
        kc_ini=0.50, kc_mid=1.15, kc_end=0.75, root_depth_m=(0.4, 0.6), depletion_fraction_p=0.35,
        stage_lengths_days=(25, 30, 45, 30), stage_lengths_source=f"{FAO56}, Table 11: potato, Jan/Nov planting, (semi-)arid climate",
        water_sensitive_stages=("development", "mid_season"), typical_seasons={"IN": ("rabi",), "BD": ("rabi",)},
    ),
    CropWaterParameters(
        crop_id="tomato", display_name="Tomato", aliases=("tomato", "tomatoes", "tamatar"), family="vegetable",
        kc_ini=0.60, kc_mid=1.15, kc_end=0.80, root_depth_m=(0.7, 1.5), depletion_fraction_p=0.40,
        stage_lengths_days=(30, 40, 40, 25), stage_lengths_source=f"{FAO56}, Table 11: tomato, January planting, arid region",
        water_sensitive_stages=("mid_season",), heat_threshold_tmax_c=32.0, heat_threshold_stage="mid_season",
        heat_threshold_source="Indicative fruit-set threshold for day temperature; cultivar tolerance differs.",
        notes=("Kc end shown is the mid-point of the FAO-56 range 0.70-0.90.",),
    ),
)

# Typical planting month for named seasons. Used only when no planting date
# is supplied, and always disclosed as an assumption.
SEASON_PLANTING_MONTH: dict[str, dict[str, int]] = {
    "IN": {"kharif": 6, "rabi": 11, "zaid": 3, "spring": 2, "autumn": 10},
    "BD": {"aus": 4, "aman": 7, "boro": 1, "rabi": 11, "kharif": 6},
}

_STAGE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("late_season", ("maturity", "mature", "ripening", "senescence", "harvest", "dough", "late")),
    ("mid_season", ("flower", "anthesis", "heading", "booting", "panicle", "reproductive", "silking", "tassel",
                    "pod", "boll", "grain fill", "fruit", "yield formation", "grand growth", "bulking", "mid")),
    ("initial", ("sowing", "seeding", "germination", "emergence", "seedling", "establishment", "transplant", "nursery", "initial")),
    ("development", ("vegetative", "tillering", "jointing", "development", "branching", "elongation", "squaring",
                     "crown root", "tuber initiation", "knee")),
)


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", folded.casefold())).strip()


_ALIASES = {_normalize(alias): crop for crop in CROPS for alias in (crop.crop_id, *crop.aliases)}


def resolve_crop(name: str | None) -> CropWaterParameters | None:
    if not name:
        return None
    normalized = _normalize(name)
    return _ALIASES.get(normalized) or _ALIASES.get(normalized.removesuffix("s"))


def supported_crops() -> list[str]:
    return [crop.crop_id for crop in CROPS]


def stage_from_label(label: str | None) -> str | None:
    if not label:
        return None
    normalized = _normalize(label)
    for stage, words in _STAGE_KEYWORDS:
        if any(word in normalized for word in words):
            return stage
    return None


def kc_for_day(crop: CropWaterParameters, day: int, lengths: tuple[int, int, int, int]) -> tuple[str, float]:
    """FAO-56 Kc curve (Fig. 34, eq. 66): constant, linear rise, constant, linear decline."""
    ini, dev, mid, late = lengths
    if day < ini:
        return "initial", crop.kc_ini
    if day < ini + dev:
        return "development", crop.kc_ini + (day - ini + 1) / dev * (crop.kc_mid - crop.kc_ini)
    if day < ini + dev + mid:
        return "mid_season", crop.kc_mid
    position = min(day - ini - dev - mid + 1, late)
    return "late_season", crop.kc_mid + position / late * (crop.kc_end - crop.kc_mid)


# FAO-56 Table 19: typical soil water characteristics by texture (m3/m3).
TEXTURE_WATER: dict[str, dict[str, tuple[float, float]]] = {
    "sand": {"fc": (0.07, 0.17), "wp": (0.02, 0.07), "taw": (0.05, 0.11)},
    "loamy sand": {"fc": (0.11, 0.19), "wp": (0.03, 0.10), "taw": (0.06, 0.12)},
    "sandy loam": {"fc": (0.18, 0.28), "wp": (0.06, 0.16), "taw": (0.11, 0.15)},
    "loam": {"fc": (0.20, 0.30), "wp": (0.07, 0.17), "taw": (0.13, 0.18)},
    "silt loam": {"fc": (0.22, 0.36), "wp": (0.09, 0.21), "taw": (0.13, 0.19)},
    "silt": {"fc": (0.28, 0.36), "wp": (0.12, 0.22), "taw": (0.16, 0.20)},
    "silty clay loam": {"fc": (0.30, 0.37), "wp": (0.17, 0.24), "taw": (0.13, 0.18)},
    "silty clay": {"fc": (0.30, 0.42), "wp": (0.17, 0.29), "taw": (0.13, 0.19)},
    "clay": {"fc": (0.32, 0.40), "wp": (0.20, 0.24), "taw": (0.12, 0.20)},
}
TEXTURE_SOURCE = f"{FAO56}, Table 19 (typical soil water characteristics)"


def usda_texture_class(sand_pct: float, silt_pct: float, clay_pct: float) -> str:
    """USDA soil texture triangle (NRCS Soil Survey Manual)."""
    sand, silt, clay = sand_pct, silt_pct, clay_pct
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 2 * clay < 30:
        return "loamy sand"
    if (7 <= clay < 20 and sand > 52) or (clay < 7 and silt < 50):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if silt >= 50 and clay < 27:
        return "silt loam"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if 27 <= clay < 40:
        return "clay loam"
    if clay >= 40 and silt >= 40:
        return "silty clay"
    return "clay"


# Soil Health Card rating classes (Government of India, Soil Health Card
# scheme; ICAR methods: alkaline KMnO4 N, Olsen P, NH4OAc K, Walkley-Black OC).
SHC_SOURCE = "Government of India Soil Health Card scheme rating classes (ICAR standard methods)"
SHC_THRESHOLDS: dict[str, tuple[float, float, str]] = {
    "available_n_kg_ha": (280.0, 560.0, "kg/ha"),
    "available_p_kg_ha": (10.0, 25.0, "kg/ha"),
    "available_k_kg_ha": (108.0, 280.0, "kg/ha"),
    "organic_carbon_pct": (0.5, 0.75, "%"),
}


def shc_rating(parameter: str, value: float) -> str:
    low, high, _unit = SHC_THRESHOLDS[parameter]
    if value < low:
        return "low"
    return "medium" if value <= high else "high"


def ph_class(ph: float) -> str:
    if ph < 5.5:
        return "strongly_acidic"
    if ph < 6.5:
        return "moderately_acidic"
    if ph <= 7.5:
        return "neutral"
    if ph <= 8.5:
        return "moderately_alkaline"
    return "strongly_alkaline"
