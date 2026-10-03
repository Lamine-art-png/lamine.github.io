"""Historical market-risk context for commercial positions.

This is NOT a price predictor. It describes how the governed price series
behind a position has historically moved, and applies those historical moves
as deterministic stress scenarios to the customer's exposure.

Methodology ``historical-moves-2026.10.1``:
- input: one governed physical-price series (the one the position's price was
  resolved from), observations ordered in time;
- horizon: moves over ``horizon_periods`` observations (4 periods = ~4 weeks for
  weekly publications, ~4 business days for daily);
- statistics: log returns; empirical percentiles (p5, p25, p50, p75, p95) of
  the horizon move; annualised volatility from per-period log returns;
  percentile rank of the latest observation within the window;
- stress: the position is recomputed by the deterministic scenario engine with
  ``price_pct`` set to the historical p5 and p95 horizon moves;
- evaluation: a rolling out-of-sample coverage check reports how often the
  realised next horizon move fell inside the p5..p95 band estimated from the
  preceding observations only (a calibration diagnostic, not a forecast score);
- minimum sample: 26 observations; below that the module reports
  ``insufficient_history`` and shows nothing quantitative.
"""
from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.market_intelligence import MarketDataSeries, MarketObservation, MarketPosition, MarketContractPosition
from app.services.market_data_plane import series_history, utc_now
from app.services.market_intelligence import MarketCalculationError, scenario_position

METHODOLOGY_VERSION = "historical-moves-2026.10.1"
MIN_OBSERVATIONS = 26
PERIODS_PER_YEAR = {"daily": 252, "daily_business": 252, "weekly": 52, "monthly": 12}


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("empty sample")
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def historical_move_statistics(values: list[Decimal], *, horizon_periods: int, frequency: str) -> dict[str, Any]:
    prices = [float(v) for v in values if v is not None and v > 0]
    if len(prices) < MIN_OBSERVATIONS:
        return {"status": "insufficient_history", "observations": len(prices), "minimum_observations": MIN_OBSERVATIONS}
    log_prices = [math.log(p) for p in prices]
    period_returns = [b - a for a, b in zip(log_prices, log_prices[1:])]
    horizon_moves = sorted(
        math.exp(log_prices[i + horizon_periods] - log_prices[i]) - 1
        for i in range(len(log_prices) - horizon_periods)
    )
    mean = sum(period_returns) / len(period_returns)
    variance = sum((r - mean) ** 2 for r in period_returns) / max(1, len(period_returns) - 1)
    annualised = math.sqrt(variance) * math.sqrt(PERIODS_PER_YEAR.get(frequency, 52))
    latest = prices[-1]
    rank = sum(1 for p in prices if p <= latest) / len(prices)

    # Rolling out-of-sample calibration of the p5..p95 band.
    inside, tested = 0, 0
    for end in range(MIN_OBSERVATIONS, len(log_prices) - horizon_periods):
        history = log_prices[: end + 1]
        moves = sorted(math.exp(history[i + horizon_periods] - history[i]) - 1 for i in range(len(history) - horizon_periods))
        if len(moves) < 10:
            continue
        low, high = _percentile(moves, 0.05), _percentile(moves, 0.95)
        realised = math.exp(log_prices[end + horizon_periods] - log_prices[end]) - 1
        tested += 1
        inside += 1 if low <= realised <= high else 0

    def pct(value: float) -> str:
        return format(Decimal(str(value * 100)).quantize(Decimal("0.01")), "f")

    return {
        "status": "ok",
        "observations": len(prices),
        "horizon_periods": horizon_periods,
        "horizon_moves_percent": {
            "p5": pct(_percentile(horizon_moves, 0.05)),
            "p25": pct(_percentile(horizon_moves, 0.25)),
            "p50": pct(_percentile(horizon_moves, 0.50)),
            "p75": pct(_percentile(horizon_moves, 0.75)),
            "p95": pct(_percentile(horizon_moves, 0.95)),
        },
        "annualised_volatility_percent": pct(annualised),
        "latest_price_percentile_in_window": pct(rank),
        "band_calibration": {
            "method": "rolling out-of-sample p5..p95 coverage",
            "tested_windows": tested,
            "inside_band_percent": pct(inside / tested) if tested else None,
            "expected_inside_percent": "90.00",
            # A band that held far less than 90% of realised moves is a poor
            # guide for this series (short history, trend or regime change).
            "warning": (
                "historical_band_poorly_calibrated"
                if tested >= 10 and inside / tested < 0.70
                else ("too_few_windows_to_evaluate" if tested < 10 else None)
            ),
        },
    }


def position_risk(db: Session, position: MarketPosition, *, horizon_periods: int = 4, window_days: int = 400) -> dict[str, Any]:
    """Historical risk context for the series currently pricing the position."""
    base = {
        "methodology_version": METHODOLOGY_VERSION,
        "not_a_forecast": True,
        "limitations": [
            "Describes historical moves of one governed price series; it does not predict future prices.",
            "Physical price series may be weekly state or market averages rather than the customer's exact delivery point.",
            "Stress results reuse current production, contracts and costs; they do not model correlated yield or FX moves.",
        ],
    }
    audit = (
        db.query(MarketObservation)
        .filter(
            MarketObservation.organization_id == position.organization_id,
            MarketObservation.position_id == position.id,
            MarketObservation.observation_type == "physical_price",
        )
        .order_by(MarketObservation.observed_at.desc())
        .first()
    )
    series_id = ((audit.metadata_json or {}).get("series_id") if audit else None)
    series = db.get(MarketDataSeries, series_id) if series_id else None
    if series is None:
        return {**base, "status": "no_governed_series", "reason": "The position is not priced from a governed shared series; risk context needs one."}
    if not (series.licensing_json or {}).get("derived_values_allowed", True):
        return {**base, "status": "licence_restricted"}
    history = series_history(db, series.id, since=utc_now() - timedelta(days=window_days))
    stats = historical_move_statistics([point.value for point in history], horizon_periods=horizon_periods, frequency=series.frequency)
    result = {
        **base,
        **stats,
        "series": {
            "series_id": series.id,
            "provider": series.provider,
            "source_name": series.source_name,
            "market_name": series.market_name,
            "frequency": series.frequency,
            "window_start": history[0].observed_at.isoformat() + "Z" if history else None,
            "window_end": history[-1].observed_at.isoformat() + "Z" if history else None,
        },
    }
    if stats.get("status") != "ok":
        return result
    contracts = (
        db.query(MarketContractPosition)
        .filter(MarketContractPosition.organization_id == position.organization_id, MarketContractPosition.position_id == position.id)
        .all()
    )
    stress: dict[str, Any] = {}
    for label in ("p5", "p95"):
        try:
            scenario = scenario_position(position, contracts, {"price_pct": stats["horizon_moves_percent"][label]})
        except MarketCalculationError as exc:
            stress[label] = {"status": "unavailable", "reason": str(exc)}
            continue
        stress[label] = {
            "price_pct": stats["horizon_moves_percent"][label],
            "projected_margin": scenario["result"].get("projected_margin"),
            "exposed_revenue": scenario["result"].get("exposed_revenue"),
            "delta": {k: scenario["delta"].get(k) for k in ("projected_margin", "exposed_revenue", "projected_revenue")},
        }
    result["stress"] = stress
    return result
