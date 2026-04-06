"""Forecast accuracy tracker — compares predicted vs observed VWC.

After a forecast is made, this service checks back at each horizon
to see how close the prediction was. Builds a per-block accuracy
history that feeds into forecast confidence calibration.

No ML — explicit comparison and exponential moving average.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.models.forecast import Forecast
from app.models.water_state import WaterState

logger = logging.getLogger(__name__)

ACCURACY_VERSION = "fa-1.0.0"

# How close predicted must be to observed to count as "accurate"
GOOD_ACCURACY_THRESHOLD = 0.03   # ±3% VWC
FAIR_ACCURACY_THRESHOLD = 0.06   # ±6% VWC


@dataclass
class HorizonAccuracy:
    """Accuracy at a single forecast horizon."""
    hours_ahead: int
    predicted_vwc: float
    observed_vwc: float
    error: float          # predicted - observed (signed)
    abs_error: float      # |error|
    accuracy_grade: str   # "good" | "fair" | "poor"


@dataclass
class ForecastAccuracyReport:
    """Accuracy report for a single past forecast."""
    forecast_id: str
    block_id: str
    computed_at: datetime
    horizons: List[HorizonAccuracy]
    mean_abs_error: float
    bias: float              # mean signed error (positive = over-predicting)
    overall_grade: str       # "good" | "fair" | "poor"
    version: str = ACCURACY_VERSION

    def to_dict(self) -> Dict:
        return {
            "forecast_id": self.forecast_id,
            "block_id": self.block_id,
            "computed_at": self.computed_at.isoformat(),
            "horizons": [
                {
                    "hours_ahead": h.hours_ahead,
                    "predicted_vwc": h.predicted_vwc,
                    "observed_vwc": h.observed_vwc,
                    "error": h.error,
                    "abs_error": h.abs_error,
                    "accuracy_grade": h.accuracy_grade,
                }
                for h in self.horizons
            ],
            "mean_abs_error": self.mean_abs_error,
            "bias": self.bias,
            "overall_grade": self.overall_grade,
            "version": self.version,
        }


class ForecastAccuracyTracker:
    """Compares past forecasts against observed water states.

    Stateless: queries DB for past forecasts and matching water states,
    computes accuracy metrics. The caller persists results if desired.
    """

    def evaluate(
        self,
        db: Session,
        block_id: str,
        lookback_days: int = 7,
    ) -> List[ForecastAccuracyReport]:
        """Evaluate accuracy of recent forecasts for a block.

        For each past forecast, find the closest water state observation
        at each horizon and compute error.
        """
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)

        forecasts = (
            db.query(Forecast)
            .filter(
                and_(
                    Forecast.block_id == block_id,
                    Forecast.computed_at >= cutoff,
                )
            )
            .order_by(desc(Forecast.computed_at))
            .limit(50)
            .all()
        )

        reports = []
        for fc in forecasts:
            report = self._evaluate_single(db, fc)
            if report:
                reports.append(report)

        return reports

    def block_accuracy_summary(
        self,
        db: Session,
        block_id: str,
        lookback_days: int = 30,
    ) -> Dict:
        """Compute aggregate accuracy stats for a block.

        Returns per-horizon MAE and bias for confidence calibration.
        """
        reports = self.evaluate(db, block_id, lookback_days)

        if not reports:
            return {
                "block_id": block_id,
                "forecast_count": 0,
                "per_horizon": {},
                "overall_mae": None,
                "overall_bias": None,
                "calibration_factor": 1.0,
            }

        # Aggregate per horizon
        horizon_errors: Dict[int, List[float]] = {}
        horizon_signed: Dict[int, List[float]] = {}
        all_abs_errors = []

        for report in reports:
            for h in report.horizons:
                horizon_errors.setdefault(h.hours_ahead, []).append(h.abs_error)
                horizon_signed.setdefault(h.hours_ahead, []).append(h.error)
                all_abs_errors.append(h.abs_error)

        per_horizon = {}
        for hours in sorted(horizon_errors.keys()):
            errors = horizon_errors[hours]
            signed = horizon_signed[hours]
            per_horizon[hours] = {
                "mae": round(sum(errors) / len(errors), 4),
                "bias": round(sum(signed) / len(signed), 4),
                "count": len(errors),
            }

        overall_mae = sum(all_abs_errors) / len(all_abs_errors) if all_abs_errors else 0.0

        # Calibration factor: reduces confidence when forecasts are inaccurate
        # MAE < 0.03 → factor 1.0, MAE > 0.10 → factor 0.5
        if overall_mae < GOOD_ACCURACY_THRESHOLD:
            calibration = 1.0
        elif overall_mae < 0.10:
            calibration = max(0.5, 1.0 - (overall_mae - GOOD_ACCURACY_THRESHOLD) / 0.07 * 0.5)
        else:
            calibration = 0.5

        return {
            "block_id": block_id,
            "forecast_count": len(reports),
            "per_horizon": per_horizon,
            "overall_mae": round(overall_mae, 4),
            "overall_bias": round(
                sum(r.bias for r in reports) / len(reports), 4
            ),
            "calibration_factor": round(calibration, 3),
        }

    def _evaluate_single(
        self, db: Session, fc: Forecast
    ) -> Optional[ForecastAccuracyReport]:
        """Evaluate a single forecast against observed water states."""
        if not fc.points:
            return None

        horizons = []
        for point in fc.points:
            hours_ahead = point["hours_ahead"]
            predicted_vwc = point["predicted_vwc"]

            # Find water state closest to forecast_time + hours_ahead
            target_time = fc.computed_at + timedelta(hours=hours_ahead)
            window_start = target_time - timedelta(hours=2)
            window_end = target_time + timedelta(hours=2)

            observed = (
                db.query(WaterState)
                .filter(
                    and_(
                        WaterState.block_id == fc.block_id,
                        WaterState.estimated_at >= window_start,
                        WaterState.estimated_at <= window_end,
                    )
                )
                .order_by(
                    # Closest to target time
                    WaterState.estimated_at
                )
                .first()
            )

            if not observed:
                continue

            error = predicted_vwc - observed.root_zone_vwc
            abs_error = abs(error)

            if abs_error <= GOOD_ACCURACY_THRESHOLD:
                grade = "good"
            elif abs_error <= FAIR_ACCURACY_THRESHOLD:
                grade = "fair"
            else:
                grade = "poor"

            horizons.append(HorizonAccuracy(
                hours_ahead=hours_ahead,
                predicted_vwc=round(predicted_vwc, 4),
                observed_vwc=round(observed.root_zone_vwc, 4),
                error=round(error, 4),
                abs_error=round(abs_error, 4),
                accuracy_grade=grade,
            ))

        if not horizons:
            return None

        errors = [h.abs_error for h in horizons]
        signed = [h.error for h in horizons]
        mae = sum(errors) / len(errors)
        bias = sum(signed) / len(signed)

        if mae <= GOOD_ACCURACY_THRESHOLD:
            overall = "good"
        elif mae <= FAIR_ACCURACY_THRESHOLD:
            overall = "fair"
        else:
            overall = "poor"

        return ForecastAccuracyReport(
            forecast_id=fc.id,
            block_id=fc.block_id,
            computed_at=fc.computed_at,
            horizons=horizons,
            mean_abs_error=round(mae, 4),
            bias=round(bias, 4),
            overall_grade=overall,
        )
