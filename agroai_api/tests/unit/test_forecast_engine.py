"""Unit tests for ForecastEngine — pure computation, no DB."""
import pytest
from datetime import datetime, timedelta

from app.services.feature_builder import DepthReading, FeatureSet
from app.services.forecast_engine import (
    ForecastEngine,
    FORECAST_VERSION,
    HORIZONS_HOURS,
    VWCForecast,
    VWCForecastPoint,
)
from app.services.crop_soil_profile import (
    CropSoilProfile,
    DEFAULT_PROFILE,
    get_profile,
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
    return ForecastEngine()


class TestForecastBasic:
    def test_returns_forecast_with_all_fields(self, engine):
        fs = _make_feature_set()
        fc = engine.forecast(fs)
        assert isinstance(fc, VWCForecast)
        assert fc.block_id == "block-001"
        assert fc.forecast_version == FORECAST_VERSION
        assert fc.current_vwc > 0
        assert len(fc.points) == len(HORIZONS_HOURS)

    def test_forecast_points_at_correct_horizons(self, engine):
        fs = _make_feature_set()
        fc = engine.forecast(fs)
        horizons = [p.hours_ahead for p in fc.points]
        assert horizons == HORIZONS_HOURS

    def test_confidence_decreases_with_horizon(self, engine):
        fs = _make_feature_set()
        fc = engine.forecast(fs)
        confidences = [p.confidence for p in fc.points]
        # Each later horizon should have equal or lower confidence
        for i in range(len(confidences) - 1):
            assert confidences[i] >= confidences[i + 1]

    def test_vwc_decreases_under_et_depletion(self, engine):
        """When depleting (negative trend, no recent irrigation), VWC should drop."""
        fs = _make_feature_set(
            last_irrigation_at=datetime.utcnow() - timedelta(days=5),
        )
        fc = engine.forecast(fs)
        # 72h forecast should be lower than current
        assert fc.points[-1].predicted_vwc < fc.current_vwc

    def test_to_dict_serializes_correctly(self, engine):
        fs = _make_feature_set()
        fc = engine.forecast(fs)
        d = fc.to_dict()
        assert "block_id" in d
        assert "points" in d
        assert len(d["points"]) == len(HORIZONS_HOURS)
        assert "hours_to_stress" in d
        assert "optimal_irrigation_window" in d


class TestStressDetection:
    def test_detects_stress_when_vwc_near_threshold(self, engine):
        """Low VWC close to stress threshold should trigger stress detection."""
        profile = get_profile("corn", "loam")  # stress at 0.20
        fs = _make_feature_set(
            weighted_root_zone_vwc=0.22,
            mean_vwc=0.22,
            et_demand_mm_day=6.0,
            last_irrigation_at=datetime.utcnow() - timedelta(days=3),
        )
        fc = engine.forecast(fs, profile)
        # Should detect impending stress
        assert fc.hours_to_stress is not None
        assert fc.hours_to_stress >= 0

    def test_no_stress_when_well_irrigated(self, engine):
        """High VWC with recent irrigation should not predict stress."""
        fs = _make_feature_set(
            weighted_root_zone_vwc=0.35,
            mean_vwc=0.35,
            et_demand_mm_day=3.0,
            last_irrigation_at=datetime.utcnow() - timedelta(hours=6),
            last_irrigation_volume_m3=50.0,
        )
        fc = engine.forecast(fs, DEFAULT_PROFILE)
        # High VWC with recent irrigation — no stress at 6h at least
        first_point = fc.points[0]
        assert first_point.below_stress is False

    def test_already_stressed_returns_zero_hours(self, engine):
        """VWC below stress threshold returns 0 hours to stress."""
        profile = get_profile("corn", "loam")  # stress at 0.20
        fs = _make_feature_set(
            weighted_root_zone_vwc=0.15,
            mean_vwc=0.15,
        )
        fc = engine.forecast(fs, profile)
        assert fc.hours_to_stress is not None
        assert fc.hours_to_stress == 0.0


class TestIrrigationWindow:
    def test_not_needed_when_saturated(self, engine):
        profile = DEFAULT_PROFILE
        fs = _make_feature_set(
            weighted_root_zone_vwc=profile.field_capacity + 0.01,
            mean_vwc=profile.field_capacity + 0.01,
        )
        fc = engine.forecast(fs, profile)
        assert fc.optimal_irrigation_window == "not_needed"

    def test_now_when_already_stressed(self, engine):
        profile = get_profile("corn", "loam")
        fs = _make_feature_set(
            weighted_root_zone_vwc=0.15,
            mean_vwc=0.15,
            et_demand_mm_day=8.0,
            last_irrigation_at=datetime.utcnow() - timedelta(days=5),
        )
        fc = engine.forecast(fs, profile)
        assert fc.optimal_irrigation_window == "now"


class TestCropProfiles:
    def test_different_profiles_produce_different_forecasts(self, engine):
        fs = _make_feature_set()
        fc_corn = engine.forecast(fs, get_profile("corn", "loam"))
        fc_vine = engine.forecast(fs, get_profile("vineyard", "loam"))
        # Different Kc values should produce different ET loss
        assert fc_corn.profile_used != fc_vine.profile_used
        # Points should differ due to different ET rates
        assert fc_corn.points[-1].predicted_vwc != fc_vine.points[-1].predicted_vwc

    def test_profile_name_in_output(self, engine):
        fs = _make_feature_set()
        fc = engine.forecast(fs, get_profile("almonds", "sandy_loam"))
        assert fc.profile_used == "almonds/sandy_loam"


class TestPhysicsModel:
    def test_et_depletion_rate_positive(self, engine):
        fs = _make_feature_set(et_demand_mm_day=5.0)
        rate = engine._et_depletion_rate(fs, DEFAULT_PROFILE)
        assert rate > 0

    def test_higher_et_means_faster_depletion(self, engine):
        fs_low = _make_feature_set(et_demand_mm_day=3.0)
        fs_high = _make_feature_set(et_demand_mm_day=8.0)
        rate_low = engine._et_depletion_rate(fs_low, DEFAULT_PROFILE)
        rate_high = engine._et_depletion_rate(fs_high, DEFAULT_PROFILE)
        assert rate_high > rate_low

    def test_higher_kc_means_faster_depletion(self, engine):
        fs = _make_feature_set(et_demand_mm_day=5.0)
        profile_low_kc = CropSoilProfile(
            crop_type="test", soil_type="test",
            field_capacity=0.36, wilting_point=0.12, stress_threshold=0.20,
            saturation=0.45, root_depth_mm=600, mad=0.50, kc=0.70,
        )
        profile_high_kc = CropSoilProfile(
            crop_type="test", soil_type="test",
            field_capacity=0.36, wilting_point=0.12, stress_threshold=0.20,
            saturation=0.45, root_depth_mm=600, mad=0.50, kc=1.20,
        )
        rate_low = engine._et_depletion_rate(fs, profile_low_kc)
        rate_high = engine._et_depletion_rate(fs, profile_high_kc)
        assert rate_high > rate_low

    def test_refill_curve_active_when_recent_irrigation(self, engine):
        fs = _make_feature_set(
            last_irrigation_at=datetime.utcnow() - timedelta(hours=6),
            last_irrigation_volume_m3=30.0,
        )
        curve = engine._irrigation_refill_curve(fs, DEFAULT_PROFILE)
        assert curve.get("active") is True

    def test_refill_curve_inactive_when_old_irrigation(self, engine):
        fs = _make_feature_set(
            last_irrigation_at=datetime.utcnow() - timedelta(days=5),
        )
        curve = engine._irrigation_refill_curve(fs, DEFAULT_PROFILE)
        assert curve.get("active") is False

    def test_predicted_vwc_clamped_to_physical_bounds(self, engine):
        """VWC should never go below ~0.8 * wilting point or above saturation."""
        profile = DEFAULT_PROFILE
        fs = _make_feature_set(
            weighted_root_zone_vwc=0.15,
            mean_vwc=0.15,
            et_demand_mm_day=10.0,
            last_irrigation_at=datetime.utcnow() - timedelta(days=10),
        )
        fc = engine.forecast(fs, profile)
        for p in fc.points:
            assert p.predicted_vwc >= profile.wilting_point * 0.8
            assert p.predicted_vwc <= profile.saturation


class TestConfidence:
    def test_fresh_data_high_confidence(self, engine):
        fs = _make_feature_set(
            data_age_hours=0.5,
            readings_count_24h=48,
            depth_coverage=1.0,
        )
        fc = engine.forecast(fs)
        assert fc.confidence >= 0.7

    def test_stale_data_lower_confidence(self, engine):
        fs_fresh = _make_feature_set(data_age_hours=0.5, readings_count_24h=48)
        fs_stale = _make_feature_set(data_age_hours=5.0, readings_count_24h=5)
        fc_fresh = engine.forecast(fs_fresh)
        fc_stale = engine.forecast(fs_stale)
        assert fc_fresh.confidence > fc_stale.confidence

    def test_no_data_low_confidence(self, engine):
        fs = _make_feature_set(
            depth_readings=[],
            weighted_root_zone_vwc=None,
            mean_vwc=None,
            data_age_hours=None,
            depth_coverage=0.0,
            readings_count_24h=0,
        )
        fc = engine.forecast(fs)
        assert fc.confidence < 0.5


class TestEdgeCases:
    def test_zero_vwc(self, engine):
        fs = _make_feature_set(weighted_root_zone_vwc=0.0, mean_vwc=0.0)
        fc = engine.forecast(fs)
        assert fc is not None
        assert len(fc.points) == len(HORIZONS_HOURS)

    def test_saturated_vwc(self, engine):
        fs = _make_feature_set(weighted_root_zone_vwc=0.45, mean_vwc=0.45)
        fc = engine.forecast(fs)
        assert fc is not None
        assert fc.optimal_irrigation_window == "not_needed"

    def test_no_et_data(self, engine):
        fs = _make_feature_set(et_demand_mm_day=None)
        fc = engine.forecast(fs)
        assert fc is not None  # Should use default ET
