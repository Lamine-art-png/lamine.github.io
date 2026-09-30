"""Team invitations: delivery state, single-use acceptance and audit fields.

Revision ID: 037_team_invitation_delivery
Revises: 036_legal_acceptance_locale
Create Date: 2026-09-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "037_team_invitation_delivery"
down_revision = "036_legal_acceptance_locale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot ALTER a foreign-key constraint. Batch mode copies the
    # existing rows/constraints there, while PostgreSQL uses additive ALTERs.
    with op.batch_alter_table("team_invitations") as batch:
        batch.add_column(sa.Column("locale", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("delivery_status", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("delivery_error", sa.String(length=240), nullable=True))
        batch.add_column(sa.Column("last_sent_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("accepted_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("accepted_by_user_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("revoked_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_team_invitations_accepted_by_user_id", "users", ["accepted_by_user_id"], ["id"])
        batch.create_index("ix_team_invitations_org_email_status", ["organization_id", "email", "status"])


def downgrade() -> None:
    with op.batch_alter_table("team_invitations") as batch:
        batch.drop_index("ix_team_invitations_org_email_status")
        batch.drop_constraint("fk_team_invitations_accepted_by_user_id", type_="foreignkey")
        for column in ("revoked_at", "accepted_by_user_id", "accepted_at", "last_sent_at", "delivery_error", "delivery_attempts", "delivery_status", "locale"):
            batch.drop_column(column)
