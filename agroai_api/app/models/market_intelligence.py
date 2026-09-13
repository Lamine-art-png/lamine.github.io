"""Persistent domain models for AGRO-AI Market Intelligence.

Money and quantities use fixed precision numerics.  Market observations always
carry provenance and a source state so synthetic/demo values can never be
mistaken for live market data.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint

from app.db.base import Base


def _id() -> str:
    return str(uuid.uuid4())


class MarketPosition(Base):
    __tablename__ = "market_positions"
    __table_args__ = (
        UniqueConstraint("organization_id", "position_key", name="uq_market_position_org_key"),
        Index("ix_market_position_org_commodity_season", "organization_id", "commodity", "season"),
    )

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    position_key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    commodity = Column(String, nullable=False, index=True)
    season = Column(String, nullable=False, index=True)
    country_code = Column(String(2), nullable=False, index=True)
    region = Column(String, nullable=True)
    market_structure = Column(String, default="physical", nullable=False, index=True)  # physical | futures | hybrid
    local_currency = Column(String(3), nullable=False)
    reporting_currency = Column(String(3), nullable=False)
    quantity_unit = Column(String, nullable=False)
    expected_production = Column(Numeric(24, 8), nullable=False)
    inventory_quantity = Column(Numeric(24, 8), nullable=False, default=0)
    production_cost_per_unit = Column(Numeric(24, 8), nullable=True)
    current_realizable_price = Column(Numeric(24, 8), nullable=True)
    price_currency = Column(String(3), nullable=True)
    fx_rate_to_reporting = Column(Numeric(24, 10), nullable=True)
    freight_per_unit = Column(Numeric(24, 8), nullable=False, default=0)
    storage_per_unit = Column(Numeric(24, 8), nullable=False, default=0)
    status = Column(String, default="active", nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MarketContractPosition(Base):
    __tablename__ = "market_contract_positions"
    __table_args__ = (
        UniqueConstraint("organization_id", "contract_code", name="uq_market_contract_org_code"),
        Index("ix_market_contract_org_position", "organization_id", "position_id"),
    )

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(String, ForeignKey("market_positions.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_code = Column(String, nullable=False, index=True)
    buyer = Column(String, nullable=True)
    status = Column(String, default="active", nullable=False, index=True)
    quantity = Column(Numeric(24, 8), nullable=False)
    quantity_unit = Column(String, nullable=False)
    price = Column(Numeric(24, 8), nullable=False)
    currency = Column(String(3), nullable=False)
    fx_rate_to_reporting = Column(Numeric(24, 10), nullable=True)
    delivery_start = Column(DateTime, nullable=True)
    delivery_end = Column(DateTime, nullable=True)
    delivery_location = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MarketObservation(Base):
    __tablename__ = "market_observations"
    __table_args__ = (
        UniqueConstraint("organization_id", "evidence_id", name="uq_market_observation_org_evidence"),
        Index("ix_market_observation_position_time", "position_id", "observed_at"),
        Index("ix_market_observation_org_type_time", "organization_id", "observation_type", "observed_at"),
    )

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(String, ForeignKey("market_positions.id", ondelete="CASCADE"), nullable=True, index=True)
    evidence_id = Column(String, nullable=False, index=True)
    observation_type = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    source_name = Column(String, nullable=False)
    source_status = Column(String, nullable=False, index=True)  # LIVE/DELAYED/DEMO/STALE/UNAVAILABLE/NOT_CONFIGURED
    value = Column(Numeric(24, 10), nullable=True)
    unit = Column(String, nullable=True)
    currency = Column(String(3), nullable=True)
    observed_at = Column(DateTime, nullable=False, index=True)
    retrieved_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    delay_minutes = Column(Numeric(16, 4), nullable=True)
    quality_json = Column(JSON, nullable=True)
    licensing_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)


class MarketScenario(Base):
    __tablename__ = "market_scenarios"
    __table_args__ = (Index("ix_market_scenario_org_position_time", "organization_id", "position_id", "created_at"),)

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(String, ForeignKey("market_positions.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String, nullable=False)
    assumptions_json = Column(JSON, nullable=False)
    baseline_json = Column(JSON, nullable=False)
    result_json = Column(JSON, nullable=False)
    calculation_version = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MarketDecisionJournalEntry(Base):
    __tablename__ = "market_decision_journal"
    __table_args__ = (Index("ix_market_decision_org_position_time", "organization_id", "position_id", "created_at"),)

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(String, ForeignKey("market_positions.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_id = Column(String, ForeignKey("market_scenarios.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    decision = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    assumptions_json = Column(JSON, nullable=True)
    outcome_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MarketIntelligenceInsight(Base):
    __tablename__ = "market_intelligence_insights"
    __table_args__ = (Index("ix_market_insight_org_position_time", "organization_id", "position_id", "created_at"),)

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(String, ForeignKey("market_positions.id", ondelete="CASCADE"), nullable=True, index=True)
    kind = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    importance = Column(String, nullable=False, index=True)
    evidence_json = Column(JSON, nullable=False)
    confidence_json = Column(JSON, nullable=False)
    model_trace_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
