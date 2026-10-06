"""Bind one Marketplace agreement to one approved organization."""
from alembic import op
import sqlalchemy as sa

revision = "043_aws_marketplace_linking"
down_revision = "042_aws_marketplace_registration"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("aws_marketplace_registrations") as batch:
        batch.add_column(sa.Column("claim_token_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("claim_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("organization_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("linked_by_user_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("linked_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("reconciled_at", sa.DateTime(), nullable=True))
        batch.create_unique_constraint("uq_aws_marketplace_registration_org", ["organization_id"])
        batch.create_foreign_key("fk_aws_marketplace_registration_org", "organizations", ["organization_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_aws_marketplace_registration_user", "users", ["linked_by_user_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_aws_marketplace_registrations_organization_id", ["organization_id"])


def downgrade():
    with op.batch_alter_table("aws_marketplace_registrations") as batch:
        batch.drop_index("ix_aws_marketplace_registrations_organization_id")
        batch.drop_constraint("fk_aws_marketplace_registration_user", type_="foreignkey")
        batch.drop_constraint("fk_aws_marketplace_registration_org", type_="foreignkey")
        batch.drop_constraint("uq_aws_marketplace_registration_org", type_="unique")
        for name in ("reconciled_at", "linked_at", "linked_by_user_id", "organization_id", "claim_expires_at", "claim_token_hash"):
            batch.drop_column(name)
