"""Shared market-data plane and tenant commercial intelligence state.

Global (not tenant-scoped) provider evidence:
- market_data_series: one row per upstream series (provider + native identity).
- market_data_points: time-series observations, unique per series and time, so
  re-ingesting the same upstream fact is idempotent and every tenant reads the
  same governed point instead of re-fetching it.
- market_provider_runs: ingestion runs for provider health and auditability,
  keyed by a sha256 of the canonical selector set.
- market_data_point_revisions: append-only audit history of upstream
  corrections (the point row keeps the latest value for fast reads).

Tenant-private state:
- market_position_snapshots: deterministic economics at a point in time for
  change detection ("what changed since yesterday").
- market_materiality_events: explainable material changes, deduplicated.
- market_position_field_links: commercial positions linked to AGRO-AI fields.
- market_cycle_organization_state: oldest-due fair scheduling of the cycle.
- market_alert_deliveries: per-recipient alert delivery attempts and outcome.
- Decision Journal v2 columns on market_decision_journal.

Revision ID: 042_market_data_plane
Revises: 041_abuse_project_holds
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "042_market_data_plane"
down_revision = "041_abuse_project_holds"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _index(name: str, table: str, columns: list[str]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    tables = _tables()
    value = sa.Numeric(24, 10)

    if "market_data_series" not in tables:
        op.create_table(
            "market_data_series",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("series_key", sa.String(400), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("source_name", sa.String(), nullable=False),
            sa.Column("native_id", sa.String(400), nullable=True),
            sa.Column("observation_type", sa.String(), nullable=False),
            sa.Column("commodity", sa.String(), nullable=True),
            sa.Column("country_code", sa.String(2), nullable=True),
            sa.Column("region", sa.String(), nullable=True),
            sa.Column("market_name", sa.String(), nullable=True),
            sa.Column("price_basis", sa.String(), nullable=True),
            sa.Column("unit", sa.String(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("base_currency", sa.String(3), nullable=True),
            sa.Column("frequency", sa.String(), nullable=False),
            sa.Column("freshness_max_age_minutes", sa.Numeric(16, 2), nullable=False),
            sa.Column("last_known_max_age_minutes", sa.Numeric(16, 2), nullable=False),
            sa.Column("licensing_json", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("last_observed_at", sa.DateTime(), nullable=True),
            sa.Column("last_retrieved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("series_key", name="uq_market_data_series_key"),
        )
    _index("ix_market_data_series_lookup", "market_data_series", ["observation_type", "commodity", "country_code"])
    _index("ix_market_data_series_provider", "market_data_series", ["provider", "status"])

    if "market_data_points" not in tables:
        op.create_table(
            "market_data_points",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("series_id", sa.String(), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("period_start", sa.DateTime(), nullable=True),
            sa.Column("period_end", sa.DateTime(), nullable=True),
            sa.Column("value", value, nullable=False),
            sa.Column("raw_value", sa.String(120), nullable=True),
            sa.Column("source_status", sa.String(), nullable=False),
            sa.Column("retrieved_at", sa.DateTime(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("revision", sa.Numeric(8, 0), nullable=False),
            sa.Column("upstream_ref", sa.String(600), nullable=True),
            sa.Column("quality_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["series_id"], ["market_data_series.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("series_id", "observed_at", name="uq_market_data_point_series_time"),
        )
    _index("ix_market_data_point_series_time", "market_data_points", ["series_id", "observed_at"])

    if "market_provider_runs" not in tables:
        op.create_table(
            "market_provider_runs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("demand_key", sa.String(400), nullable=False),
            sa.Column("trigger", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("observations_seen", sa.Numeric(12, 0), nullable=False),
            sa.Column("points_inserted", sa.Numeric(12, 0), nullable=False),
            sa.Column("points_revised", sa.Numeric(12, 0), nullable=False),
            sa.Column("duplicates", sa.Numeric(12, 0), nullable=False),
            sa.Column("error_class", sa.String(), nullable=True),
            sa.Column("trace_json", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _index("ix_market_provider_run_provider_time", "market_provider_runs", ["provider", "started_at"])
    _index("ix_market_provider_run_demand_time", "market_provider_runs", ["provider", "demand_key", "started_at"])

    if "market_data_point_revisions" not in tables:
        op.create_table(
            "market_data_point_revisions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("point_id", sa.String(), nullable=False),
            sa.Column("series_id", sa.String(), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("previous_value", value, nullable=False),
            sa.Column("new_value", value, nullable=False),
            sa.Column("previous_raw_value", sa.String(120), nullable=True),
            sa.Column("new_raw_value", sa.String(120), nullable=True),
            sa.Column("previous_source_status", sa.String(), nullable=True),
            sa.Column("new_source_status", sa.String(), nullable=True),
            sa.Column("previous_content_hash", sa.String(64), nullable=False),
            sa.Column("new_content_hash", sa.String(64), nullable=False),
            sa.Column("previous_retrieved_at", sa.DateTime(), nullable=True),
            sa.Column("revised_retrieved_at", sa.DateTime(), nullable=False),
            sa.Column("provider_run_id", sa.String(), nullable=True),
            sa.Column("upstream_ref", sa.String(600), nullable=True),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["point_id"], ["market_data_points.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["series_id"], ["market_data_series.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["provider_run_id"], ["market_provider_runs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("point_id", "revision", name="uq_market_point_revision"),
        )
    _index("ix_market_data_point_revisions_point_id", "market_data_point_revisions", ["point_id"])
    _index("ix_market_point_revision_series_time", "market_data_point_revisions", ["series_id", "observed_at"])

    if "market_position_snapshots" not in tables:
        op.create_table(
            "market_position_snapshots",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("position_id", sa.String(), nullable=False),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.Column("inputs_hash", sa.String(64), nullable=False),
            sa.Column("inputs_json", sa.JSON(), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("calculation_version", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["position_id"], ["market_positions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _index("ix_market_position_snapshots_organization_id", "market_position_snapshots", ["organization_id"])
    _index("ix_market_position_snapshots_position_id", "market_position_snapshots", ["position_id"])
    _index("ix_market_snapshot_org_position_time", "market_position_snapshots", ["organization_id", "position_id", "computed_at"])

    if "market_materiality_events" not in tables:
        op.create_table(
            "market_materiality_events",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("position_id", sa.String(), nullable=False),
            sa.Column("dedupe_key", sa.String(64), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("level", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("title_key", sa.String(), nullable=False),
            sa.Column("reasons_json", sa.JSON(), nullable=False),
            sa.Column("impact_json", sa.JSON(), nullable=False),
            sa.Column("data_quality_json", sa.JSON(), nullable=False),
            sa.Column("reference_snapshot_id", sa.String(), nullable=True),
            sa.Column("current_snapshot_id", sa.String(), nullable=True),
            sa.Column("methodology_version", sa.String(), nullable=False),
            sa.Column("notified_json", sa.JSON(), nullable=False),
            sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
            sa.Column("acknowledged_by_user_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["position_id"], ["market_positions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reference_snapshot_id"], ["market_position_snapshots.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["current_snapshot_id"], ["market_position_snapshots.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["acknowledged_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "dedupe_key", name="uq_market_materiality_org_dedupe"),
        )
    _index("ix_market_materiality_events_organization_id", "market_materiality_events", ["organization_id"])
    _index("ix_market_materiality_events_position_id", "market_materiality_events", ["position_id"])
    _index("ix_market_materiality_org_status_time", "market_materiality_events", ["organization_id", "status", "created_at"])
    _index("ix_market_materiality_position_kind_time", "market_materiality_events", ["position_id", "kind", "created_at"])

    if "market_position_field_links" not in tables:
        op.create_table(
            "market_position_field_links",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("position_id", sa.String(), nullable=False),
            sa.Column("field_entity_id", sa.String(), nullable=False),
            sa.Column("created_by_user_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["position_id"], ["market_positions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["field_entity_id"], ["managed_entities.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("position_id", "field_entity_id", name="uq_market_position_field"),
        )
    _index("ix_market_position_field_org", "market_position_field_links", ["organization_id", "position_id"])

    if "market_cycle_organization_state" not in tables:
        op.create_table(
            "market_cycle_organization_state",
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("last_enqueued_at", sa.DateTime(), nullable=True),
            sa.Column("last_started_at", sa.DateTime(), nullable=True),
            sa.Column("last_completed_at", sa.DateTime(), nullable=True),
            sa.Column("last_status", sa.String(), nullable=True),
            sa.Column("last_job_id", sa.String(), nullable=True),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("organization_id"),
        )
    _index("ix_market_cycle_organization_state_last_completed_at", "market_cycle_organization_state", ["last_completed_at"])

    if "market_alert_deliveries" not in tables:
        op.create_table(
            "market_alert_deliveries",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("event_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("channel", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("language", sa.String(16), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["event_id"], ["market_materiality_events.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_id", "user_id", "channel", name="uq_market_alert_delivery"),
        )
    _index("ix_market_alert_deliveries_organization_id", "market_alert_deliveries", ["organization_id"])
    _index("ix_market_alert_deliveries_event_id", "market_alert_deliveries", ["event_id"])
    _index("ix_market_alert_delivery_due", "market_alert_deliveries", ["status", "next_attempt_at"])

    journal_columns = _columns("market_decision_journal")
    for name, column in (
        ("evidence_snapshot_json", sa.Column("evidence_snapshot_json", sa.JSON(), nullable=True)),
        ("action_taken", sa.Column("action_taken", sa.Text(), nullable=True)),
        ("outcome_recorded_at", sa.Column("outcome_recorded_at", sa.DateTime(), nullable=True)),
        ("outcome_recorded_by_user_id", sa.Column("outcome_recorded_by_user_id", sa.String(), nullable=True)),
    ):
        if name not in journal_columns:
            op.add_column("market_decision_journal", column)
    if op.get_bind().dialect.name == "postgresql":
        existing_fks = {fk["name"] for fk in sa.inspect(op.get_bind()).get_foreign_keys("market_decision_journal")}
        if "fk_market_journal_outcome_user" not in existing_fks:
            op.create_foreign_key(
                "fk_market_journal_outcome_user",
                "market_decision_journal",
                "users",
                ["outcome_recorded_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_market_journal_outcome_user", "market_decision_journal", type_="foreignkey")
    for name in ("outcome_recorded_by_user_id", "outcome_recorded_at", "action_taken", "evidence_snapshot_json"):
        op.drop_column("market_decision_journal", name)
    op.drop_table("market_alert_deliveries")
    op.drop_table("market_cycle_organization_state")
    op.drop_table("market_data_point_revisions")
    op.drop_table("market_position_field_links")
    op.drop_table("market_materiality_events")
    op.drop_table("market_position_snapshots")
    op.drop_table("market_provider_runs")
    op.drop_table("market_data_points")
    op.drop_table("market_data_series")
