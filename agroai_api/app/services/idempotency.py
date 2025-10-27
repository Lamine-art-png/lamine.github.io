"""Idempotency service for deduplicating requests."""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.recommendation import Recommendation
from app.core.config import settings


class IdempotencyService:
    """Handle idempotent request processing."""

    @staticmethod
    def compute_body_hash(body: dict) -> str:
        """Compute hash of request body for deduplication."""
        body_str = json.dumps(body, sort_keys=True)
        return hashlib.sha256(body_str.encode()).hexdigest()

    @staticmethod
    def compute_feature_hash(block_id: str, horizon_hours: float, features: dict) -> str:
        """Compute hash for cache lookup based on features."""
        cache_key = f"{block_id}:{horizon_hours}:{json.dumps(features, sort_keys=True)}"
        return hashlib.sha256(cache_key.encode()).hexdigest()

    @staticmethod
    def get_cached_recommendation(
        db: Session,
        tenant_id: str,
        idempotency_key: Optional[str],
        body_hash: str,
    ) -> Optional[Recommendation]:
        """
        Check for existing recommendation within idempotency window (24h).

        Returns cached recommendation if found.
        """
        if not idempotency_key:
            return None

        cutoff = datetime.utcnow() - timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS)

        existing = (
            db.query(Recommendation)
            .filter(
                and_(
                    Recommendation.tenant_id == tenant_id,
                    Recommendation.idempotency_key == idempotency_key,
                    Recommendation.body_hash == body_hash,
                    Recommendation.created_at >= cutoff,
                )
            )
            .order_by(Recommendation.created_at.desc())
            .first()
        )

        return existing

    @staticmethod
    def get_feature_cached_recommendation(
        db: Session,
        block_id: str,
        feature_hash: str,
    ) -> Optional[Recommendation]:
        """
        Check for cached recommendation based on features (6h TTL).

        Returns cached recommendation if features haven't changed significantly.
        """
        now = datetime.utcnow()

        cached = (
            db.query(Recommendation)
            .filter(
                and_(
                    Recommendation.block_id == block_id,
                    Recommendation.feature_hash == feature_hash,
                    Recommendation.expires_at > now,
                )
            )
            .order_by(Recommendation.created_at.desc())
            .first()
        )

        return cached

    @staticmethod
    def save_recommendation(
        db: Session,
        tenant_id: str,
        block_id: str,
        result: Dict,
        idempotency_key: Optional[str],
        body_hash: str,
        feature_hash: str,
        horizon_hours: float,
    ) -> Recommendation:
        """Save recommendation with idempotency and cache metadata."""
        import uuid

        rec = Recommendation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            block_id=block_id,
            idempotency_key=idempotency_key,
            body_hash=body_hash,
            feature_hash=feature_hash,
            when=result["when"],
            duration_min=result["duration_min"],
            volume_m3=result["volume_m3"],
            confidence=result["confidence"],
            horizon_hours=horizon_hours,
            explanations=result["explanations"],
            version=result["version"],
            expires_at=datetime.utcnow() + timedelta(hours=settings.CACHE_TTL_HOURS),
        )

        db.add(rec)
        db.commit()
        db.refresh(rec)

        return rec
