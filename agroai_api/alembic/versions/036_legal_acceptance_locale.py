"""Record the localized presentation used for self-service legal acceptance.

Revision ID: 036_legal_acceptance_locale
Revises: 035_self_service_legal_accept
Create Date: 2026-09-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "036_legal_acceptance_locale"
down_revision = "035_self_service_legal_accept"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "self_service_legal_acceptances",
        sa.Column("locale", sa.String(length=40), nullable=False, server_default="en"),
    )
    op.create_index(
        "ix_self_service_legal_acceptances_locale",
        "self_service_legal_acceptances",
        ["locale"],
    )


def downgrade() -> None:
    op.drop_index("ix_self_service_legal_acceptances_locale", table_name="self_service_legal_acceptances")
    op.drop_column("self_service_legal_acceptances", "locale")
