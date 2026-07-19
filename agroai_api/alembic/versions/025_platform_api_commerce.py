"""Add versioned API commerce, credit, Stripe, logs, and sandbox custody.

Revision ID: 025_platform_api_commerce
Revises: 024_platform_api_programs
Create Date: 2026-07-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from datetime import datetime


revision = "025_platform_api_commerce"
down_revision = "024_platform_api_programs"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "platform_api_plans",
        _id(),
        sa.Column("catalog_version", sa.String(), nullable=False),
        sa.Column("plan_identifier", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("monthly_price_cents", sa.Integer(), nullable=True),
        sa.Column("annual_price_cents", sa.Integer(), nullable=True),
        sa.Column("included_credits", sa.Integer(), nullable=True),
        sa.Column("overage_price_per_1000_cents", sa.Integer(), nullable=True),
        sa.Column("overages_allowed", sa.Boolean(), nullable=False),
        sa.Column("limits_json", sa.JSON(), nullable=False),
        sa.Column("support_tier", sa.String(), nullable=False),
        sa.Column("stripe_product_config_key", sa.String(), nullable=True),
        sa.Column("stripe_monthly_price_config_key", sa.String(), nullable=True),
        sa.Column("stripe_annual_price_config_key", sa.String(), nullable=True),
        sa.Column("stripe_overage_price_config_key", sa.String(), nullable=True),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("catalog_version", "plan_identifier", name="uq_platform_api_plan_version"),
    )
    op.create_index("ix_platform_api_plan_active", "platform_api_plans", ["active", "catalog_version"])

    op.create_table(
        "platform_api_operation_costs",
        _id(),
        sa.Column("catalog_version", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("operation_class", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("catalog_version", "operation_id", "environment", name="uq_platform_cost_version_operation_env"),
    )

    op.create_table(
        "platform_api_subscriptions",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enrollment_id", sa.String(), sa.ForeignKey("platform_program_enrollments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_id", sa.String(), sa.ForeignKey("platform_api_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("status_slot", sa.String(), nullable=False),
        sa.Column("billing_mode", sa.String(), nullable=False),
        sa.Column("billing_interval", sa.String(), nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True, unique=True),
        sa.Column("stripe_price_id", sa.String(), nullable=True),
        sa.Column("current_period_start", sa.DateTime(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("grace_ends_at", sa.DateTime(), nullable=True),
        sa.Column("stripe_state_updated_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("contract_reference", sa.String(), nullable=True),
        sa.Column("entitlement_policy_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "status_slot", name="uq_platform_api_subscription_active_slot"),
    )
    op.create_index("ix_platform_api_subscription_stripe", "platform_api_subscriptions", ["stripe_subscription_id"])

    op.create_table(
        "platform_credit_reservations",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", sa.String(), sa.ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("logical_operation_id", sa.String(), nullable=False),
        sa.Column("billing_period_key", sa.String(), nullable=False),
        sa.Column("reserved_credits", sa.Integer(), nullable=False),
        sa.Column("committed_credits", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("overage_credits", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "api_project_id", "logical_operation_id", name="uq_platform_credit_logical_operation"),
    )
    op.create_index("ix_platform_credit_period_state", "platform_credit_reservations", ["organization_id", "billing_period_key", "state"])

    op.create_table(
        "platform_stripe_meter_outbox",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(), sa.ForeignKey("platform_api_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usage_event_id", sa.String(), sa.ForeignKey("platform_api_usage_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meter_event_identifier", sa.String(), nullable=False),
        sa.Column("meter_event_name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("exported_at", sa.DateTime(), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_class", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("usage_event_id", name="uq_platform_meter_usage_event"),
        sa.UniqueConstraint("meter_event_identifier", name="uq_platform_meter_event_identifier"),
    )
    op.create_index("ix_platform_meter_outbox_ready", "platform_stripe_meter_outbox", ["status", "next_attempt_at", "created_at"])

    op.create_table(
        "platform_stripe_events",
        _id(),
        sa.Column("stripe_event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subscription_id", sa.String(), sa.ForeignKey("platform_api_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("event_created_at", sa.DateTime(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("safe_metadata_json", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("stripe_event_id", name="uq_platform_stripe_event"),
    )
    op.create_index("ix_platform_stripe_event_processing", "platform_stripe_events", ["status", "created_at"])

    op.create_table(
        "platform_request_logs",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("usage_cost", sa.Integer(), nullable=False),
        sa.Column("safe_error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "request_id", name="uq_platform_request_log_org_request"),
    )
    op.create_index("ix_platform_request_log_project_time", "platform_request_logs", ["api_project_id", "created_at"])

    op.create_table(
        "platform_notifications",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notification_type", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("locale", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("safe_context_json", sa.JSON(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "notification_type", "dedupe_key", name="uq_platform_notification_dedupe"),
    )
    op.create_index("ix_platform_notification_delivery", "platform_notifications", ["status", "created_at"])

    op.create_table(
        "platform_sandbox_states",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fixture_version", sa.String(), nullable=False),
        sa.Column("reset_counter", sa.Integer(), nullable=False),
        sa.Column("seed", sa.String(), nullable=False),
        sa.Column("last_reset_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_reset_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("api_project_id", name="uq_platform_sandbox_project"),
    )

    plans = sa.table(
        "platform_api_plans",
        sa.column("id", sa.String()),
        sa.column("catalog_version", sa.String()),
        sa.column("plan_identifier", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("status", sa.String()),
        sa.column("active", sa.Boolean()),
        sa.column("currency", sa.String()),
        sa.column("monthly_price_cents", sa.Integer()),
        sa.column("annual_price_cents", sa.Integer()),
        sa.column("included_credits", sa.Integer()),
        sa.column("overage_price_per_1000_cents", sa.Integer()),
        sa.column("overages_allowed", sa.Boolean()),
        sa.column("limits_json", sa.JSON()),
        sa.column("support_tier", sa.String()),
        sa.column("stripe_product_config_key", sa.String()),
        sa.column("stripe_monthly_price_config_key", sa.String()),
        sa.column("stripe_annual_price_config_key", sa.String()),
        sa.column("stripe_overage_price_config_key", sa.String()),
        sa.column("effective_at", sa.DateTime()),
        sa.column("retired_at", sa.DateTime()),
        sa.column("created_at", sa.DateTime()),
    )
    now = datetime(2026, 7, 19)
    op.bulk_insert(
        plans,
        [
            {
                "id": "api-plan-sandbox-2026-07",
                "catalog_version": "2026-07-provisional",
                "plan_identifier": "sandbox",
                "display_name": "Sandbox",
                "status": "provisional_commercial_approval_required",
                "active": False,
                "currency": "USD",
                "monthly_price_cents": 0,
                "annual_price_cents": 0,
                "included_credits": 10000,
                "overage_price_per_1000_cents": None,
                "overages_allowed": False,
                "limits_json": {"projects": 1, "live_projects": 0, "service_accounts": 2, "keys": 2, "webhooks": 1, "request_log_retention_days": 7, "synthetic_only": True},
                "support_tier": "community_documentation",
                "stripe_product_config_key": "PLATFORM_API_STRIPE_SANDBOX_PRODUCT_ID",
                "stripe_monthly_price_config_key": None,
                "stripe_annual_price_config_key": None,
                "stripe_overage_price_config_key": None,
                "effective_at": None,
                "retired_at": None,
                "created_at": now,
            },
            {
                "id": "api-plan-developer-2026-07",
                "catalog_version": "2026-07-provisional",
                "plan_identifier": "developer",
                "display_name": "Developer",
                "status": "provisional_commercial_approval_required",
                "active": False,
                "currency": "USD",
                "monthly_price_cents": 14900,
                "annual_price_cents": 143000,
                "included_credits": 250000,
                "overage_price_per_1000_cents": 75,
                "overages_allowed": True,
                "limits_json": {"projects": 3, "live_projects": 1, "service_accounts": 5, "keys": 5, "webhooks": 3, "request_log_retention_days": 30},
                "support_tier": "email",
                "stripe_product_config_key": None,
                "stripe_monthly_price_config_key": "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID",
                "stripe_annual_price_config_key": "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID",
                "stripe_overage_price_config_key": "PLATFORM_API_STRIPE_DEVELOPER_OVERAGE_PRICE_ID",
                "effective_at": None,
                "retired_at": None,
                "created_at": now,
            },
            {
                "id": "api-plan-scale-2026-07",
                "catalog_version": "2026-07-provisional",
                "plan_identifier": "scale",
                "display_name": "Scale",
                "status": "provisional_commercial_approval_required",
                "active": False,
                "currency": "USD",
                "monthly_price_cents": 74900,
                "annual_price_cents": 719000,
                "included_credits": 2000000,
                "overage_price_per_1000_cents": 35,
                "overages_allowed": True,
                "limits_json": {"projects": 10, "live_projects": 5, "service_accounts": 20, "keys": 20, "webhooks": 20, "request_log_retention_days": 90},
                "support_tier": "priority",
                "stripe_product_config_key": None,
                "stripe_monthly_price_config_key": "PLATFORM_API_STRIPE_SCALE_MONTHLY_PRICE_ID",
                "stripe_annual_price_config_key": "PLATFORM_API_STRIPE_SCALE_ANNUAL_PRICE_ID",
                "stripe_overage_price_config_key": "PLATFORM_API_STRIPE_SCALE_OVERAGE_PRICE_ID",
                "effective_at": None,
                "retired_at": None,
                "created_at": now,
            },
            {
                "id": "api-plan-enterprise-2026-07",
                "catalog_version": "2026-07-provisional",
                "plan_identifier": "enterprise",
                "display_name": "Enterprise",
                "status": "provisional_commercial_approval_required",
                "active": False,
                "currency": "USD",
                "monthly_price_cents": None,
                "annual_price_cents": None,
                "included_credits": None,
                "overage_price_per_1000_cents": None,
                "overages_allowed": False,
                "limits_json": {"all_limits": "explicit_contract_values_required"},
                "support_tier": "contract",
                "stripe_product_config_key": None,
                "stripe_monthly_price_config_key": None,
                "stripe_annual_price_config_key": None,
                "stripe_overage_price_config_key": None,
                "effective_at": None,
                "retired_at": None,
                "created_at": now,
            },
        ],
    )

    costs = sa.table(
        "platform_api_operation_costs",
        sa.column("id", sa.String()),
        sa.column("catalog_version", sa.String()),
        sa.column("operation_id", sa.String()),
        sa.column("operation_class", sa.String()),
        sa.column("environment", sa.String()),
        sa.column("credits", sa.Integer()),
        sa.column("active", sa.Boolean()),
        sa.column("description", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    classes = {
        "basic_read": 1,
        "list_query": 2,
        "metadata_write": 5,
        "field_creation": 10,
        "source_upload_initiation": 10,
        "data_ingestion": 25,
        "observation_batch_processing": 50,
        "recommendation_computation": 100,
        "report_generation": 250,
        "connector_synchronization": 100,
        "large_artifact_processing": 500,
        "webhook_logical_event": 1,
    }
    op.bulk_insert(
        costs,
        [
            {
                "id": f"api-cost-{environment}-{operation_class.replace('_', '-')}",
                "catalog_version": "2026-07-provisional",
                "operation_id": operation_class,
                "operation_class": operation_class,
                "environment": environment,
                "credits": credits if environment == "live" else max(1, credits // 10),
                "active": False,
                "description": f"Provisional {operation_class.replace('_', ' ')} credit cost.",
                "created_at": now,
            }
            for environment in ("test", "live")
            for operation_class, credits in classes.items()
        ],
    )


def downgrade() -> None:
    for table in (
        "platform_sandbox_states",
        "platform_notifications",
        "platform_request_logs",
        "platform_stripe_events",
        "platform_stripe_meter_outbox",
        "platform_credit_reservations",
        "platform_api_subscriptions",
        "platform_api_operation_costs",
        "platform_api_plans",
    ):
        op.drop_table(table)
