"""Evaluation context seeding for product-ready AGRO-AI intelligence.

This creates honest evaluation_sample field context. It does not claim live
WiseConn, Talgil, OpenET, or weather integrations are connected.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.block import Block
from app.models.recommendation import Recommendation
from app.models.saas import Organization, Workspace
from app.models.telemetry import Telemetry
from app.models.tenant import Tenant


def _id() -> str:
    return str(uuid.uuid4())


def ensure_evaluation_context(
    db: Session,
    org: Organization,
    workspace: Workspace | None = None,
) -> dict[str, str | None]:
    """Ensure an org has a safe starter field context for AI diagnosis.

    Idempotent. Existing customer/live data is preserved.
    """
    tenant = db.get(Tenant, org.id)
    if tenant is None:
        tenant = Tenant(
            id=org.id,
            name=org.name,
            email=None,
            tier=org.plan or "free",
            active=True,
        )
        db.add(tenant)
        db.flush()

    if workspace is None:
        workspace = (
            db.query(Workspace)
            .filter(Workspace.organization_id == org.id)
            .order_by(Workspace.created_at.asc())
            .first()
        )
        if workspace is None:
            workspace = Workspace(
                organization_id=org.id,
                name="Evaluation workspace",
                crop="wine grapes",
                region="California",
                mode="evaluation",
            )
            db.add(workspace)
            db.flush()

    block = db.query(Block).filter(Block.tenant_id == org.id).first()
    if block is None:
        block = Block(
            id=_id(),
            tenant_id=org.id,
            name="Evaluation Block",
            area_ha=12.0,
            crop_type=workspace.crop or "wine grapes",
            soil_type="loam",
            latitude=38.2975,
            longitude=-122.2869,
            config={
                "source": "evaluation_sample",
                "workspace_id": workspace.id,
                "region": workspace.region or "California",
                "sample_notice": (
                    "Evaluation sample only. Connect live telemetry before "
                    "using recommendations operationally."
                ),
                "integration_readiness": {
                    "wiseconn": {
                        "status": "missing_credentials",
                        "next_step": "Add WiseConn API credentials or upload exports.",
                    },
                    "talgil": {
                        "status": "missing_credentials",
                        "next_step": "Add Talgil API credentials or upload exports.",
                    },
                    "manual_upload": {
                        "status": "available",
                        "next_step": "Upload recent irrigation, ET, flow, and soil records.",
                    },
                    "public_weather": {
                        "status": "not_configured",
                        "next_step": "Configure weather/public data source.",
                    },
                },
            },
            water_budget_allocated=36000.0,
            water_budget_used=16400.0,
        )
        db.add(block)
        db.flush()

    enriched_config = dict(block.config or {})
    enriched_config.setdefault("source", "evaluation_sample")
    enriched_config.setdefault(
        "sample_notice",
        "Evaluation sample only. Connect live data before operational use.",
    )
    enriched_config.setdefault(
        "assurance_readiness",
        {
            "status": "evaluation_ready",
            "operational_use": False,
            "missing_before_live": [
                "live controller credentials",
                "recent live telemetry",
                "verified water budget",
                "operator approval trail",
            ],
        },
    )
    enriched_config.setdefault(
        "evidence_sources",
        [
            {
                "name": "Evaluation telemetry sample",
                "status": "available",
                "source": "evaluation_sample",
                "operational_use": False,
            },
            {
                "name": "Controller integration",
                "status": "missing_credentials",
                "source": "live_required",
                "operational_use": False,
            },
            {
                "name": "Manual evidence upload",
                "status": "available",
                "source": "operator_upload",
                "operational_use": False,
            },
        ],
    )
    enriched_config.setdefault(
        "report_readiness",
        {
            "status": "draft_ready_from_evaluation_sample",
            "operational_use": False,
            "missing_for_certified_report": [
                "live source credentials",
                "recent controller events",
                "reviewer approval",
            ],
        },
    )
    block.config = enriched_config

    telemetry_exists = (
        db.query(Telemetry.id)
        .filter(and_(Telemetry.tenant_id == org.id, Telemetry.block_id == block.id))
        .first()
        is not None
    )
    if not telemetry_exists:
        now = datetime.utcnow()
        rows = [
            ("soil_vwc", now - timedelta(hours=2), 24.8, "%", "evaluation_sample"),
            ("et0", now - timedelta(hours=6), 4.1, "mm/day", "evaluation_sample"),
            ("flow", now - timedelta(hours=10), 18.6, "m3/hour", "evaluation_sample"),
            ("weather", now - timedelta(hours=3), 27.2, "C", "evaluation_sample"),
            ("valve_state", now - timedelta(hours=1), 1.0, "open_flag", "evaluation_sample"),
            ("soil_vwc", now - timedelta(days=1), 23.4, "%", "evaluation_sample"),
        ]
        for kind, ts, value, unit, source in rows:
            db.add(
                Telemetry(
                    id=_id(),
                    tenant_id=org.id,
                    block_id=block.id,
                    type=kind,
                    timestamp=ts,
                    value=value,
                    unit=unit,
                    source=source,
                    meta_data={
                        "source": "evaluation_sample",
                        "workspace_id": workspace.id,
                        "operational_use": False,
                    },
                )
            )
        db.flush()

    required_telemetry_rows = [
        ("soil_vwc", datetime.utcnow() - timedelta(hours=2), 24.8, "%"),
        ("et0", datetime.utcnow() - timedelta(hours=6), 4.1, "mm/day"),
        ("flow", datetime.utcnow() - timedelta(hours=10), 18.6, "m3/hour"),
        ("weather", datetime.utcnow() - timedelta(hours=3), 27.2, "C"),
        ("valve_state", datetime.utcnow() - timedelta(hours=1), 1.0, "open_flag"),
    ]
    for kind, ts, value, unit in required_telemetry_rows:
        exists = (
            db.query(Telemetry.id)
            .filter(
                and_(
                    Telemetry.tenant_id == org.id,
                    Telemetry.block_id == block.id,
                    Telemetry.type == kind,
                )
            )
            .first()
        )
        if exists:
            continue
        db.add(
            Telemetry(
                id=_id(),
                tenant_id=org.id,
                block_id=block.id,
                type=kind,
                timestamp=ts,
                value=value,
                unit=unit,
                source="evaluation_sample",
                meta_data={
                    "source": "evaluation_sample",
                    "workspace_id": workspace.id,
                    "operational_use": False,
                    "sample_notice": "Evaluation sample only. Connect live data before operational use.",
                },
            )
        )
    db.flush()

    recommendation_exists = (
        db.query(Recommendation.id)
        .filter(and_(Recommendation.tenant_id == org.id, Recommendation.block_id == block.id))
        .first()
        is not None
    )
    if not recommendation_exists:
        now = datetime.utcnow()
        db.add(
            Recommendation(
                id=_id(),
                tenant_id=org.id,
                block_id=block.id,
                idempotency_key="evaluation-sample-starter",
                body_hash="evaluation-sample-starter",
                feature_hash="evaluation-sample-starter",
                when=now + timedelta(hours=18),
                duration_min=42.0,
                volume_m3=88.0,
                confidence=0.62,
                horizon_hours=48.0,
                explanations=[
                    "Evaluation sample context is present for product walkthrough.",
                    "Connect live telemetry before making operational irrigation decisions.",
                    "Current sample suggests monitoring soil VWC and ET trend before scheduling irrigation.",
                ],
                version="evaluation-sample-v1",
                meta_data={
                    "source": "evaluation_sample",
                    "workspace_id": workspace.id,
                    "operational_use": False,
                    "required_before_operational_use": [
                        "live controller credentials",
                        "recent telemetry",
                        "confirmed crop/block/water budget",
                    ],
                },
                expires_at=now + timedelta(days=7),
            )
        )
        db.flush()

    return {"workspace_id": workspace.id, "block_id": block.id}
