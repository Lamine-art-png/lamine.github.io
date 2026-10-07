"""Persist AWS Marketplace plan dimension and entitlement expiry.

Revision ID: 046_aws_marketplace_plan_mapping
Revises: 045_intelligence_platform_v1
"""
from alembic import op
import sqlalchemy as sa


revision = "046_aws_marketplace_plan_mapping"
down_revision = "045_intelligence_platform_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "aws_marketplace_registrations",
        sa.Column("plan_identifier", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "aws_marketplace_registrations",
        sa.Column("entitlement_expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("aws_marketplace_registrations", "entitlement_expires_at")
    op.drop_column("aws_marketplace_registrations", "plan_identifier")
