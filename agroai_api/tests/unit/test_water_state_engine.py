"""Unit tests for WaterStateEngine — pure computation, no DB needed."""
import pytest
from datetime import datetime, timedelta

from app.services.feature_builder import DepthReading, FeatureSet
from app.services.water_state_engine import (
    WaterStateEngine,
    ENGINE_VERSION,
    STRESS_VWC_THRESHOLD,
    FIELD_CAPACITY_VWC,
    WILTING_POINT_VWC,
    SATURATION_VWC,
)


def _make_feature_set(**overrides) -> FeatureSet:
    """Helper to build a FeatureSet with sensible defaults."""
    now = datetime.utcnow()
    defaults = dict(
        block_id="block-001",
        computed_at=now,
        depth_readings=[
            DepthReading(depth_inches=12, vwc=0.32, timestamp=now - timedelta(minutes=30)),
            DepthReading(depth_inches=24, vwc=0.30, timestamp=now - timedelta(minutes=30)),
            DepthReading(depth_inches=36, vwc=0.28, timestamp=now - timedelta(minutes=30)),
            DepthReading(depth_inches=48, vwc=0.26, timestamp=now - timedelta(minutes=30)),
            DepthReading(depth_inches=60, vwc=0.24, timestamp=now - timedelta(minutes=30)),
        ],
        mean_vwc=0.28,
        min_vwc=0.24,
        max_vwc=0.32,
        weighted_root_zone_vwc=0.293,
        vwc_trend_pct_per_hour=-0.002,
        trend_window_hours=24.0,
        et_demand_mm_day=5.5,
        recent_rainfall_mm=0.0,
        last_irrigation_at=now - timedelta(hours=36),
        last_irrigation_volume_m3=25.0,
        last_irrigation_duration_min=45.0,
        irrigations_last_7d=2,
        total_irrigation_volume_7d_m3=50.0,
        data_age_hours=0.5,
        depth_coverage=1.0,
        readings_count_24h=48,
        anomalies=[],
    )
    defaults.update(overrides)
    return FeatureSet(**defaults)


@pytest.fixture
def engine():
    return WaterStateEngine()


class TestEstimateBasic:
    def test_returns_estimate_with_all_fields(self, engine):
        fs = _make_feature_set()
        est = engine.estimate(fs)

        assert est.block_id == "block-001"
        assert est.engine_version == ENGINE_VERSION
        assert est.root_zone_vwc > 0
        assert 0 <= est.stress_risk <= 1
        assert est.refill_status in ("depleting", "stable", "refilling", "saturated", "unknown")
        assert 0 <= est.confidence <= 1
        assert isinstance(est.depth_profile, list)
        assert isinstance(est.anomaly_flags, list)
        assert isinstance(est.feature_snapshot, dict)

    def test_uses_weighted_vwc_over_mean(self, engine):
        fs = _make_feature_set(weighted_root_zone_vwc=0.30, mean_vwc=0.25)
        est = engine.estimate(fs)
        assert est.root_zone_vwc == 0.30

    def test_falls_back_to_mean_vwc(self, engine):
        fs = _make_feature_set(weighted_root_zone_vwc=None, mean_vwc=0.27)
        est = engine.estimate(fs)
        assert est.root_zone_vwc == 0.27

    def test_falls_back_to_zero_when_no_vwc(self, engine):
        fs = _make_feature_set(
            weighted_root_zone_vwc=None, mean_vwc=None, depth_readings=[]
        )
        est = engine.estimate(fs)
        assert est.root_zone_vwc == 0.0


class TestStressRisk:
    def test_low_stress_at_field_capacity(self, engine):
        fs = _make_feature_set(weighted_root_zone_vwc=FIELD_CAPACITY_VWC)
        est = engine.estimate(fs)
        assert est.stress_risk < 0.2

    def test_high_stress_near_wilting_point(self, engine):
        fs = _make_feature_set(weighted_root_zone_vwc=WILTING_POINT_VWC + 0.01)
        est = engine.estimate(fs)
        assert est.stress_risk > 0.5

    def test_max_stress_at_wilting_point(self, engine):
        fs = _make_feature_set(weighted_root_zone_vwc=WILTING_POINT_VWC)
        est = engine.estimate(fs)
        assert est.stress_risk > 0.55

    def test_rapid_drying_increases_stress(self, engine):
        fs_slow = _make_feature_set(vwc_trend_pct_per_hour=-0.001)
        fs_fast = _make_feature_set(vwc_trend_pct_per_hour=-0.03)

        est_slow = engine.estimate(fs_slow)
        est_fast = engine.estimate(fs_fast)

        assert est_fast.stress_risk > est_slow.stress_risk

    def test_high_et_amplifies_stress(self, engine):
        fs_low_et = _make_feature_set(et_demand_mm_day=3.0)
        fs_high_et = _make_feature_set(et_demand_mm_day=12.0)

        est_low = engine.estimate(fs_low_et)
        est_high = engine.estimate(fs_high_et)

        assert est_high.stress_risk >= est_low.stress_risk


