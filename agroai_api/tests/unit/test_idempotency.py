"""Unit tests for idempotency service."""
import pytest
from datetime import datetime, timedelta
from app.services.idempotency import IdempotencyService
from app.models.recommendation import Recommendation


def test_compute_body_hash():
    """Test body hash computation."""
    body1 = {"a": 1, "b": 2}
    body2 = {"b": 2, "a": 1}  # Different order, same content

    hash1 = IdempotencyService.compute_body_hash(body1)
    hash2 = IdempotencyService.compute_body_hash(body2)

    # Should be identical despite different order
    assert hash1 == hash2

    body3 = {"a": 1, "b": 3}
    hash3 = IdempotencyService.compute_body_hash(body3)

    # Different content should produce different hash
    assert hash1 != hash3


def test_compute_feature_hash():
    """Test feature hash computation."""
    features1 = {"vwc": 0.30, "et0": 5.0}
    features2 = {"et0": 5.0, "vwc": 0.30}

    hash1 = IdempotencyService.compute_feature_hash("block-1", 72, features1)
    hash2 = IdempotencyService.compute_feature_hash("block-1", 72, features2)

    assert hash1 == hash2


def test_get_cached_recommendation(db, test_tenant, test_block):
    """Test retrieving cached recommendation."""
    import uuid

    # Create a recommendation
    rec = Recommendation(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant.id,
        block_id=test_block.id,
        idempotency_key="test-key",
        body_hash="test-hash",
        when=datetime.utcnow(),
        duration_min=60,
        volume_m3=100,
        confidence=0.8,
        horizon_hours=72,
        explanations=["test"],
        version="1.0.0",
    )

    db.add(rec)
    db.commit()

    # Retrieve it
    cached = IdempotencyService.get_cached_recommendation(
        db, test_tenant.id, "test-key", "test-hash"
    )

    assert cached is not None
    assert cached.id == rec.id


def test_expired_idempotency(db, test_tenant, test_block):
    """Test that expired recommendations are not returned."""
    import uuid

    # Create an old recommendation (25 hours ago - beyond 24h TTL)
    rec = Recommendation(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant.id,
        block_id=test_block.id,
        idempotency_key="old-key",
        body_hash="old-hash",
        when=datetime.utcnow(),
        duration_min=60,
        volume_m3=100,
        confidence=0.8,
        horizon_hours=72,
        explanations=["test"],
        version="1.0.0",
        created_at=datetime.utcnow() - timedelta(hours=25),
    )

    db.add(rec)
    db.commit()

    # Should not retrieve expired recommendation
    cached = IdempotencyService.get_cached_recommendation(
        db, test_tenant.id, "old-key", "old-hash"
    )

    assert cached is None
