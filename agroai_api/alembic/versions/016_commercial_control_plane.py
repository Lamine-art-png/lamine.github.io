"""Add AGRO-AI commercial, entitlement, quota, and managed-entity control plane.

Revision ID: 016_commercial_control_plane
Revises: 015_saas_requests_repair
Create Date: 2026-07-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "016_commercial_control_plane"
down_revision = "015_saas_requests_repair"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _columns(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {index["name"] for index in _inspector().get_indexes(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    _add_column("organizations", sa.Column("plan_version", sa.String(), nullable=False, server_default="2026-07"))
    _add_column("organizations", sa.Column("customer_class", sa.String(), nullable=False, server_default="individual_operator"))
    _add_column("organizations", sa.Column("organization_type", sa.String(), nullable=True))
    _add_column("organizations", sa.Column("commercial_metadata_json", sa.JSON(), nullable=True))
    _add_column("organizations", sa.Column("subscription_source", sa.String(), nullable=False, server_default="local"))
    _add_column("organizations", sa.Column("stripe_product_id", sa.String(), nullable=True))
    _add_column("organizations", sa.Column("stripe_price_id", sa.String(), nullable=True))
    _add_column("organizations", sa.Column("current_period_start", sa.DateTime(), nullable=True))
    _add_column("organizations", sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()))

    _create_index("ix_organizations_plan_version", "organizations", ["plan_version"])
    _create_index("ix_organizations_customer_class", "organizations", ["customer_class"])
    _create_index("ix_organizations_organization_type", "organizations", ["organization_type"])
    _create_index("ix_organizations_subscription_source", "organizations", ["subscription_source"])
    _create_index("ix_organizations_stripe_product_id", "organizations", ["stripe_product_id"])
    _create_index("ix_organizations_stripe_price_id", "organizations", ["stripe_price_id"])

    _add_column("usage_events", sa.Column("metric", sa.String(), nullable=True))
    _add_column("usage_events", sa.Column("unit", sa.String(), nullable=False, server_default="count"))
    _add_column("usage_events", sa.Column("period_key", sa.String(), nullable=True))
    _add_column("usage_events", sa.Column("request_id", sa.String(), nullable=True))
    _add_column("usage_events", sa.Column("reservation_id", sa.String(), nullable=True))
    _add_column("usage_events", sa.Column("state", sa.String(), nullable=False, server_default="committed"))

    _create_index("ix_usage_events_metric", "usage_events", ["metric"])
    _create_index("ix_usage_events_period_key", "usage_events", ["period_key"])
    _create_index("ix_usage_events_request_id", "usage_events", ["request_id"])
    _create_index("ix_usage_events_reservation_id", "usage_events", ["reservation_id"])
    _create_index("ix_usage_events_state", "usage_events", ["state"])

    op.execute(sa.text("UPDATE organizations SET plan = 'free' WHERE lower(plan) = 'pilot'"))
    op.execute(sa.text("UPDATE organizations SET plan = 'professional' WHERE lower(plan) IN ('pro', 'waterops', 'assurance_audit')"))
    op.execute(sa.text("UPDATE organizations SET plan = 'team' WHERE lower(plan) = 'assurance'"))
    op.execute(sa.text("UPDATE organizations SET plan_version = '2026-07' WHERE plan_version IS NULL OR plan_version = ''"))
    op.execute(sa.text("UPDATE organizations SET customer_class = 'individual_operator' WHERE customer_class IS NULL OR customer_class = ''"))
    op.execute(sa.text("UPDATE organizations SET subscription_source = CASE WHEN stripe_subscription_id IS NOT NULL THEN 'stripe' ELSE 'local' END WHERE subscription_source IS NULL OR subscription_source = '' OR subscription_source = 'local'"))
    op.execute(sa.text("UPDATE usage_events SET metric = event_type WHERE metric IS NULL OR metric = ''"))
    op.execute(sa.text("UPDATE usage_events SET unit = 'count' WHERE unit IS NULL OR unit = ''"))
    op.execute(sa.text("UPDATE usage_events SET state = 'committed' WHERE state IS NULL OR state = ''"))

    if not _has_table("entitlement_overrides"):
        op.create_table(
            "entitlement_overrides",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("feature_key", sa.String(), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("source", sa.String(), nullable=False, server_default="manual"),
            sa.Column("valid_from", sa.DateTime(), nullable=True),
            sa.Column("valid_until", sa.DateTime(), nullable=True),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "feature_key", "valid_from", name="uq_entitlement_override_window"),
        )
        op.create_index("ix_entitlement_overrides_organization_id", "entitlement_overrides", ["organization_id"])
        op.create_index("ix_entitlement_overrides_feature_key", "entitlement_overrides", ["feature_key"])
        op.create_index("ix_entitlement_overrides_source", "entitlement_overrides", ["source"])
        op.create_index("ix_entitlement_overrides_valid_from", "entitlement_overrides", ["valid_from"])
        op.create_index("ix_entitlement_overrides_valid_until", "entitlement_overrides", ["valid_until"])

    if not _has_table("commercial_contracts"):
        op.create_table(
            "commercial_contracts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("contract_code", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("effective_from", sa.DateTime(), nullable=True),
            sa.Column("effective_to", sa.DateTime(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "contract_code", name="uq_contract_org_code"),
        )
        op.create_index("ix_commercial_contracts_organization_id", "commercial_contracts", ["organization_id"])
        op.create_index("ix_commercial_contracts_contract_code", "commercial_contracts", ["contract_code"])
        op.create_index("ix_commercial_contracts_status", "commercial_contracts", ["status"])
        op.create_index("ix_commercial_contracts_effective_from", "commercial_contracts", ["effective_from"])
        op.create_index("ix_commercial_contracts_effective_to", "commercial_contracts", ["effective_to"])

    if not _has_table("managed_entities"):
        op.create_table(
            "managed_entities",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("external_id", sa.String(), nullable=True),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "entity_type", "external_id", name="uq_managed_entity_external"),
        )
        op.create_index("ix_managed_entities_organization_id", "managed_entities", ["organization_id"])
        op.create_index("ix_managed_entities_workspace_id", "managed_entities", ["workspace_id"])
        op.create_index("ix_managed_entities_entity_type", "managed_entities", ["entity_type"])
        op.create_index("ix_managed_entities_external_id", "managed_entities", ["external_id"])
        op.create_index("ix_managed_entities_status", "managed_entities", ["status"])

    if not _has_table("quota_reservations"):
        op.create_table(
            "quota_reservations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("metric", sa.String(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("unit", sa.String(), nullable=False, server_default="count"),
            sa.Column("period_key", sa.String(), nullable=False),
            sa.Column("request_id", sa.String(), nullable=False),
            sa.Column("state", sa.String(), nullable=False, server_default="reserved"),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("committed_at", sa.DateTime(), nullable=True),
            sa.Column("released_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("organization_id", "metric", "request_id", name="uq_quota_reservation_request"),
        )
        op.create_index("ix_quota_reservations_organization_id", "quota_reservations", ["organization_id"])
        op.create_index("ix_quota_reservations_workspace_id", "quota_reservations", ["workspace_id"])
        op.create_index("ix_quota_reservations_user_id", "quota_reservations", ["user_id"])
        op.create_index("ix_quota_reservations_metric", "quota_reservations", ["metric"])
        op.create_index("ix_quota_reservations_period_key", "quota_reservations", ["period_key"])
        op.create_index("ix_quota_reservations_request_id", "quota_reservations", ["request_id"])
        op.create_index("ix_quota_reservations_state", "quota_reservations", ["state"])


def downgrade() -> None:
    for table in ("quota_reservations", "managed_entities", "commercial_contracts", "entitlement_overrides"):
        if _has_table(table):
            op.drop_table(table)

    for name in (
        "ix_usage_events_state",
        "ix_usage_events_reservation_id",
        "ix_usage_events_request_id",
        "ix_usage_events_period_key",
        "ix_usage_events_metric",
    ):
        if name in _indexes("usage_events"):
            op.drop_index(name, table_name="usage_events")

    for column in ("state", "reservation_id", "request_id", "period_key", "unit", "metric"):
        if column in _columns("usage_events"):
            op.drop_column("usage_events", column)

    for name in (
        "ix_organizations_stripe_price_id",
        "ix_organizations_stripe_product_id",
        "ix_organizations_subscription_source",
        "ix_organizations_organization_type",
        "ix_organizations_customer_class",
        "ix_organizations_plan_version",
    ):
        if name in _indexes("organizations"):
            op.drop_index(name, table_name="organizations")

    for column in (
        "cancel_at_period_end",
        "current_period_start",
        "stripe_price_id",
        "stripe_product_id",
        "subscription_source",
        "commercial_metadata_json",
        "organization_type",
        "customer_class",
        "plan_version",
    ):
        if column in _columns("organizations"):
            op.drop_column("organizations", column)
