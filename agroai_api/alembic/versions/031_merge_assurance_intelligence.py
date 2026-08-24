"""Merge Assurance V2 and Intelligence Memory migration heads.

Revision ID: 031_merge_assurance_intelligence
Revises: 030_assurance_intelligence_v2, 030_intelligence_state_memory
Create Date: 2026-08-23

Both revision 030 branches are additive and independently proven. Production
already contains the Assurance branch. This no-op Alembic merge revision keeps
both histories intact and restores one canonical schema head without replaying,
renumbering, or rewriting an already shipped migration.
"""
from __future__ import annotations


revision = "031_merge_assurance_intelligence"
down_revision = ("030_assurance_intelligence_v2", "030_intelligence_state_memory")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
