"""Bind one Marketplace agreement to one approved organization."""
from alembic import op
import sqlalchemy as sa

revision = "043_aws_marketplace_linking"
down_revision = "042_aws_marketplace_registration"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("aws_marketplace_registrations", sa.Column("claim_token_hash", sa.String(64), nullable=True))
    op.add_column("aws_marketplace_registrations", sa.Column("claim_expires_at", sa.DateTime(), nullable=True))
    op.add_column("aws_marketplace_registrations", sa.Column("organization_id", sa.String(), nullable=True))
    op.add_column("aws_marketplace_registrations", sa.Column("linked_by_user_id", sa.String(), nullable=True))
    op.add_column("aws_marketplace_registrations", sa.Column("linked_at", sa.DateTime(), nullable=True))
    op.add_column("aws_marketplace_registrations", sa.Column("reconciled_at", sa.DateTime(), nullable=True))
    op.create_unique_constraint("uq_aws_marketplace_registration_org", "aws_marketplace_registrations", ["organization_id"])
    op.create_foreign_key("fk_aws_marketplace_registration_org", "aws_marketplace_registrations", "organizations", ["organization_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_aws_marketplace_registration_user", "aws_marketplace_registrations", "users", ["linked_by_user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_aws_marketplace_registrations_organization_id", "aws_marketplace_registrations", ["organization_id"])


def downgrade():
    op.drop_index("ix_aws_marketplace_registrations_organization_id", table_name="aws_marketplace_registrations")
    op.drop_constraint("fk_aws_marketplace_registration_user", "aws_marketplace_registrations", type_="foreignkey")
    op.drop_constraint("fk_aws_marketplace_registration_org", "aws_marketplace_registrations", type_="foreignkey")
    op.drop_constraint("uq_aws_marketplace_registration_org", "aws_marketplace_registrations", type_="unique")
    for name in ("reconciled_at", "linked_at", "linked_by_user_id", "organization_id", "claim_expires_at", "claim_token_hash"):
        op.drop_column("aws_marketplace_registrations", name)
