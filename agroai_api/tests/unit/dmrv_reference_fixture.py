"""Synthetic DMRV reference data with two contrasting districts.

Values are invented test inputs shaped like the committed dataset; they are
not real climate or soil data and are used only to test engine arithmetic.
"""
from __future__ import annotations

import hashlib
import json

from app.intelligence_platform.dmrv_engine import ReferenceData

_HOT_DRY = {  # semi-arid north-west style: hot pre-monsoon, short monsoon
    "tmax": [21, 24, 30, 36, 40, 39, 34, 33, 33, 32, 28, 23], "tmin": [8, 10, 15, 21, 25, 27, 27, 26, 25, 20, 13, 9],
    "rh": [65, 58, 42, 30, 33, 50, 75, 80, 72, 58, 58, 65], "solar": [13, 16, 19, 22, 23, 21, 18, 17, 17, 16, 14, 12],
    "rain": [0.6, 0.7, 0.4, 0.3, 0.9, 2.0, 5.5, 5.0, 3.0, 0.5, 0.1, 0.2], "wind": 2.4,
}
_HUMID = {  # humid east style: milder, long wet season
    "tmax": [24, 27, 32, 35, 35, 33, 31, 31, 31, 30, 28, 25], "tmin": [11, 14, 19, 23, 25, 26, 26, 26, 25, 22, 16, 12],
    "rh": [70, 62, 52, 58, 68, 80, 86, 86, 84, 78, 72, 72], "solar": [14, 17, 19, 20, 20, 16, 14, 15, 15, 15, 15, 13],
    "rain": [0.4, 0.6, 0.6, 1.5, 4.0, 9.0, 11.0, 10.0, 8.0, 3.0, 0.3, 0.2], "wind": 1.4,
}


def _climate(profile: dict) -> dict:
    monthly = {}
    for i in range(12):
        monthly[str(i + 1)] = {
            "tmean_c": (profile["tmax"][i] + profile["tmin"][i]) / 2, "tmax_c": profile["tmax"][i], "tmin_c": profile["tmin"][i],
            "rh_mean_pct": profile["rh"][i], "wind_2m_ms": profile["wind"], "solar_mj_m2_day": profile["solar"][i],
            "precip_mm_day": profile["rain"][i],
        }
    return {"source": "NASA POWER climatology (AG community)", "period": "2001-2020",
            "grid_point": {"latitude": 28.5, "longitude": 77.5}, "elevation_m": 200, "monthly": monthly}


def _soil(sand: float, silt: float, clay: float, ph: float, soc: float) -> dict:
    props = {"sand": sand, "silt": silt, "clay": clay, "phh2o": ph, "soc": soc, "nitrogen": 0.6, "cec": 15}
    return {"source": "ISRIC SoilGrids 2.0 (250 m, mean)", "depth": "0-30 cm thickness-weighted",
            "properties": {k: {"value_0_30cm": v} for k, v in props.items()}}


DATA = {
    "dataset": "agroai-dmrv-reference", "version": "1", "generated_at": "2026-10-24T00:00:00+00:00",
    "sources": {
        "gazetteer": {"name": "GeoNames", "license": "CC BY 4.0"},
        "climate": {"name": "NASA POWER climatology", "license": "NASA open data"},
        "soil": {"name": "ISRIC SoilGrids 2.0", "license": "CC BY 4.0"},
    },
    "gazetteer": {
        "IN": {
            "states": {
                "36": {"name": "Uttar Pradesh", "ascii": "Uttar Pradesh", "alt": []},
                "34": {"name": "Bihar", "ascii": "Bihar", "alt": []},
                "16": {"name": "Maharashtra", "ascii": "Maharashtra", "alt": []},
                "24": {"name": "Rajasthan", "ascii": "Rajasthan", "alt": []},
            },
            "districts": [
                {"id": 101, "name": "Gautam Buddha Nagar", "ascii": "Gautam Buddha Nagar", "alt": [], "admin1": "36", "lat": 28.4, "lon": 77.5},
                {"id": 102, "name": "Aurangabad", "ascii": "Aurangabad", "alt": [], "admin1": "34", "lat": 24.75, "lon": 84.37},
                {"id": 103, "name": "Aurangabad", "ascii": "Aurangabad", "alt": [], "admin1": "16", "lat": 19.88, "lon": 75.34},
                {"id": 104, "name": "Bikaner", "ascii": "Bikaner", "alt": [], "admin1": "24", "lat": 28.02, "lon": 73.31},
                {"id": 105, "name": "Prayagraj", "ascii": "Prayagraj", "alt": [], "admin1": "36", "lat": 25.45, "lon": 81.85},
            ],
        },
    },
    "climate": {"101": _climate(_HOT_DRY), "102": _climate(_HUMID), "104": _climate(_HOT_DRY)},
    "soil": {
        "101": _soil(45, 35, 20, 8.1, 4.5),
        "102": _soil(20, 30, 50, 6.0, 9.0),
        "104": _soil(88, 7, 5, 8.6, 1.0),
    },
    "unresolved_targets": [],
}


def synthetic_reference() -> ReferenceData:
    raw = json.dumps(DATA, sort_keys=True).encode()
    return ReferenceData(json.loads(raw), hashlib.sha256(raw).hexdigest())
