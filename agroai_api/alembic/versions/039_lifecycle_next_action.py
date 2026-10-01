"""Lifecycle email scheduling: per-enrollment next action time.

The scheduler used to scan the oldest active enrollments, so users who were
merely waiting for a later step could fill every batch and starve newer users
with email due now. ``next_action_at`` records when each enrollment next has
work (a due step, a retry, a deferred localization or the end of the minimum
gap); the scheduler selects only enrollments due now, earliest first. NULL
(rows created before this revision) means "due now".

Revision ID: 039_lifecycle_next_action
Revises: 038_lifecycle_emails
"""
from alembic import op
import sqlalchemy as sa

revision = "039_lifecycle_next_action"
down_revision = "038_lifecycle_emails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lifecycle_email_enrollments", sa.Column("next_action_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_lifecycle_email_enrollments_status_next_action",
        "lifecycle_email_enrollments",
        ["status", "next_action_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_lifecycle_email_enrollments_status_next_action", table_name="lifecycle_email_enrollments")
    op.drop_column("lifecycle_email_enrollments", "next_action_at")
