"""Irrigation recommendation engine using water balance method."""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.models.telemetry import Telemetry
from app.models.block import Block
from app.schemas.recommendation import IrrigationConstraints, IrrigationTargets

logger = logging.getLogger(__name__)

MODEL_VERSION = "rf-ens-1.0.0"


class Recommender:
    """
    Baseline water balance recommender.

    Algorithm: ET0 - effective rainfall + soil VWC deficit → irrigation need
    """

    def compute(
        self,
        db: Session,
        block_id: str,
        constraints: Optional[IrrigationConstraints],
        targets: Optional[IrrigationTargets],
        horizon_hours: float,
    ) -> Dict:
        """
        Compute irrigation recommendation.

        Returns:
            {
                "when": datetime,
                "duration_min": float,
                "volume_m3": float,
                "confidence": float,
                "explanations": List[str],
                "version": str
            }
        """
        # Get block info
        block = db.query(Block).filter(Block.id == block_id).first()
        if not block:
            raise ValueError(f"Block {block_id} not found")

        # Default targets
        if not targets:
            targets = IrrigationTargets()

        target_vwc = targets.target_soil_vwc or 0.35  # 35% field capacity
        efficiency = targets.efficiency or 0.85

        # Get recent telemetry
        features = self._extract_features(db, block_id, horizon_hours)

        # Calculate water deficit
        water_deficit_mm, confidence = self._calculate_deficit(
            features, target_vwc, block.crop_type
        )

        explanations = []

        # Decision logic
        if water_deficit_mm < 5:
            # No irrigation needed
            when = datetime.utcnow() + timedelta(hours=horizon_hours * 0.8)
            duration_min = 0
            volume_m3 = 0
            explanations.append(f"Soil moisture adequate (deficit: {water_deficit_mm:.1f}mm)")
        else:
            # Calculate irrigation timing
            when = self._optimal_timing(constraints, features)

            # Calculate duration and volume
            # Convert mm to m3 based on area
            volume_m3 = (water_deficit_mm / 1000.0) * block.area_ha * 10000 / efficiency

            # Estimate duration (assumes flow rate ~50 m3/hr per ha)
            flow_rate_m3_hr = 50 * block.area_ha
            duration_min = (volume_m3 / flow_rate_m3_hr) * 60

            # Apply constraints
            if constraints:
                if constraints.min_duration_min:
                    duration_min = max(duration_min, constraints.min_duration_min)
                if constraints.max_duration_min:
                    duration_min = min(duration_min, constraints.max_duration_min)

            explanations.append(f"Water deficit: {water_deficit_mm:.1f}mm")
            explanations.append(f"Current soil VWC: {features.get('current_vwc', 'unknown')}")
            explanations.append(f"Recent ET0: {features.get('recent_et0', 'unknown')}mm/day")
            explanations.append(f"Application efficiency: {efficiency*100:.0f}%")

        return {
            "when": when,
            "duration_min": round(duration_min, 2),
            "volume_m3": round(volume_m3, 2),
            "confidence": confidence,
            "explanations": explanations,
            "version": MODEL_VERSION,
        }

    def _extract_features(
        self, db: Session, block_id: str, horizon_hours: float
    ) -> Dict:
        """Extract features from recent telemetry."""
        now = datetime.utcnow()
        lookback = now - timedelta(days=7)

        features = {}

        # Get latest soil VWC
        vwc_reading = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == block_id,
                    Telemetry.type == "soil_vwc",
                    Telemetry.timestamp >= lookback,
                )
            )
            .order_by(desc(Telemetry.timestamp))
            .first()
        )

        if vwc_reading:
            features["current_vwc"] = vwc_reading.value
        else:
            features["current_vwc"] = 0.30  # Default assumption

        # Get recent ET0 (last 3 days average)
        et0_readings = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == block_id,
                    Telemetry.type == "et0",
                    Telemetry.timestamp >= now - timedelta(days=3),
                )
            )
            .all()
        )

        if et0_readings:
            features["recent_et0"] = sum(r.value for r in et0_readings) / len(et0_readings)
        else:
            features["recent_et0"] = 5.0  # Default 5mm/day

        # Get recent rainfall
        rain_readings = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == block_id,
                    Telemetry.type == "weather",
                    Telemetry.timestamp >= now - timedelta(days=3),
                )
            )
            .all()
        )

        features["recent_rainfall_mm"] = sum(
            r.value for r in rain_readings if r.meta_data and r.meta_data.get("variable") == "rainfall"
        )

        return features

    def _calculate_deficit(
        self, features: Dict, target_vwc: float, crop_type: Optional[str]
    ) -> Tuple[float, float]:
        """
        Calculate water deficit in mm.

        Returns: (deficit_mm, confidence)
        """
        current_vwc = features.get("current_vwc", 0.30)
        recent_et0 = features.get("recent_et0", 5.0)
        rainfall = features.get("recent_rainfall_mm", 0)

        # Soil deficit based on VWC
        vwc_deficit = target_vwc - current_vwc

        # Root zone depth (mm) - varies by crop
        root_zone_depth = 600  # Default 600mm
        if crop_type:
            crop_depths = {
                "corn": 800,
                "wheat": 600,
                "vegetables": 400,
                "trees": 1000,
            }
            root_zone_depth = crop_depths.get(crop_type.lower(), 600)

        # Convert VWC deficit to mm
        deficit_from_vwc = vwc_deficit * root_zone_depth

        # ET-based deficit (forecast)
        # Assume 3-day forward ET minus effective rainfall
        effective_rainfall = rainfall * 0.75  # 75% efficiency
        et_deficit = (recent_et0 * 3) - effective_rainfall

        # Combine both methods (weighted average)
        total_deficit = (deficit_from_vwc * 0.6) + (et_deficit * 0.4)

        # Confidence based on data freshness/availability
        confidence = 0.7 if features.get("current_vwc") else 0.5

        return max(0, total_deficit), confidence

    def _optimal_timing(
        self, constraints: Optional[IrrigationConstraints], features: Dict
    ) -> datetime:
        """Determine optimal irrigation timing."""
        # Default to early morning (6 AM next day)
        now = datetime.utcnow()
        tomorrow_6am = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

        if not constraints or not constraints.preferred_time_start:
            return tomorrow_6am

        # Parse preferred time
        try:
            start_hour, start_min = map(int, constraints.preferred_time_start.split(":"))
            preferred = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)

            # If time passed today, schedule for tomorrow
            if preferred < now:
                preferred += timedelta(days=1)

            return preferred
        except Exception:
            return tomorrow_6am
