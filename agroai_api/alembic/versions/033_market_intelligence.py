"""Global Market Intelligence domain tables.

Revision ID: 033_market_intelligence
Revises: 032_repair_onboarding_state
Create Date: 2026-09-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "033_market_intelligence"
down_revision = "032_repair_onboarding_state"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index(name: str, table: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    tables = _tables()
    money = sa.Numeric(24, 8)
    fx = sa.Numeric(24, 10)

    if "market_positions" not in tables:
        op.create_table(
            "market_positions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("position_key", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("commodity", sa.String(), nullable=False),
            sa.Column("season", sa.String(), nullable=False),
            sa.Column("country_code", sa.String(length=2), nullable=False),
            sa.Column("region", sa.String(), nullable=True),
            sa.Column("market_structure", sa.String(), nullable=False, server_default="physical"),
            sa.Column("local_currency", sa.String(length=3), nullable=False),
            sa.Column("reporting_currency", sa.String(length=3), nullable=False),
            sa.Column("quantity_unit", sa.String(), nullable=False),
            sa.Column("expected_production", money, nullable=False),
            sa.Column("inventory_quantity", money, nullable=False, server_default="0"),
            sa.Column("production_cost_per_unit", money, nullable=True),
            sa.Column("current_realizable_price", money, nullable=True),
            sa.Column("price_currency", sa.String(length=3), nullable=True),
            sa.Column("fx_rate_to_reporting", fx, nullable=True),
            sa.Column("freight_per_unit", money, nullable=False, server_default="0"),
            sa.Column("storage_per_unit", money, nullable=False, server_default="0"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "position_key", name="uq_market_position_org_key"),
        )
    for name, cols in {
        "ix_market_positions_organization_id": ["organization_id"],
        "ix_market_positions_workspace_id": ["workspace_id"],
        "ix_market_positions_position_key": ["position_key"],
        "ix_market_positions_commodity": ["commodity"],
        "ix_market_positions_season": ["season"],
        "ix_market_positions_country_code": ["country_code"],
        "ix_market_positions_status": ["status"],
        "ix_market_position_org_commodity_season": ["organization_id", "commodity", "season"],
    }.items():
        _index(name, "market_positions", cols)

    if "market_contract_positions" not in tables:
        op.create_table(
            "market_contract_positions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("position_id", sa.String(), nullable=False),
            sa.Column("contract_code", sa.String(), nullable=False),
            sa.Column("buyer", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("quantity", money, nullable=False),
            sa.Column("quantity_unit", sa.String(), nullable=False),
            sa.Column("price", money, nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("fx_rate_to_reporting", fx, nullable=True),
            sa.Column("delivery_start", sa.DateTime(), nullable=True),
            sa.Column("delivery_end", sa.DateTime(), nullable=True),
            sa.Column("delivery_location", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["position_id"], ["market_positions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "contract_code", name="uq_market_contract_org_code"),
        )
    for name, cols in {
        "ix_market_contract_positions_organization_id": ["organization_id"],
        "ix_market_contract_positions_position_id": ["position_id"],
        "ix_market_contract_positions_contract_code": ["contract_code"],
        "ix_market_contract_positions_status": ["status"],
        "ix_market_contract_org_position": ["organization_id", "position_id"],
    }.items():
        _index(name, "market_contract_positions", cols)

    if "market_observations" not in tables:
        op.create_table(
            "market_observations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("position_id", sa.String(), nullable=True),
            sa.Column("evidence_id", sa.String(), nullable=False),
            sa.Column("observation_type", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("source_name", sa.String(), nullable=False),
            sa.Column("source_status", sa.String(), nullable=False),
            sa.Column("value", fx, nullable=True),
            sa.Column("unit", sa.String(), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=True),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("retrieved_at", sa.DateTime(), nullable=False),
            sa.Column("delay_minutes", sa.Numeric(16, 4), nullable=True),
            sa.Column("quality_json", sa.JSON(), nullable=True),
            sa.Column("licensing_json", sa.JSON(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["position_id"], ["market_positions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "evidence_id", name="uq_market_observation_org_evidence"),
        )
    for name, cols in {
        "ix_market_observations_organization_id": ["organization_id"],
        "ix_market_observations_position_id": ["position_id"],
        "ix_market_observations_evidence_id": ["evidence_id"],
        "ix_market_observations_observation_type": ["observation_type"],
        "ix_market_observations_provider": ["provider"],
        "ix_market_observations_source_status": ["source_status"],
        "ix_market_observations_observed_at": ["observed_at"],
        "ix_market_observations_retrieved_at": ["retrieved_at"],
        "ix_market_observation_position_time": ["position_id", "observed_at"],
        "ix_market_observation_org_type_time": ["organization_id", "observation_type", "observed_at"],
    }.items():
        _index(name, "market_observations", cols)

    if "market_scenarios" not in tables:
        op.create_table(
            "market_scenarios",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("position_id", sa.String(), nullable=False),
            sa.Column("created_by_user_id", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("assumptions_json", sa.JSON(), nullable=False),
            sa.Column("baseline_json", sa.JSON(), nullable=False),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.Column("calculation_version", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["position_id"], ["market_positions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in {
        "ix_market_scenarios_organization_id": ["organization_id"],
        "ix_market_scenarios_position_id": ["position_id"],
        "ix_market_scenarios_created_by_user_id": ["created_by_user_id"],
        "ix_market_scenarios_created_at": ["created_at"],
        "ix_market_scenario_org_position_time": ["organization_id", "position_id", "created_at"],
    }.items():
        _index(name, "market_scenarios", cols)

    if "market_decision_journal" not in tables:
        op.create_table(
            "market_decision_journal",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("position_id", sa.String(), nullable=False),
            sa.Column("scenario_id", sa.String(), nullable=True),
            sa.Column("created_by_user_id", sa.String(), nullable=True),
            sa.Column("decision", sa.Text(), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("assumptions_json", sa.JSON(), nullable=True),
            sa.Column("outcome_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["position_id"], ["market_positions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scenario_id"], ["market_scenarios.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in {
        "ix_market_decision_journal_organization_id": ["organization_id"],
        "ix_market_decision_journal_position_id": ["position_id"],
        "ix_market_decision_journal_scenario_id": ["scenario_id"],
        "ix_market_decision_journal_created_at": ["created_at"],
        "ix_market_decision_org_position_time": ["organization_id", "position_id", "created_at"],
    }.items():
        _index(name, "market_decision_journal", cols)

    if "market_intelligence_insights" not in tables:
        op.create_table(
            "market_intelligence_insights",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("position_id", sa.String(), nullable=True),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("importance", sa.String(), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("confidence_json", sa.JSON(), nullable=False),
            sa.Column("model_trace_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["position_id"], ["market_positions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in {
        "ix_market_intelligence_insights_organization_id": ["organization_id"],
        "ix_market_intelligence_insights_position_id": ["position_id"],
        "ix_market_intelligence_insights_kind": ["kind"],
        "ix_market_intelligence_insights_importance": ["importance"],
        "ix_market_intelligence_insights_created_at": ["created_at"],
        "ix_market_insight_org_position_time": ["organization_id", "position_id", "created_at"],
    }.items():
        _index(name, "market_intelligence_insights", cols)


def downgrade() -> None:
    for table in (
        "market_intelligence_insights",
        "market_decision_journal",
        "market_scenarios",
        "market_observations",
        "market_contract_positions",
        "market_positions",
    ):
        if table in _tables():
            op.drop_table(table)
