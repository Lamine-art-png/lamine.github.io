from typing import Dict, Any, List
import math
import time
import random

from app.schemas.demo import Assumptions, ConfidenceType, RecommendationOut
from app.schemas.demo import DemoBlock

def _soil_factor(soil_type: str) -> float:
    # Roughly: water holding / infiltration behavior proxy
    st = (soil_type or "unknown").lower()
    return {
        "sand": 0.85,
        "loam": 1.0,
        "silt": 1.05,
        "clay": 1.1,
        "unknown": 1.0,
    }.get(st, 1.0)

def _crop_factor(crop: str) -> float:
    c = (crop or "").lower()
    if "grape" in c:
        return 0.9
    if "almond" in c:
        return 1.05
    return 1.0

def simulate_soil_balance(seed_key: str) -> List[float]:
    rng = random.Random(sum(ord(ch) for ch in seed_key))
    start = rng.uniform(0.55, 0.8)
    series = [start]
    for _ in range(6):
        drift = rng.uniform(-0.08, 0.03)
        series.append(max(0.25, min(0.95, series[-1] + drift)))
    return [round(x, 2) for x in series]

def generate_recommendation(
    block: DemoBlock,
    assumptions: Assumptions,
    drivers: Dict[str, Any],
    mode: str,
) -> Dict[str, Any]:
    et0 = float(drivers.get("et0_mm", 5.0))
    precip = float(drivers.get("precip_mm_next_24h", 0.0))

    soil_f = _soil_factor(assumptions.soil_type)
    crop_f = _crop_factor(block.crop)
    eff = float(assumptions.irrigation_efficiency)
    root = float(assumptions.root_depth_m)

    # Demand proxy: higher ET0 + crop factor + soil factor adjusts intensity
    demand_idx = et0 * crop_f * soil_f

    # Simple precipitation relief
    relief = 0.35 if precip > 3 else 0.15 if precip > 1 else 0.0

    # Root depth gives buffer
    buffer = 0.15 * (root - 0.9)

    score = demand_idx - relief - buffer

    # Convert to action
    if score >= 5.8:
        action = "irrigate"
    elif score >= 4.8:
        action = "reduce"
    else:
        action = "hold"

    # Inches estimate (demo-level approximation)
    # Convert mm ET-ish to inches/week-ish feel
    # 1 inch = 25.4 mm
    weekly_in = (et0 * 7) / 25.4
    # Efficiency penalizes required applied water
    applied_weekly_in = weekly_in / max(0.7, eff)

    # Action-specific amount
    if action == "irrigate":
        amount_in = round(min(0.35, max(0.08, applied_weekly_in * 0.12)), 2)
        window = "Tonight 9pm–2am"
        cadence = "2x/week"
    elif action == "reduce":
        amount_in = round(min(0.22, max(0.05, applied_weekly_in * 0.08)), 2)
        window = "Next cycle"
        cadence = "1–2x/week"
    else:
        amount_in = 0.0
        window = "Reassess in 24–48h"
        cadence = "Hold"

    # Confidence heuristic
    confidence: ConfidenceType
    notes = []
    if mode == "synthetic":
        confidence = "medium"
        notes.append("Synthetic scenario for edge-case demonstration.")
    else:
        confidence = "high" if 4.2 <= et0 <= 7.5 else "medium"

    if precip > 3:
        notes.append("Meaningful rain risk reduces near-term irrigation need.")
    if assumptions.soil_type == "unknown":
        confidence = "medium"
        notes.append("Soil type unknown; recommendation uses neutral assumptions.")
    if eff < 0.75:
        notes.append("Lower efficiency increases applied water requirement.")

    rec = RecommendationOut(
        action=action,
        amount_in=amount_in if amount_in > 0 else None,
        window=window,
        cadence=cadence,
    )

    soil_balance = simulate_soil_balance(f"{block.id}:{assumptions.soil_type}:{mode}")

    return {
        "recommendation": rec.model_dump(),
        "confidence": confidence,
        "notes": notes,
        "soil_balance": soil_balance,
    }

