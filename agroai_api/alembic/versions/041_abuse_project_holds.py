"""Per-event AGRO-AI project suspension holds.

An abuse event that disables a project now records a durable hold
(``project_hold_state``). A suspended project returns to ``active`` only when
its last active hold is restored, so restoring one of several abuse events
cannot lift a suspension another event still requires. ``status`` and
``automated_action`` are overwritten by later reviews and are not hold records.

Backfill (every currently ``suspended`` project ends with a releasable hold):
an abuse event holds its project when its last disable/restore review in the
``platform.abuse.reviewed`` audit history was ``disable_project`` (later
reviews overwrote ``automated_action``, so it is only the fallback when no
audit history exists). A suspended project with no reconstructable hold gets
one seeded ``legacy_project_suspension`` event, so operators can always lift
it through the normal restore_project review.

Revision ID: 041_abuse_project_holds
Revises: 040_intelligence_money_checks
"""
import json
import uuid
from datetime import datetime

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
    backfill_project_holds(op.get_bind())


def _metadata(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value or {}


def backfill_project_holds(bind) -> None:
    """Give every suspended project the holds that still apply. Idempotent."""
    projects = bind.execute(
        sa.text("SELECT id, organization_id FROM api_projects WHERE status = 'suspended'")
    ).fetchall()
    for project_id, organization_id in projects:
        events = bind.execute(
            sa.text(
                "SELECT id, automated_action, project_hold_state FROM platform_abuse_events "
                "WHERE api_project_id = :project ORDER BY created_at"
            ),
            {"project": project_id},
        ).fetchall()
        active = 0
        for event_id, automated_action, hold_state in events:
            if hold_state is not None:
                active += hold_state == "active"
                continue
            reviews = bind.execute(
                sa.text(
                    "SELECT metadata_json FROM platform_product_audit_events "
                    "WHERE subject_type = 'abuse_event' AND subject_id = :event "
                    "AND event_type = 'platform.abuse.reviewed' ORDER BY created_at"
                ),
                {"event": event_id},
            ).fetchall()
            hold_actions = [
                _metadata(row[0]).get("action")
                for row in reviews
                if _metadata(row[0]).get("action") in {"disable_project", "restore_project"}
            ]
            last = hold_actions[-1] if hold_actions else automated_action
            if last == "disable_project":
                bind.execute(
                    sa.text("UPDATE platform_abuse_events SET project_hold_state = 'active' WHERE id = :event"),
                    {"event": event_id},
                )
                active += 1
        if active == 0:
            bind.execute(
                sa.text(
                    "INSERT INTO platform_abuse_events (id, organization_id, api_project_id, signal_type, severity, "
                    "status, automated_action, evidence_summary_json, project_hold_state, created_at) "
                    "VALUES (:id, :org, :project, 'legacy_project_suspension', 'high', 'monitoring', "
                    "'disable_project', :evidence, 'active', :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": organization_id,
                    "project": project_id,
                    "evidence": json.dumps(
                        {
                            "source": "041_abuse_project_holds",
                            "reason": "Project was suspended before per-event holds and no unreleased disable could be reconstructed.",
                        }
                    ),
                    "now": datetime.utcnow(),
                },
            )


def downgrade() -> None:
    op.drop_index("ix_platform_abuse_project_hold", table_name="platform_abuse_events")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_platform_abuse_hold_released_by", "platform_abuse_events", type_="foreignkey")
    op.drop_column("platform_abuse_events", "project_hold_released_by_user_id")
    op.drop_column("platform_abuse_events", "project_hold_released_at")
    op.drop_column("platform_abuse_events", "project_hold_state")