class TestRefillStatus:
    def test_depleting_with_negative_trend(self, engine):
        fs = _make_feature_set(vwc_trend_pct_per_hour=-0.005)
        est = engine.estimate(fs)
        assert est.refill_status == "depleting"

    def test_refilling_with_positive_trend(self, engine):
        fs = _make_feature_set(vwc_trend_pct_per_hour=0.005)
        est = engine.estimate(fs)
        assert est.refill_status == "refilling"

    def test_stable_with_near_zero_trend(self, engine):
        fs = _make_feature_set(vwc_trend_pct_per_hour=0.0005)
        est = engine.estimate(fs)
        assert est.refill_status == "stable"

    def test_saturated_at_high_vwc(self, engine):
        fs = _make_feature_set(weighted_root_zone_vwc=SATURATION_VWC + 0.01)
        est = engine.estimate(fs)
        assert est.refill_status == "saturated"

    def test_unknown_when_no_trend(self, engine):
        fs = _make_feature_set(
            vwc_trend_pct_per_hour=None,
            weighted_root_zone_vwc=0.30,
        )
        est = engine.estimate(fs)
        assert est.refill_status == "unknown"


class TestHoursToStress:
    def test_returns_none_when_not_depleting(self, engine):
        fs = _make_feature_set(vwc_trend_pct_per_hour=0.002)
        est = engine.estimate(fs)
        assert est.hours_to_stress is None

    def test_returns_zero_when_already_stressed(self, engine):
        fs = _make_feature_set(
            weighted_root_zone_vwc=STRESS_VWC_THRESHOLD - 0.01,
            vwc_trend_pct_per_hour=-0.005,
        )
        est = engine.estimate(fs)
        assert est.hours_to_stress == 0.0

    def test_calculates_hours_when_depleting(self, engine):
        # VWC = 0.28, stress at 0.18, trend = -0.005/hr
        # Expected: (0.28 - 0.18) / 0.005 = 20 hours
        fs = _make_feature_set(
            weighted_root_zone_vwc=0.28,
            vwc_trend_pct_per_hour=-0.005,
        )
        est = engine.estimate(fs)
        assert est.hours_to_stress is not None
        assert 19 <= est.hours_to_stress <= 21

    def test_capped_at_720_hours(self, engine):
        # Very slow depletion
        fs = _make_feature_set(
            weighted_root_zone_vwc=0.35,
            vwc_trend_pct_per_hour=-0.0001,
        )
        est = engine.estimate(fs)
        assert est.hours_to_stress is not None
        assert est.hours_to_stress <= 720.0


class TestConfidence:
    def test_high_confidence_with_good_data(self, engine):
        fs = _make_feature_set(
            depth_coverage=1.0,
            data_age_hours=0.5,
            readings_count_24h=48,
            anomalies=[],
        )
        est = engine.estimate(fs)
        assert est.confidence > 0.8

    def test_low_confidence_with_stale_data(self, engine):
        fs = _make_feature_set(data_age_hours=8.0)
        est = engine.estimate(fs)
        assert est.confidence < 0.7

    def test_low_confidence_with_missing_depths(self, engine):
        now = datetime.utcnow()
        fs = _make_feature_set(
            depth_readings=[
                DepthReading(depth_inches=12, vwc=0.30, timestamp=now),
            ],
            depth_coverage=0.2,
        )
        est = engine.estimate(fs)
        assert est.confidence < 0.5

    def test_anomalies_reduce_confidence(self, engine):
        fs_clean = _make_feature_set(anomalies=[])
        fs_noisy = _make_feature_set(anomalies=["stale_data", "sensor_drift", "missing_depth"])

        est_clean = engine.estimate(fs_clean)
        est_noisy = engine.estimate(fs_noisy)

        assert est_noisy.confidence < est_clean.confidence

    def test_few_readings_reduce_confidence(self, engine):
        fs = _make_feature_set(readings_count_24h=2)
        est = engine.estimate(fs)
        assert est.confidence < 0.8


class TestFeatureSnapshot:
    def test_snapshot_included(self, engine):
        fs = _make_feature_set()
        est = engine.estimate(fs)
        assert "block_id" in est.feature_snapshot
        assert "weighted_root_zone_vwc" in est.feature_snapshot

    def test_depth_profile_serialized(self, engine):
        fs = _make_feature_set()
        est = engine.estimate(fs)
        assert len(est.depth_profile) == 5
        assert "depth_inches" in est.depth_profile[0]
        assert "vwc" in est.depth_profile[0]
