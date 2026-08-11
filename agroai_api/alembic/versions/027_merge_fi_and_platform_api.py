"""Merge the Field Intelligence launch and Platform API operations heads.

Revision ID: 027_merge_fi_and_platform_api
Revises: 024_field_intelligence_launch, 026_platform_api_operations
Create Date: 2026-08-10

Both ``024_field_intelligence_launch`` and the Platform API tail
(``024_platform_api_programs`` → ``025_platform_api_commerce`` →
``026_platform_api_operations``) branch off ``023_field_intelligence``.
They were developed on separate branches and merged into the launch branch.

This is a pure Alembic *merge* revision: it re-parents nothing and creates no
schema. Its only job is to collapse the two heads into a single authoritative
head so ``alembic heads`` returns exactly one revision. Because both parent
tails are additive and independent (distinct tables), no data movement is
required and the merge is safely reversible.
"""
from __future__ import annotations


revision = "027_merge_fi_and_platform_api"
down_revision = ("024_field_intelligence_launch", "026_platform_api_operations")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: the two parent tails already created all required objects."""


def downgrade() -> None:
    """No-op: reverting the merge simply restores the two independent heads."""
