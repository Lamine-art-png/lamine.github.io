from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


def _id() -> str:
    return str(uuid.uuid4())


class IntelligenceWallet(Base):
    __tablename__ = "platform_intelligence_wallets"
    # Mirrors alembic 040_intelligence_money_checks.
    __table_args__ = (
        CheckConstraint("balance_cents >= 0", name="ck_intelligence_wallet_balance_nonnegative"),
        CheckConstraint("lifetime_funded_cents >= 0", name="ck_intelligence_wallet_funded_nonnegative"),
        CheckConstraint("lifetime_spent_cents >= 0", name="ck_intelligence_wallet_spent_nonnegative"),
    )

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
        CheckConstraint(
            "(kind = 'intelligence_charge' AND amount_cents < 0)"
            " OR (kind IN ('topup', 'intelligence_refund') AND amount_cents > 0)"
            " OR kind NOT IN ('intelligence_charge', 'topup', 'intelligence_refund')",
            name="ck_intelligence_wallet_ledger_amount_sign",
        ),
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
        Index("ix_commercial_intelligence_run_session_id", "session_id"),
        Index("ix_commercial_intelligence_run_job_queue", "execution", "status", "next_attempt_at"),
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
    # Intelligence Platform v1 (alembic 042). A run is either a synchronous
    # request or an asynchronous job; both share one idempotency namespace and
    # one money path.
    execution = Column(String(16), nullable=False, default="sync", server_default="sync")
    session_id = Column(String, nullable=True)
    request_id = Column(String(64), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    started_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    # Full validated request, held only while an async job is pending and
    # cleared when the job reaches a terminal state.
    request_payload_json = Column(JSON, nullable=True)
    tool_calls_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    latency_ms = Column(Integer, nullable=True)
