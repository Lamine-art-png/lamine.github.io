from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


def _id() -> str:
    return str(uuid.uuid4())


class IntelligenceWallet(Base):
    __tablename__ = "platform_intelligence_wallets"

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    currency = Column(String(3), nullable=False, default="usd")
    balance_cents = Column(Integer, nullable=False, default=0)
    lifetime_funded_cents = Column(Integer, nullable=False, default=0)
    lifetime_spent_cents = Column(Integer, nullable=False, default=0)
    auto_reload_enabled = Column(Boolean, nullable=False, default=False)
    auto_reload_threshold_cents = Column(Integer, nullable=True)
    auto_reload_amount_cents = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class IntelligenceWalletLedger(Base):
    __tablename__ = "platform_intelligence_wallet_ledger"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_intelligence_wallet_ledger_idempotency"),
        UniqueConstraint("external_reference", name="uq_intelligence_wallet_ledger_external_reference"),
        Index("ix_intelligence_wallet_ledger_org_time", "organization_id", "created_at"),
        Index("ix_intelligence_wallet_ledger_status", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    wallet_id = Column(String, ForeignKey("platform_intelligence_wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    amount_cents = Column(Integer, nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    external_reference = Column(String, nullable=True)
    intelligence_run_id = Column(String, nullable=True, index=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    posted_at = Column(DateTime, nullable=True)


class CommercialIntelligenceRun(Base):
    __tablename__ = "platform_commercial_intelligence_runs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "api_project_id",
            "idempotency_key",
            name="uq_commercial_intelligence_run_idempotency",
        ),
        Index("ix_commercial_intelligence_run_org_time", "organization_id", "created_at"),
        Index("ix_commercial_intelligence_run_project_time", "api_project_id", "created_at"),
        Index("ix_commercial_intelligence_run_status", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key_id = Column(String, ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    field_id = Column(String, nullable=True, index=True)
    idempotency_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    task = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False)
    public_model = Column(String, nullable=False, default="agroai-intelligence-1")
    status = Column(String, nullable=False, default="processing", index=True)
    charge_cents = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="usd")
    request_safe_json = Column(JSON, nullable=False, default=dict)
    response_json = Column(JSON, nullable=True)
    provider_internal = Column(String, nullable=True)
    model_internal = Column(String, nullable=True)
    error_code = Column(String, nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
