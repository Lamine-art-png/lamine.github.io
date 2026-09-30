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
    op.add_column("team_invitations", sa.Column("locale", sa.String(length=40), nullable=True))
    op.add_column("team_invitations", sa.Column("delivery_status", sa.String(length=40), nullable=True))
    op.add_column("team_invitations", sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("team_invitations", sa.Column("delivery_error", sa.String(length=240), nullable=True))
    op.add_column("team_invitations", sa.Column("last_sent_at", sa.DateTime(), nullable=True))
    op.add_column("team_invitations", sa.Column("accepted_at", sa.DateTime(), nullable=True))
    op.add_column("team_invitations", sa.Column("accepted_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("team_invitations", sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.create_index("ix_team_invitations_org_email_status", "team_invitations", ["organization_id", "email", "status"])


def downgrade() -> None:
    op.drop_index("ix_team_invitations_org_email_status", table_name="team_invitations")
    for column in ("revoked_at", "accepted_by_user_id", "accepted_at", "last_sent_at", "delivery_error", "delivery_attempts", "delivery_status", "locale"):
        op.drop_column("team_invitations", column)
