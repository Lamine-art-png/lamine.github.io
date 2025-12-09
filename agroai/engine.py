# agroai/engine.py

"""
Very simple local irrigation "engine" so we can run simulations
without calling any API.

Later you can replace this with your real model logic.
"""

def recommend_irrigation(payload: dict) -> float:
    """
    Given a payload with weather and constraints, return recommended_inches (float).

    This is intentionally simple:
    - Use ET0 as a proxy for demand
    - Apply a crop coefficient (kc)
    - Convert mm -> inches
    - Clamp to max daily capacity
    """
    weather = payload.get("weather", {})
    et0_mm = float(weather.get("et0_mm", 0.0))

    crop_type = payload.get("crop", {}).get("type", "")
    # crude kc by crop type
    if "almond" in crop_type:
        kc = 1.0
    elif "grape" in crop_type or "vine" in crop_type:
        kc = 0.9
    else:
        kc = 0.95

    et_mm = et0_mm * kc
    # mm -> inches
    inches = et_mm / 25.4

    # daily max from system constraints
    constraints = payload.get("constraints", {})
    max_daily_in = float(constraints.get("max_daily_in", 0.3))

    recommended_inches = min(inches, max_daily_in)
    # never negative
    return max(recommended_inches, 0.0)

