"""Add AGRO-AI commercial control plane fields.

Revision ID: 007_commercial_control_plane
Revises: 006_saas_auth_billing_foundation
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa


revision = "007_commercial_control_plane"
down_revision = "006_saas_auth_billing_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("plan_version", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("customer_class", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("organization_type", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("operating_scale", sa.JSON(), nullable=True))
    op.add_column("organizations", sa.Column("commercial_metadata_json", sa.JSON(), nullable=True))
    op.add_column("organizations", sa.Column("billing_period", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("stripe_product_id", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("stripe_price_id", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("current_period_start", sa.DateTime(), nullable=True))
    op.add_column("organizations", sa.Column("cancel_at_period_end", sa.Boolean(), nullable=True))
    op.add_column("organizations", sa.Column("subscription_source", sa.String(), nullable=True))
    op.create_index("ix_organizations_customer_class", "organizations", ["customer_class"])
    op.create_index("ix_organizations_organization_type", "organizations", ["organization_type"])

    op.execute("UPDATE organizations SET plan = 'professional' WHERE lower(plan) IN ('pilot', 'pro')")
    op.execute("UPDATE organizations SET plan = 'network' WHERE lower(plan) = 'waterops'")
    op.execute("UPDATE organizations SET plan = 'team' WHERE lower(plan) IN ('assurance', 'assurance_audit')")
    op.execute("UPDATE organizations SET plan_version = '2026-07' WHERE plan_version IS NULL")
    op.execute("UPDATE organizations SET customer_class = 'individual_operator' WHERE customer_class IS NULL")
    op.execute("UPDATE organizations SET cancel_at_period_end = false WHERE cancel_at_period_end IS NULL")
    op.execute("UPDATE organizations SET subscription_source = 'self_serve' WHERE subscription_source IS NULL")

    op.add_column("usage_events", sa.Column("metric", sa.String(), nullable=True))
    op.add_column("usage_events", sa.Column("unit", sa.String(), nullable=True))
    op.add_column("usage_events", sa.Column("period_key", sa.String(), nullable=True))
    op.add_column("usage_events", sa.Column("request_id", sa.String(), nullable=True))
    op.add_column("usage_events", sa.Column("reservation_id", sa.String(), nullable=True))
    op.add_column("usage_events", sa.Column("state", sa.String(), nullable=True))
    op.execute("UPDATE usage_events SET metric = event_type WHERE metric IS NULL")
    op.execute("UPDATE usage_events SET unit = 'count' WHERE unit IS NULL")
    op.execute("UPDATE usage_events SET state = 'committed' WHERE state IS NULL")
    op.create_index("ix_usage_events_metric", "usage_events", ["metric"])
    op.create_index("ix_usage_events_period_key", "usage_events", ["period_key"])
    op.create_index("ix_usage_events_request_id", "usage_events", ["request_id"])
    op.create_index("ix_usage_events_reservation_id", "usage_events", ["reservation_id"])
    op.create_index("ix_usage_events_state", "usage_events", ["state"])

    op.create_table(
        "entitlement_overrides",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("feature_key", sa.String(), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entitlement_overrides_id", "entitlement_overrides", ["id"])
    op.create_index("ix_entitlement_overrides_organization_id", "entitlement_overrides", ["organization_id"])
    op.create_index("ix_entitlement_overrides_feature_key", "entitlement_overrides", ["feature_key"])

    op.create_table(
        "commercial_contracts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("contract_code", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=True),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commercial_contracts_id", "commercial_contracts", ["id"])
    op.create_index("ix_commercial_contracts_organization_id", "commercial_contracts", ["organization_id"])
    op.create_index("ix_commercial_contracts_contract_code", "commercial_contracts", ["contract_code"])
    op.create_index("ix_commercial_contracts_status", "commercial_contracts", ["status"])

    op.create_table(
        "managed_entities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "entity_type", "external_id", name="uq_managed_entity_external"),
    )
    op.create_index("ix_managed_entities_id", "managed_entities", ["id"])
    op.create_index("ix_managed_entities_organization_id", "managed_entities", ["organization_id"])
    op.create_index("ix_managed_entities_workspace_id", "managed_entities", ["workspace_id"])
    op.create_index("ix_managed_entities_entity_type", "managed_entities", ["entity_type"])
    op.create_index("ix_managed_entities_status", "managed_entities", ["status"])


def downgrade() -> None:
    op.drop_table("managed_entities")
    op.drop_table("commercial_contracts")
    op.drop_table("entitlement_overrides")
    op.drop_index("ix_usage_events_state", table_name="usage_events")
    op.drop_index("ix_usage_events_reservation_id", table_name="usage_events")
    op.drop_index("ix_usage_events_request_id", table_name="usage_events")
    op.drop_index("ix_usage_events_period_key", table_name="usage_events")
    op.drop_index("ix_usage_events_metric", table_name="usage_events")
    op.drop_column("usage_events", "state")
    op.drop_column("usage_events", "reservation_id")
    op.drop_column("usage_events", "request_id")
    op.drop_column("usage_events", "period_key")
    op.drop_column("usage_events", "unit")
    op.drop_column("usage_events", "metric")
    op.drop_index("ix_organizations_organization_type", table_name="organizations")
    op.drop_index("ix_organizations_customer_class", table_name="organizations")
    op.drop_column("organizations", "subscription_source")
    op.drop_column("organizations", "cancel_at_period_end")
    op.drop_column("organizations", "current_period_start")
    op.drop_column("organizations", "stripe_price_id")
    op.drop_column("organizations", "stripe_product_id")
    op.drop_column("organizations", "billing_period")
    op.drop_column("organizations", "commercial_metadata_json")
    op.drop_column("organizations", "operating_scale")
    op.drop_column("organizations", "organization_type")
    op.drop_column("organizations", "customer_class")
    op.drop_column("organizations", "plan_version")
