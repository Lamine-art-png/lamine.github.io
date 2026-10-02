"""Per-event AGRO-AI project suspension holds.

An abuse event that disables a project now records a durable hold
(``project_hold_state``). A suspended project returns to ``active`` only when
its last active hold is restored, so restoring one of several abuse events
cannot lift a suspension another event still requires. ``status`` and
``automated_action`` are overwritten by later reviews and are not hold records.

Backfill (every currently ``suspended`` project ends with a releasable hold):
holds are reconstructed over each project's whole disable/restore timeline
from the ``platform.abuse.reviewed`` audit history. Before this revision a
``restore_project`` on any event reactivated the whole project, so every
disable that precedes the project's last restore is void; an event holds the
project only if it disabled it after that restore. ``automated_action`` (later
reviews overwrote it) is used, timed by ``reviewed_at``, only for events with
no audit history. A suspended project with no reconstructable hold gets one
seeded ``legacy_project_suspension`` event, so operators can always lift it
through the normal restore_project review.

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
                "SELECT id, automated_action, project_hold_state, reviewed_at FROM platform_abuse_events "
                "WHERE api_project_id = :project ORDER BY created_at"
            ),
            {"project": project_id},
        ).fetchall()
        # (timestamp, event_id, action) across the project's whole timeline.
        timeline = []
        existing_active = 0
        for event_id, automated_action, hold_state, reviewed_at in events:
            if hold_state is not None:
                existing_active += hold_state == "active"
                continue
            reviews = bind.execute(
                sa.text(
                    "SELECT created_at, metadata_json FROM platform_product_audit_events "
                    "WHERE subject_type = 'abuse_event' AND subject_id = :event "
                    "AND event_type = 'platform.abuse.reviewed' ORDER BY created_at"
                ),
                {"event": event_id},
            ).fetchall()
            actions = [
                (created_at, _metadata(metadata).get("action"))
                for created_at, metadata in reviews
                if _metadata(metadata).get("action") in {"disable_project", "restore_project"}
            ]
            if actions:
                timeline.extend((at, event_id, action) for at, action in actions)
            elif automated_action == "disable_project" and reviewed_at is not None:
                timeline.append((reviewed_at, event_id, "disable_project"))
        timeline.sort(key=lambda item: item[0])
        restores = [at for at, _event, action in timeline if action == "restore_project"]
        last_restore = restores[-1] if restores else None
        held = {
            event_id
            for at, event_id, action in timeline
            if action == "disable_project" and (last_restore is None or at > last_restore)
        }
        for event_id in held:
            bind.execute(
                sa.text("UPDATE platform_abuse_events SET project_hold_state = 'active' WHERE id = :event"),
                {"event": event_id},
            )
        active = existing_active + len(held)
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
