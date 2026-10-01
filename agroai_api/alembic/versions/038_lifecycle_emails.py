"""Lifecycle onboarding email state.

One enrollment row per user (the sequence position and why it stopped) and one
row per lifecycle step per user. The (user_id, step) unique constraint is the
idempotency key: a step can be scheduled, sent, skipped or deferred exactly
once, across restarts, redeploys and concurrent schedulers.

Revision ID: 038_lifecycle_emails
Revises: 037_team_invitation_delivery
"""
from alembic import op
import sqlalchemy as sa

revision = "038_lifecycle_emails"
down_revision = "037_team_invitation_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_email_enrollments",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sequence_version", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("stop_reason", sa.String(length=80), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_lifecycle_email_enrollments_status", "lifecycle_email_enrollments", ["status", "enrolled_at"])
    op.create_table(
        "lifecycle_email_sends",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=120), nullable=True),
        sa.Column("variant", sa.String(length=40), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("locale", sa.String(length=40), nullable=True),
        sa.Column("plan_at_send", sa.String(length=40), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("clicked_at", sa.DateTime(), nullable=True),
        sa.Column("bounced_at", sa.DateTime(), nullable=True),
        sa.Column("activation_event", sa.String(length=60), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "step", name="uq_lifecycle_email_sends_user_step"),
    )
    op.create_index("ix_lifecycle_email_sends_status_due", "lifecycle_email_sends", ["status", "next_attempt_at"])
    op.create_index("ix_lifecycle_email_sends_provider_message_id", "lifecycle_email_sends", ["provider_message_id"])


def downgrade() -> None:
    op.drop_index("ix_lifecycle_email_sends_provider_message_id", table_name="lifecycle_email_sends")
    op.drop_index("ix_lifecycle_email_sends_status_due", table_name="lifecycle_email_sends")
    op.drop_table("lifecycle_email_sends")
    op.drop_index("ix_lifecycle_email_enrollments_status", table_name="lifecycle_email_enrollments")
    op.drop_table("lifecycle_email_enrollments")
