"""Persist verified AWS license identities without granting access."""
from alembic import op
import sqlalchemy as sa

revision = "042_aws_marketplace_registration"
down_revision = "041_abuse_project_holds"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "aws_marketplace_registrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("license_arn", sa.String(1200), nullable=False, unique=True),
        sa.Column("customer_aws_account_id", sa.String(12), nullable=False),
        sa.Column("product_code", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("aws_marketplace_registrations")
