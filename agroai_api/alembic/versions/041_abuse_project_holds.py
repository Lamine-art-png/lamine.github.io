"""Per-event AGRO-AI project suspension holds.

An abuse event that disables a project now records a durable hold
(``project_hold_state``). A suspended project returns to ``active`` only when
its last active hold is restored, so restoring one of several abuse events
cannot lift a suspension another event still requires. ``status`` and
``automated_action`` are overwritten by later reviews and are not hold records.

Backfill: events whose last action was ``disable_project`` on a project that is
currently ``suspended`` become active holds, so suspensions applied before this
revision keep holding.

Revision ID: 041_abuse_project_holds
Revises: 040_intelligence_money_checks
"""
from alembic import op
import sqlalchemy as sa

revision = "041_abuse_project_holds"
down_revision = "040_intelligence_money_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_abuse_events", sa.Column("project_hold_state", sa.String(), nullable=True))
    op.add_column("platform_abuse_events", sa.Column("project_hold_released_at", sa.DateTime(), nullable=True))
    op.add_column("platform_abuse_events", sa.Column("project_hold_released_by_user_id", sa.String(), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_platform_abuse_hold_released_by",
            "platform_abuse_events",
            "users",
            ["project_hold_released_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_platform_abuse_project_hold",
        "platform_abuse_events",
        ["api_project_id", "project_hold_state"],
    )
    op.execute(
        """
        UPDATE platform_abuse_events
        SET project_hold_state = 'active'
        WHERE automated_action = 'disable_project'
          AND api_project_id IN (SELECT id FROM api_projects WHERE status = 'suspended')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_platform_abuse_project_hold", table_name="platform_abuse_events")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_platform_abuse_hold_released_by", "platform_abuse_events", type_="foreignkey")
    op.drop_column("platform_abuse_events", "project_hold_released_by_user_id")
    op.drop_column("platform_abuse_events", "project_hold_released_at")
    op.drop_column("platform_abuse_events", "project_hold_state")
