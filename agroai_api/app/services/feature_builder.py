"""Feature builder — derives structured inputs from raw telemetry and schedules.

Provider-agnostic: works with any data source that writes to the Telemetry
and Schedule tables using AGRO-AI canonical types.

Output is a plain dict (FeatureSet) consumed by WaterStateEngine and Recommender.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.models.telemetry import Telemetry
from app.models.schedule import Schedule

logger = logging.getLogger(__name__)


@dataclass
class DepthReading:
    """Single soil moisture reading at a specific depth."""
    depth_inches: float
    vwc: float
    timestamp: datetime
    source_measure_id: Optional[str] = None


@dataclass
class FeatureSet:
    """Structured feature dict for a single block at a point in time.

    All downstream services (WaterStateEngine, Recommender, ForecastEngine)
    consume this same structure so feature logic is never duplicated.
    """
    block_id: str
    computed_at: datetime

    # Multi-depth soil moisture profile (sorted shallowest → deepest)
    depth_readings: List[DepthReading] = field(default_factory=list)

    # Aggregated soil state
    mean_vwc: Optional[float] = None
    min_vwc: Optional[float] = None
    max_vwc: Optional[float] = None
    weighted_root_zone_vwc: Optional[float] = None

    # Trend (linear slope of mean VWC over last N hours)
    vwc_trend_pct_per_hour: Optional[float] = None  # negative = drying
    trend_window_hours: float = 24.0

    # ET and weather
    et_demand_mm_day: Optional[float] = None
    recent_rainfall_mm: float = 0.0

    # Irrigation history
    last_irrigation_at: Optional[datetime] = None
    last_irrigation_volume_m3: Optional[float] = None
    last_irrigation_duration_min: Optional[float] = None
    irrigations_last_7d: int = 0
    total_irrigation_volume_7d_m3: float = 0.0

    # Data quality
    data_age_hours: Optional[float] = None  # hours since newest reading
    depth_coverage: float = 0.0  # fraction of expected depths present (0-1)
    readings_count_24h: int = 0  # total readings in last 24h

    # Anomaly indicators
    anomalies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage in feature_snapshot column."""
        return {
            "block_id": self.block_id,
            "computed_at": self.computed_at.isoformat(),
            "depth_readings": [
                {"depth_inches": d.depth_inches, "vwc": d.vwc,
                 "timestamp": d.timestamp.isoformat()}
                for d in self.depth_readings
            ],
            "mean_vwc": self.mean_vwc,
            "min_vwc": self.min_vwc,
            "max_vwc": self.max_vwc,
            "weighted_root_zone_vwc": self.weighted_root_zone_vwc,
            "vwc_trend_pct_per_hour": self.vwc_trend_pct_per_hour,
            "et_demand_mm_day": self.et_demand_mm_day,
            "recent_rainfall_mm": self.recent_rainfall_mm,
            "last_irrigation_at": (
                self.last_irrigation_at.isoformat()
                if self.last_irrigation_at else None
            ),
            "last_irrigation_volume_m3": self.last_irrigation_volume_m3,
            "irrigations_last_7d": self.irrigations_last_7d,
            "total_irrigation_volume_7d_m3": self.total_irrigation_volume_7d_m3,
            "data_age_hours": self.data_age_hours,
            "depth_coverage": self.depth_coverage,
            "readings_count_24h": self.readings_count_24h,
            "anomalies": self.anomalies,
        }


# Depth weighting for root-zone average.
# Shallower sensors matter more for active root uptake.
# Weights are normalized at runtime; these are relative importance.
DEFAULT_DEPTH_WEIGHTS = {
    12: 0.30,   # 12 inches — active root zone
    24: 0.25,   # 24 inches
    36: 0.20,   # 36 inches
    48: 0.15,   # 48 inches
    60: 0.10,   # 60 inches — deep storage
}

# Expected number of depth sensors
EXPECTED_DEPTHS = 5

# Stale data threshold
STALE_DATA_HOURS = 2.0


