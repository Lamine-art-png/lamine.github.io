"""Execution assurance API — verification status, outcome history, anomalies.

Exposes the Phase 2 execution verification loop:
- Per-block verification status
- Recommendation outcome history
- Anomaly and deviation feeds
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.decision_run import DecisionRun
from app.models.execution_verification import ExecutionVerification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/execution", tags=["execution-assurance"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class DecisionRunResponse(BaseModel):
    id: str
    block_id: str
    status: str
    recommendation_id: str
    schedule_id: Optional[str] = None
    verification_id: Optional[str] = None
    planned_start: datetime
    planned_duration_min: float
    planned_volume_m3: float
    actual_start: Optional[datetime] = None
    actual_duration_min: Optional[float] = None
    actual_volume_m3: Optional[float] = None
    provider: Optional[str] = None
    engine_version: Optional[str] = None
    recommended_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None


class VerificationResponse(BaseModel):
    id: str
    block_id: str
    decision_run_id: str
    outcome: str
    deviation_reasons: List[str] = []
    verification_status: str
    duration_deviation_pct: Optional[float] = None
    volume_deviation_pct: Optional[float] = None
    start_delay_minutes: Optional[float] = None
    pre_irrigation_vwc: Optional[float] = None
    post_24h_vwc: Optional[float] = None
    post_48h_vwc: Optional[float] = None
    vwc_delta_24h: Optional[float] = None
    vwc_delta_48h: Optional[float] = None
    effectiveness_score: Optional[float] = None
    confidence: Optional[float] = None
    verifier_version: str
    verified_at: Optional[datetime] = None


class BlockOutcomeSummary(BaseModel):
    block_id: str
    total_decisions: int
    matched: int
    partially_matched: int
    deviated: int
    failed: int
    agronomically_ineffective: int
    avg_effectiveness: Optional[float] = None
    avg_duration_deviation_pct: Optional[float] = None
    avg_volume_deviation_pct: Optional[float] = None


class AnomalyItem(BaseModel):
    decision_run_id: str
    block_id: str
    outcome: str
    deviation_reasons: List[str]
    effectiveness_score: Optional[float] = None
    verified_at: Optional[datetime] = None


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/blocks/{block_id}/decisions", response_model=List[DecisionRunResponse])
def list_decision_runs(
    block_id: str,
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List decision runs for a block, optionally filtered by status."""
    query = db.query(DecisionRun).filter(DecisionRun.block_id == block_id)
    if status:
        query = query.filter(DecisionRun.status == status)
    runs = query.order_by(desc(DecisionRun.recommended_at)).limit(limit).all()

    return [
        DecisionRunResponse(
            id=r.id,
            block_id=r.block_id,
            status=r.status,
            recommendation_id=r.recommendation_id,
            schedule_id=r.schedule_id,
            verification_id=r.verification_id,
            planned_start=r.planned_start,
            planned_duration_min=r.planned_duration_min,
            planned_volume_m3=r.planned_volume_m3,
            actual_start=r.actual_start,
            actual_duration_min=r.actual_duration_min,
            actual_volume_m3=r.actual_volume_m3,
            provider=r.provider,
            engine_version=r.engine_version,
            recommended_at=r.recommended_at,
            verified_at=r.verified_at,
        )
        for r in runs
    ]


@router.get(
    "/blocks/{block_id}/verifications",
    response_model=List[VerificationResponse],
)
def list_verifications(
    block_id: str,
    outcome: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List execution verifications for a block."""
    query = db.query(ExecutionVerification).filter(
        ExecutionVerification.block_id == block_id
    )
    if outcome:
        query = query.filter(ExecutionVerification.outcome == outcome)
    evs = query.order_by(desc(ExecutionVerification.verified_at)).limit(limit).all()

    return [
        VerificationResponse(
            id=ev.id,
            block_id=ev.block_id,
            decision_run_id=ev.decision_run_id,
            outcome=ev.outcome,
            deviation_reasons=ev.deviation_reasons or [],
            verification_status=ev.verification_status,
            duration_deviation_pct=ev.duration_deviation_pct,
            volume_deviation_pct=ev.volume_deviation_pct,
            start_delay_minutes=ev.start_delay_minutes,
            pre_irrigation_vwc=ev.pre_irrigation_vwc,
            post_24h_vwc=ev.post_24h_vwc,
            post_48h_vwc=ev.post_48h_vwc,
            vwc_delta_24h=ev.vwc_delta_24h,
            vwc_delta_48h=ev.vwc_delta_48h,
            effectiveness_score=ev.effectiveness_score,
            confidence=ev.confidence,
            verifier_version=ev.verifier_version,
            verified_at=ev.verified_at,
        )
        for ev in evs
    ]


@router.get(
    "/blocks/{block_id}/outcome-summary",
    response_model=BlockOutcomeSummary,
)
def get_outcome_summary(
    block_id: str,
    db: Session = Depends(get_db),
):
    """Aggregated outcome summary for a block."""
    evs = (
        db.query(ExecutionVerification)
        .filter(ExecutionVerification.block_id == block_id)
        .all()
    )

    summary = {
        "matched": 0,
        "partially_matched": 0,
        "deviated": 0,
        "failed": 0,
        "agronomically_ineffective": 0,
    }
    effectiveness_scores = []
    dur_devs = []
    vol_devs = []

    for ev in evs:
        if ev.outcome in summary:
            summary[ev.outcome] += 1
        if ev.effectiveness_score is not None:
            effectiveness_scores.append(ev.effectiveness_score)
        if ev.duration_deviation_pct is not None:
            dur_devs.append(ev.duration_deviation_pct)
        if ev.volume_deviation_pct is not None:
            vol_devs.append(ev.volume_deviation_pct)

    return BlockOutcomeSummary(
        block_id=block_id,
        total_decisions=len(evs),
        **summary,
        avg_effectiveness=(
            round(sum(effectiveness_scores) / len(effectiveness_scores), 3)
            if effectiveness_scores else None
        ),
        avg_duration_deviation_pct=(
            round(sum(dur_devs) / len(dur_devs), 1)
            if dur_devs else None
        ),
        avg_volume_deviation_pct=(
            round(sum(vol_devs) / len(vol_devs), 1)
            if vol_devs else None
        ),
    )


@router.get("/anomalies", response_model=List[AnomalyItem])
def list_anomalies(
    tenant_id: str = "wiseconn-demo",
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List recent anomalous verifications (deviated, failed, ineffective)."""
    evs = (
        db.query(ExecutionVerification)
        .filter(
            and_(
                ExecutionVerification.tenant_id == tenant_id,
                ExecutionVerification.outcome.in_([
                    "deviated",
                    "failed",
                    "agronomically_ineffective",
                ]),
            )
        )
        .order_by(desc(ExecutionVerification.verified_at))
        .limit(limit)
        .all()
    )

    return [
        AnomalyItem(
            decision_run_id=ev.decision_run_id,
            block_id=ev.block_id,
            outcome=ev.outcome,
            deviation_reasons=ev.deviation_reasons or [],
            effectiveness_score=ev.effectiveness_score,
            verified_at=ev.verified_at,
        )
        for ev in evs
    ]
