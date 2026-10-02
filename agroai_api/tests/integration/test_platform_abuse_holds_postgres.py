"""Concurrent AGRO-AI abuse holds on one project (real PostgreSQL).

Disable and restore serialize on the project row, and the remaining-hold count
is read under that lock, so simultaneous operations always leave the state the
surviving holds require.
"""
from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")


def _seed(Session, holds: int):
    from app.models.platform_api import ApiProject
    from app.models.platform_product import PlatformAbuseEvent
    from app.models.saas import Organization, User

    db = Session()
    try:
        s = uuid.uuid4().hex[:10]
        user = User(email=f"hold-{s}@example.com", password_hash="x", email_verification_status="verified",
                    email_verified_at=datetime.utcnow())
        admin = User(email=f"hold-admin-{s}@example.com", password_hash="x")
        db.add_all([user, admin])
        db.flush()
        org = Organization(name=f"Hold {s}", slug=f"hold-{s}", owner_user_id=user.id, plan="enterprise",
                           subscription_status="active")
        db.add(org)
        db.flush()
        project = ApiProject(organization_id=org.id, workspace_id=None, name="Intelligence", slug="intelligence",
                             environment="live", status="suspended", default_rate_limit_policy={},
                             created_by_user_id=user.id)
        db.add(project)
        db.flush()
        events = [
            PlatformAbuseEvent(organization_id=org.id, api_project_id=project.id, signal_type=f"s{i}",
                               severity="high", status="monitoring", automated_action="disable_project",
                               project_hold_state="active", evidence_summary_json={})
            for i in range(holds)
        ]
        extra = PlatformAbuseEvent(organization_id=org.id, api_project_id=project.id, signal_type="new",
                                   severity="high", status="open", evidence_summary_json={})
        db.add_all([*events, extra])
        db.commit()
        return SimpleNamespace(user=user.id, admin=admin.id, org=org.id, project=project.id,
                               events=[e.id for e in events], extra=extra.id)
    finally:
        db.close()


def _cleanup(Session, seeded):
    from app.models.platform_api import ApiProject
    from app.models.platform_product import PlatformAbuseEvent
    from app.models.saas import Organization, User

    db = Session()
    try:
        db.query(PlatformAbuseEvent).filter(PlatformAbuseEvent.organization_id == seeded.org).delete(synchronize_session=False)
        db.query(ApiProject).filter(ApiProject.organization_id == seeded.org).delete(synchronize_session=False)
        db.query(Organization).filter(Organization.id == seeded.org).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_([seeded.user, seeded.admin])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _run_concurrently(monkeypatch, Session, seeded, operations):
    from app.api.v1 import platform_operations

    monkeypatch.setattr(platform_operations.settings, "PLATFORM_API_PRIVATE_BETA_ENABLED", True, raising=False)

    def slow_audit(*_args, **_kwargs):
        # Runs after the hold count and before commit: keeps each transaction
        # open long enough that the other one overlaps it.
        time.sleep(0.4)

    monkeypatch.setattr(platform_operations, "record_product_audit", slow_audit)

    def review(operation):
        event_id, action = operation
        db = Session()
        try:
            return platform_operations.review_abuse_event(
                event_id,
                platform_operations.AbuseReview(status="resolved", action=action, reason="concurrency"),
                ctx=SimpleNamespace(user=SimpleNamespace(id=seeded.admin)),
                db=db,
            )
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        list(pool.map(review, operations, timeout=30))


def _project_status(Session, project_id):
    from app.models.platform_api import ApiProject

    db = Session()
    try:
        return db.get(ApiProject, project_id).status
    finally:
        db.close()


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_final_restorations_reactivate_exactly_once(monkeypatch, attempt):
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    seeded = _seed(Session, holds=2)
    try:
        _run_concurrently(monkeypatch, Session, seeded, [(seeded.events[0], "restore_project"), (seeded.events[1], "restore_project")])
        assert _project_status(Session, seeded.project) == "active"
    finally:
        _cleanup(Session, seeded)
        engine.dispose()


@pytest.mark.parametrize("attempt", range(3))
def test_new_hold_racing_the_last_restoration_keeps_the_project_suspended(monkeypatch, attempt):
    from app.models.platform_product import PlatformAbuseEvent

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    seeded = _seed(Session, holds=1)
    try:
        _run_concurrently(monkeypatch, Session, seeded, [(seeded.events[0], "restore_project"), (seeded.extra, "disable_project")])
        assert _project_status(Session, seeded.project) == "suspended"
        db = Session()
        try:
            holds = {e.id: e.project_hold_state for e in db.query(PlatformAbuseEvent).filter_by(api_project_id=seeded.project)}
        finally:
            db.close()
        assert holds == {seeded.events[0]: "released", seeded.extra: "active"}
    finally:
        _cleanup(Session, seeded)
        engine.dispose()


