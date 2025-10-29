"""Unit tests for recommender service."""
import pytest
from datetime import datetime, timedelta
from app.services.recommender import Recommender
from app.schemas.recommendation import IrrigationConstraints, IrrigationTargets


def test_recommender_compute(db, test_block):
    """Test basic recommendation computation."""
    recommender = Recommender()

    result = recommender.compute(
        db=db,
        block_id=test_block.id,
        constraints=None,
        targets=None,
        horizon_hours=72,
    )

    assert "when" in result
    assert "duration_min" in result
    assert "volume_m3" in result
    assert "confidence" in result
    assert "explanations" in result
    assert "version" in result

    assert isinstance(result["when"], datetime)
    assert result["confidence"] >= 0 and result["confidence"] <= 1
    assert len(result["explanations"]) > 0


def test_recommender_with_constraints(db, test_block):
    """Test recommendation with constraints."""
    recommender = Recommender()

    constraints = IrrigationConstraints(
        min_duration_min=60,
        max_duration_min=180,
        preferred_time_start="06:00"
    )

    result = recommender.compute(
        db=db,
        block_id=test_block.id,
        constraints=constraints,
        targets=None,
        horizon_hours=72,
    )

    # If irrigation is needed, duration should respect constraints
    if result["duration_min"] > 0:
        assert result["duration_min"] >= 60
        assert result["duration_min"] <= 180


def test_recommender_with_targets(db, test_block):
    """Test recommendation with custom targets."""
    recommender = Recommender()

    targets = IrrigationTargets(
        target_soil_vwc=0.40,
        efficiency=0.90
    )

    result = recommender.compute(
        db=db,
        block_id=test_block.id,
        constraints=None,
        targets=targets,
        horizon_hours=48,
    )

    assert result is not None
    assert result["version"] == "rf-ens-1.0.0"
