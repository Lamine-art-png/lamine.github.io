"""Persistent domain models for AGRO-AI Market Intelligence.

Money and quantities use fixed precision numerics.  Market observations always
carry provenance and a source state so synthetic/demo values can never be
mistaken for live market data.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint

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
    source_status = Column(String, nullable=False, index=True)  # LIVE/DELAYED/DEMO/STALE/UNAVAILABLE/NOT_CONFIGURED/MANUAL
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
    # Decision Journal v2 (alembic 042): what was known at decision time, what
    # was actually done, and what later happened versus the modelled result.
    evidence_snapshot_json = Column(JSON, nullable=True)
    action_taken = Column(Text, nullable=True)
    outcome_recorded_at = Column(DateTime, nullable=True)
    outcome_recorded_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
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


# ---------------------------------------------------------------------------
# Shared market-data plane (global, not tenant-scoped).
#
# One upstream observation (e.g. CONAB soybean, Mato Grosso, one week) is stored
# once and consumed by every tenant position that needs it. Rows here are public
# or licensed provider evidence only; tenant economics never enter these tables.
# ---------------------------------------------------------------------------


class MarketDataSeries(Base):
    __tablename__ = "market_data_series"
    __table_args__ = (
        UniqueConstraint("series_key", name="uq_market_data_series_key"),
        Index("ix_market_data_series_lookup", "observation_type", "commodity", "country_code"),
        Index("ix_market_data_series_provider", "provider", "status"),
    )

    id = Column(String, primary_key=True, default=_id)
    series_key = Column(String(400), nullable=False)
    provider = Column(String, nullable=False)
    source_name = Column(String, nullable=False)
    native_id = Column(String(400), nullable=True)
    observation_type = Column(String, nullable=False)  # physical_price | benchmark_price | fx_rate | reference_statistic
    commodity = Column(String, nullable=True)
    country_code = Column(String(2), nullable=True)
    region = Column(String, nullable=True)
    market_name = Column(String, nullable=True)
    price_basis = Column(String, nullable=True)  # e.g. producer_received, delivered_port, fob, mandi_modal
    unit = Column(String, nullable=True)  # canonical quantity unit for prices; "CCY per BASE" for FX
    currency = Column(String(3), nullable=True)
    base_currency = Column(String(3), nullable=True)  # FX only: value = currency units per one base_currency
    frequency = Column(String, nullable=False, default="daily")
    freshness_max_age_minutes = Column(Numeric(16, 2), nullable=False)
    last_known_max_age_minutes = Column(Numeric(16, 2), nullable=False)
    licensing_json = Column(JSON, nullable=False, default=dict)
    metadata_json = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, default="active")
    last_observed_at = Column(DateTime, nullable=True)
    last_retrieved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MarketDataPoint(Base):
    __tablename__ = "market_data_points"
    __table_args__ = (
        UniqueConstraint("series_id", "observed_at", name="uq_market_data_point_series_time"),
        Index("ix_market_data_point_series_time", "series_id", "observed_at"),
    )

    id = Column(String, primary_key=True, default=_id)
    series_id = Column(String, ForeignKey("market_data_series.id", ondelete="CASCADE"), nullable=False)
    observed_at = Column(DateTime, nullable=False)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    value = Column(Numeric(24, 10), nullable=False)
    raw_value = Column(String(120), nullable=True)
    source_status = Column(String, nullable=False)
    retrieved_at = Column(DateTime, nullable=False)
    content_hash = Column(String(64), nullable=False)
    revision = Column(Numeric(8, 0), nullable=False, default=0)
    upstream_ref = Column(String(600), nullable=True)
    quality_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MarketDataPointRevision(Base):
    """Append-only audit history of upstream corrections to a point.

    ``market_data_points`` keeps the latest value for efficient reads; every
    change of an already-stored upstream fact appends one row here and rows are
    never updated or deleted by the application.
    """

    __tablename__ = "market_data_point_revisions"
    __table_args__ = (
        UniqueConstraint("point_id", "revision", name="uq_market_point_revision"),
        Index("ix_market_point_revision_series_time", "series_id", "observed_at"),
    )

    id = Column(String, primary_key=True, default=_id)
    point_id = Column(String, ForeignKey("market_data_points.id", ondelete="CASCADE"), nullable=False, index=True)
    series_id = Column(String, ForeignKey("market_data_series.id", ondelete="CASCADE"), nullable=False)
    observed_at = Column(DateTime, nullable=False)
    revision = Column(Integer, nullable=False)
    previous_value = Column(Numeric(24, 10), nullable=False)
    new_value = Column(Numeric(24, 10), nullable=False)
    previous_raw_value = Column(String(120), nullable=True)
    new_raw_value = Column(String(120), nullable=True)
    previous_source_status = Column(String, nullable=True)
    new_source_status = Column(String, nullable=True)
    previous_content_hash = Column(String(64), nullable=False)
    new_content_hash = Column(String(64), nullable=False)
    previous_retrieved_at = Column(DateTime, nullable=True)
    revised_retrieved_at = Column(DateTime, nullable=False)
    provider_run_id = Column(String, ForeignKey("market_provider_runs.id", ondelete="SET NULL"), nullable=True)
    upstream_ref = Column(String(600), nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MarketProviderRun(Base):
    __tablename__ = "market_provider_runs"
    __table_args__ = (
        Index("ix_market_provider_run_provider_time", "provider", "started_at"),
        Index("ix_market_provider_run_demand_time", "provider", "demand_key", "started_at"),
    )

    id = Column(String, primary_key=True, default=_id)
    provider = Column(String, nullable=False)
    # sha256 of the canonical, sorted selector set; readable selectors live in trace_json.
    demand_key = Column(String(400), nullable=False)
    trigger = Column(String, nullable=False, default="scheduled")
    status = Column(String, nullable=False)  # ok | partial | unavailable | not_configured | skipped
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    observations_seen = Column(Numeric(12, 0), nullable=False, default=0)
    points_inserted = Column(Numeric(12, 0), nullable=False, default=0)
    points_revised = Column(Numeric(12, 0), nullable=False, default=0)
    duplicates = Column(Numeric(12, 0), nullable=False, default=0)
    error_class = Column(String, nullable=True)
    trace_json = Column(JSON, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# Tenant-private commercial intelligence state.
# ---------------------------------------------------------------------------


class MarketPositionSnapshot(Base):
    __tablename__ = "market_position_snapshots"
    __table_args__ = (Index("ix_market_snapshot_org_position_time", "organization_id", "position_id", "computed_at"),)

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(String, ForeignKey("market_positions.id", ondelete="CASCADE"), nullable=False, index=True)
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    inputs_hash = Column(String(64), nullable=False)
    inputs_json = Column(JSON, nullable=False)
    payload_json = Column(JSON, nullable=False)
    evidence_json = Column(JSON, nullable=False, default=dict)
    calculation_version = Column(String, nullable=False)


class MarketMaterialityEvent(Base):
    __tablename__ = "market_materiality_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "dedupe_key", name="uq_market_materiality_org_dedupe"),
        Index("ix_market_materiality_org_status_time", "organization_id", "status", "created_at"),
        Index("ix_market_materiality_position_kind_time", "position_id", "kind", "created_at"),
    )

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(String, ForeignKey("market_positions.id", ondelete="CASCADE"), nullable=False, index=True)
    dedupe_key = Column(String(64), nullable=False)
    kind = Column(String, nullable=False)
    level = Column(String, nullable=False)  # LOW | MEDIUM | HIGH | CRITICAL
    status = Column(String, nullable=False, default="open")  # open | acknowledged | resolved
    title_key = Column(String, nullable=False)
    reasons_json = Column(JSON, nullable=False)
    impact_json = Column(JSON, nullable=False)
    data_quality_json = Column(JSON, nullable=False, default=dict)
    reference_snapshot_id = Column(String, ForeignKey("market_position_snapshots.id", ondelete="SET NULL"), nullable=True)
    current_snapshot_id = Column(String, ForeignKey("market_position_snapshots.id", ondelete="SET NULL"), nullable=True)
    methodology_version = Column(String, nullable=False)
    notified_json = Column(JSON, nullable=False, default=dict)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MarketPositionFieldLink(Base):
    __tablename__ = "market_position_field_links"
    __table_args__ = (
        UniqueConstraint("position_id", "field_entity_id", name="uq_market_position_field"),
        Index("ix_market_position_field_org", "organization_id", "position_id"),
    )

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    position_id = Column(String, ForeignKey("market_positions.id", ondelete="CASCADE"), nullable=False)
    field_entity_id = Column(String, ForeignKey("managed_entities.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MarketCycleOrganizationState(Base):
    """Per-organization scheduling state for the Commercial Intelligence cycle.

    The scheduler enqueues organizations oldest-due first (never-run first, then
    the oldest successful completion), so a large tenant population cannot
    starve later organizations.
    """

    __tablename__ = "market_cycle_organization_state"

    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    last_enqueued_at = Column(DateTime, nullable=True)
    last_started_at = Column(DateTime, nullable=True)
    last_completed_at = Column(DateTime, nullable=True, index=True)
    last_status = Column(String, nullable=True)
    last_job_id = Column(String, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MarketAlertDelivery(Base):
    """One alert channel delivery per event and recipient.

    Attempts are recorded separately from success: ``delivered_at`` is set only
    when the provider accepted the message; failures retry on a bounded backoff
    and an unsupported recipient language is an explicit terminal deferral.
    """

    __tablename__ = "market_alert_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", "channel", name="uq_market_alert_delivery"),
        Index("ix_market_alert_delivery_due", "status", "next_attempt_at"),
    )

    id = Column(String, primary_key=True, default=_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String, ForeignKey("market_materiality_events.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String, nullable=False, default="email")
    # pending | retrying | delivered | failed | deferred_unsupported_language | cancelled_alert_closed
    status = Column(String, nullable=False, default="pending")
    language = Column(String(16), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    last_error = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