def _backfill_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "041_abuse_project_holds.py"
    spec = importlib.util.spec_from_file_location("migration_041", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_reconstructs_overwritten_holds_and_keeps_every_suspension_releasable(monkeypatch):
    """Pre-041 suspensions whose automated_action was later overwritten still hold."""
    from app.api.v1 import platform_operations
    from app.models.platform_api import ApiProject
    from app.models.platform_product import PlatformAbuseEvent, PlatformProductAuditEvent

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    overwritten = _seed(Session, holds=1)
    restored = _seed(Session, holds=1)
    orphan = _seed(Session, holds=1)
    global_restore = _seed(Session, holds=3)
    db = Session()
    try:
        # Reset every seeded event to its pre-041 shape (no hold column data).
        for seeded in (overwritten, restored, orphan, global_restore):
            db.query(PlatformAbuseEvent).filter_by(api_project_id=seeded.project).update(
                {"project_hold_state": None, "automated_action": None}, synchronize_session=False
            )
        t0 = datetime(2026, 10, 2, 17, 0)

        def audit(seeded, event_id, action, minute):
            db.add(PlatformProductAuditEvent(
                organization_id=seeded.org, actor_user_id=seeded.admin, actor_type="platform_admin",
                event_type="platform.abuse.reviewed", subject_type="abuse_event", subject_id=event_id,
                outcome="success", metadata_json={"action": action}, created_at=t0.replace(minute=minute),
            ))

        # A: disabled, then re-reviewed with throttle (automated_action overwritten).
        audit(overwritten, overwritten.events[0], "disable_project", 1)
        audit(overwritten, overwritten.events[0], "throttle", 2)
        db.query(PlatformAbuseEvent).filter_by(id=overwritten.events[0]).update({"automated_action": "throttle"})
        # B: disabled, then restored — not a hold; project is already active.
        audit(restored, restored.events[0], "disable_project", 1)
        audit(restored, restored.events[0], "restore_project", 2)
        db.query(ApiProject).filter_by(id=restored.project).update({"status": "active"})
        # D: legacy global restore — A disables, B restores (which reactivated the
        # whole project before 041), C disables again. Only C still holds.
        a, b, c = global_restore.events
        audit(global_restore, a, "disable_project", 1)
        audit(global_restore, b, "disable_project", 2)
        audit(global_restore, b, "restore_project", 3)
        audit(global_restore, c, "disable_project", 4)
        # C: suspended with no reconstructable hold at all.
        db.query(PlatformAbuseEvent).filter_by(api_project_id=orphan.project).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    module = _backfill_module()
    try:
        for _ in range(2):  # idempotent
            with engine.begin() as connection:
                module.backfill_project_holds(connection)

        db = Session()
        try:
            def holds(project_id):
                return {
                    e.id: (e.project_hold_state, e.signal_type)
                    for e in db.query(PlatformAbuseEvent).filter_by(api_project_id=project_id)
                }

            assert holds(overwritten.project)[overwritten.events[0]][0] == "active"
            assert holds(overwritten.project)[overwritten.extra][0] is None
            assert {state for state, _ in holds(restored.project).values()} == {None}
            d_holds = holds(global_restore.project)
            a, b, c = global_restore.events
            assert (d_holds[a][0], d_holds[b][0], d_holds[c][0]) == (None, None, "active")
            seeded_holds = holds(orphan.project)
            assert list(seeded_holds.values()) == [("active", "legacy_project_suspension")]
        finally:
            db.close()

        # Every suspension is releasable through the normal operator review.
        monkeypatch.setattr(platform_operations.settings, "PLATFORM_API_PRIVATE_BETA_ENABLED", True, raising=False)
        monkeypatch.setattr(platform_operations, "record_product_audit", lambda *a, **k: None)
        for seeded, event_id in (
            (overwritten, overwritten.events[0]),
            (orphan, next(iter(seeded_holds))),
            (global_restore, global_restore.events[2]),
        ):
            db = Session()
            try:
                platform_operations.review_abuse_event(
                    event_id,
                    platform_operations.AbuseReview(status="resolved", action="restore_project", reason="backfill release"),
                    ctx=SimpleNamespace(user=SimpleNamespace(id=seeded.admin)), db=db,
                )
            finally:
                db.close()
            assert _project_status(Session, seeded.project) == "active"
    finally:
        db = Session()
        try:
            orgs = [overwritten.org, restored.org, orphan.org, global_restore.org]
            db.query(PlatformProductAuditEvent).filter(PlatformProductAuditEvent.organization_id.in_(orgs)).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
        for seeded in (overwritten, restored, orphan, global_restore):
            _cleanup(Session, seeded)
        engine.dispose()