class FeatureBuilder:
    """Builds a FeatureSet for a block from Telemetry + Schedule data."""

    def build(
        self,
        db: Session,
        block_id: str,
        now: Optional[datetime] = None,
    ) -> FeatureSet:
        """Build features for a block at a given time.

        Queries the database for recent telemetry and irrigation history,
        then computes derived features.
        """
        if now is None:
            now = datetime.utcnow()

        fs = FeatureSet(block_id=block_id, computed_at=now)

        self._build_soil_profile(db, block_id, now, fs)
        self._build_soil_trend(db, block_id, now, fs)
        self._build_et_weather(db, block_id, now, fs)
        self._build_irrigation_history(db, block_id, now, fs)
        self._assess_data_quality(now, fs)

        return fs

    # ------------------------------------------------------------------
    # Soil moisture profile
    # ------------------------------------------------------------------

    def _build_soil_profile(
        self, db: Session, block_id: str, now: datetime, fs: FeatureSet
    ) -> None:
        """Get the latest reading at each depth."""
        lookback = now - timedelta(hours=24)

        soil_readings = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == block_id,
                    Telemetry.type == "soil_vwc",
                    Telemetry.timestamp >= lookback,
                )
            )
            .order_by(desc(Telemetry.timestamp))
            .all()
        )

        # Group by depth, keep latest per depth
        latest_by_depth: Dict[float, Telemetry] = {}
        for r in soil_readings:
            depth = None
            if r.meta_data and isinstance(r.meta_data, dict):
                depth = r.meta_data.get("depth_inches")
            if depth is None:
                continue
            depth = float(depth)
            if depth not in latest_by_depth:
                latest_by_depth[depth] = r

        # Build sorted depth readings
        fs.depth_readings = sorted([
            DepthReading(
                depth_inches=depth,
                vwc=r.value,
                timestamp=r.timestamp,
                source_measure_id=r.meta_data.get("measure_id") if r.meta_data else None,
            )
            for depth, r in latest_by_depth.items()
        ], key=lambda d: d.depth_inches)

        if not fs.depth_readings:
            return

        # Compute aggregates
        vwcs = [d.vwc for d in fs.depth_readings]
        fs.mean_vwc = sum(vwcs) / len(vwcs)
        fs.min_vwc = min(vwcs)
        fs.max_vwc = max(vwcs)

        # Weighted root-zone VWC
        total_weight = 0.0
        weighted_sum = 0.0
        for dr in fs.depth_readings:
            w = DEFAULT_DEPTH_WEIGHTS.get(int(dr.depth_inches), 0.1)
            weighted_sum += dr.vwc * w
            total_weight += w
        if total_weight > 0:
            fs.weighted_root_zone_vwc = weighted_sum / total_weight

    # ------------------------------------------------------------------
    # Soil moisture trend
    # ------------------------------------------------------------------

    def _build_soil_trend(
        self, db: Session, block_id: str, now: datetime, fs: FeatureSet
    ) -> None:
        """Compute VWC trend slope from last 24h of data."""
        lookback = now - timedelta(hours=fs.trend_window_hours)

        readings = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == block_id,
                    Telemetry.type == "soil_vwc",
                    Telemetry.timestamp >= lookback,
                )
            )
            .order_by(Telemetry.timestamp)
            .all()
        )

        fs.readings_count_24h = len(readings)

        if len(readings) < 4:
            return  # Not enough data for a trend

        # Simple linear regression: VWC vs hours-since-start
        t0 = readings[0].timestamp
        xs = [(r.timestamp - t0).total_seconds() / 3600.0 for r in readings]
        ys = [r.value for r in readings]

        n = len(xs)
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_x2 = sum(x * x for x in xs)

        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-10:
            return

        slope = (n * sum_xy - sum_x * sum_y) / denom
        fs.vwc_trend_pct_per_hour = slope

    # ------------------------------------------------------------------
    # ET and weather
    # ------------------------------------------------------------------

    def _build_et_weather(
        self, db: Session, block_id: str, now: datetime, fs: FeatureSet
    ) -> None:
        """Get recent ET0 and rainfall."""
        lookback_3d = now - timedelta(days=3)

        # ET0
        et0_readings = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == block_id,
                    Telemetry.type == "et0",
                    Telemetry.timestamp >= lookback_3d,
                )
            )
            .all()
        )
        if et0_readings:
            fs.et_demand_mm_day = sum(r.value for r in et0_readings) / len(et0_readings)

        # Rainfall (stored as weather type with rainfall variable in metadata)
        rain_readings = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == block_id,
                    Telemetry.type == "weather",
                    Telemetry.timestamp >= lookback_3d,
                )
            )
            .all()
        )
        fs.recent_rainfall_mm = sum(
            r.value for r in rain_readings
            if r.meta_data and r.meta_data.get("variable") == "rainfall"
        )

    # ------------------------------------------------------------------
    # Irrigation history
    # ------------------------------------------------------------------

    def _build_irrigation_history(
        self, db: Session, block_id: str, now: datetime, fs: FeatureSet
    ) -> None:
        """Get recent irrigation events from Schedule table."""
        lookback_7d = now - timedelta(days=7)

        schedules = (
            db.query(Schedule)
            .filter(
                and_(
                    Schedule.block_id == block_id,
                    Schedule.start_time >= lookback_7d,
                    Schedule.status.in_(["completed", "active"]),
                )
            )
            .order_by(desc(Schedule.start_time))
            .all()
        )

        fs.irrigations_last_7d = len(schedules)
        fs.total_irrigation_volume_7d_m3 = sum(
            s.volume_m3 or 0 for s in schedules
        )

        if schedules:
            latest = schedules[0]
            fs.last_irrigation_at = latest.start_time
            fs.last_irrigation_volume_m3 = latest.volume_m3
            fs.last_irrigation_duration_min = latest.duration_min

    # ------------------------------------------------------------------
    # Data quality assessment
    # ------------------------------------------------------------------

    def _assess_data_quality(self, now: datetime, fs: FeatureSet) -> None:
        """Assess data freshness and coverage, flag anomalies."""
        # Data age
        if fs.depth_readings:
            newest = max(d.timestamp for d in fs.depth_readings)
            fs.data_age_hours = (now - newest).total_seconds() / 3600.0
        else:
            fs.data_age_hours = None
            fs.anomalies.append("no_soil_data")

        # Depth coverage
        fs.depth_coverage = len(fs.depth_readings) / EXPECTED_DEPTHS

        # Anomaly checks
        if fs.data_age_hours and fs.data_age_hours > STALE_DATA_HOURS:
            fs.anomalies.append("stale_data")

        if fs.depth_coverage < 0.6:
            fs.anomalies.append("missing_depth")

        # Check for sensor drift: if adjacent depths differ by >0.3 VWC
        for i in range(len(fs.depth_readings) - 1):
            diff = abs(fs.depth_readings[i].vwc - fs.depth_readings[i + 1].vwc)
            if diff > 0.3:
                fs.anomalies.append("sensor_drift")
                break

        # Check for unexpected refill without irrigation
        if (fs.vwc_trend_pct_per_hour and fs.vwc_trend_pct_per_hour > 0.005
                and fs.last_irrigation_at
                and (now - fs.last_irrigation_at).total_seconds() > 48 * 3600
                and fs.recent_rainfall_mm < 5):
            fs.anomalies.append("unexpected_refill")
