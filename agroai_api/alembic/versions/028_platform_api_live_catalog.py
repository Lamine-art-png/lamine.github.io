"""Activate the live Developer and Scale Platform API catalog.

Revision ID: 028_platform_api_live_catalog
Revises: 027_field_intelligence_launch
Create Date: 2026-08-02

The founder has approved the live commercial launch and the Stripe resources are
configured server-side. Production startup runs Alembic before Uvicorn, so this
one-time, idempotent data migration removes the need for a browser token or a
manual privileged curl command.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "028_platform_api_live_catalog"
down_revision = "027_field_intelligence_launch"
branch_labels = None
depends_on = None

CATALOG_VERSION = "2026-07-provisional"
LIVE_PLAN_IDENTIFIERS = ("developer", "scale")


def upgrade() -> None:
    connection = op.get_bind()

    plan_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM platform_api_plans
            WHERE catalog_version = :catalog_version
              AND plan_identifier IN ('developer', 'scale')
            """
        ),
        {"catalog_version": CATALOG_VERSION},
    ).scalar_one()
    cost_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM platform_api_operation_costs
            WHERE catalog_version = :catalog_version
            """
        ),
        {"catalog_version": CATALOG_VERSION},
    ).scalar_one()

    if int(plan_count or 0) != len(LIVE_PLAN_IDENTIFIERS):
        raise RuntimeError(
            "Platform API live catalog activation refused: Developer and Scale plans are not both present"
        )
    if int(cost_count or 0) == 0:
        raise RuntimeError(
            "Platform API live catalog activation refused: operation cost catalog is missing"
        )

    connection.execute(
        sa.text(
            """
            UPDATE platform_api_plans
            SET active = TRUE,
                status = 'private_preview',
                effective_at = COALESCE(effective_at, CURRENT_TIMESTAMP)
            WHERE catalog_version = :catalog_version
              AND plan_identifier IN ('developer', 'scale')
            """
        ),
        {"catalog_version": CATALOG_VERSION},
    )
    connection.execute(
        sa.text(
            """
            UPDATE platform_api_operation_costs
            SET active = TRUE
            WHERE catalog_version = :catalog_version
            """
        ),
        {"catalog_version": CATALOG_VERSION},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE platform_api_plans
            SET active = FALSE,
                status = 'provisional_commercial_approval_required',
                effective_at = NULL
            WHERE catalog_version = :catalog_version
              AND plan_identifier IN ('developer', 'scale')
            """
        ),
        {"catalog_version": CATALOG_VERSION},
    )
    connection.execute(
        sa.text(
            """
            UPDATE platform_api_operation_costs
            SET active = FALSE
            WHERE catalog_version = :catalog_version
            """
        ),
        {"catalog_version": CATALOG_VERSION},
    )
