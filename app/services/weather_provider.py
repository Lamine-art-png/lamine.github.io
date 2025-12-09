import os
import time
from typing import Dict, Any, List, Tuple
import math
import random

import httpx

OPENWEATHER_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OPENWEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall"

# Very light in-memory cache to avoid hammering APIs
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SEC = 600  # 10 minutes


def _cache_get(key: str):
    if key not in _CACHE:
        return None
    ts, val = _CACHE[key]
    if time.time() - ts > CACHE_TTL_SEC:
        _CACHE.pop(key, None)
        return None
    return val

def _cache_set(key: str, val: Dict[str, Any]):
    _CACHE[key] = (time.time(), val)


async def fetch_openweather(lat: float, lon: float) -> Dict[str, Any]:
    if not OPENWEATHER_KEY:
        raise RuntimeError("OPENWEATHER_API_KEY not set")

    cache_key = f"ow:{lat:.4f}:{lon:.4f}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    params = {
        "lat": lat,
        "lon": lon,
        "appid": OPENWEATHER_KEY,
        "units": "metric",
        "exclude": "minutely,alerts",
    }

    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(OPENWEATHER_URL, params=params)
        r.raise_for_status()
        data = r.json()

    _cache_set(cache_key, data)
    return data


def synth_weather(lat: float, lon: float) -> Dict[str, Any]:
    # Generate plausible conditions; deterministic-ish based on coords
    seed = int(abs(lat * 1000) + abs(lon * 1000))
    rng = random.Random(seed)

    base_max = rng.uniform(28, 38)
    base_min = base_max - rng.uniform(8, 14)
    wind = rng.uniform(1.5, 6.5)
    humidity = rng.uniform(25, 65)
    precip = max(0.0, rng.gauss(1.0, 2.0))

    return {
        "synthetic": True,
        "daily": [
            {
                "temp": {"max": base_max, "min": base_min},
                "wind_speed": wind,
                "humidity": humidity,
                "rain": precip,
            }
        ],
        "current": {
            "wind_speed": wind,
            "humidity": humidity,
            "temp": (base_max + base_min) / 2,
        },
    }


def estimate_et0_mm(temp_max_c: float, temp_min_c: float, wind_mps: float, humidity_pct: float) -> float:
    # Simplified heuristic ET0 proxy for demo purposes.
    # Not a full Penman-Monteith implementation.
    t_mean = (temp_max_c + temp_min_c) / 2
    dryness = (100 - humidity_pct) / 100
    et0 = 2.5 + 0.12 * t_mean + 0.35 * wind_mps + 2.0 * dryness
    return max(2.0, min(et0, 9.5))


def extract_drivers(weather: Dict[str, Any]) -> Dict[str, Any]:
    daily0 = (weather.get("daily") or [{}])[0]
    temp = daily0.get("temp") or {}
    tmax = float(temp.get("max", 32))
    tmin = float(temp.get("min", 18))
    wind = float(daily0.get("wind_speed", weather.get("current", {}).get("wind_speed", 3.5)))
    humidity = float(daily0.get("humidity", weather.get("current", {}).get("humidity", 45)))
    precip = float(daily0.get("rain", 0.0) or 0.0)

    et0 = estimate_et0_mm(tmax, tmin, wind, humidity)

    return {
        "forecast_max_c": round(tmax, 1),
        "forecast_min_c": round(tmin, 1),
        "wind_mps": round(wind, 1),
        "humidity_pct": round(humidity, 0),
        "precip_mm_next_24h": round(precip, 1),
        "et0_mm": round(et0, 2),
    }

