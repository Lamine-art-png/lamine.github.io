"""Real-PostgreSQL concurrency contracts for Field Intelligence.

These tests require an actual PostgreSQL database (two independent sessions,
transaction advisory locks) and are skipped when
``FIELD_INTELLIGENCE_TEST_DATABASE_URL`` is not set. CI provisions a dedicated
database; locally::

    FIELD_INTELLIGENCE_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/fi_tests \
        pytest tests/unit/test_field_intelligence_postgres.py

Covered:
* two workers deleting two asset rows that share one ``object_ref`` perform
  exactly one physical delete via the advisory-lock path (never the process
  lock fallback), both rows terminal, no orphan, no stuck job;
* concurrent uploads cannot overshoot the storage quota (atomic reservation);
* a tenant exactly at quota can still replay an identical asset.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import AuthContext
from app.db.base import Base
from app.models.field_intelligence import FieldObservationAsset, FieldStorageReservation
from app.models.operational_records import IngestionJob
from app.models.saas import EntitlementOverride, Organization, OrganizationMembership, User, Workspace
from app.services import field_intelligence as svc
from app.services.object_storage import S3ObjectStore

from tests.unit.test_field_intelligence import FakeStoreClient

PG_URL = os.environ.get("FIELD_INTELLIGENCE_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not PG_URL.startswith("postgresql"),
    reason="FIELD_INTELLIGENCE_TEST_DATABASE_URL is not a PostgreSQL URL",
)


class _ForbiddenProcessLocks(dict):
    """Fails the test if the SQLite process-lock fallback is ever exercised."""

    def setdefault(self, *args, **kwargs):  # noqa: D102
        raise AssertionError("process-lock fallback used on PostgreSQL — advisory lock path expected")


@pytest.fixture()
def pg_sessions():
    engine = create_engine(PG_URL)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()
    try:
        yield session, factory
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def fake_store(monkeypatch):
    client = FakeStoreClient()
    store = S3ObjectStore(bucket="agroai-test", prefix="agroai", client=client)
    monkeypatch.setattr(svc, "get_object_store", lambda **_: store)
    monkeypatch.setattr(svc, "object_storage_configured", lambda: True)
    return store


def _seed(db, *, org_id="org-pg", quota_mb: int | None = None):
    user = User(
        id=f"user-{org_id}", email=f"{org_id}@example.com", name="PG User", password_hash="x",
        email_verification_status="verified", email_verified_at=datetime.utcnow(),
    )
    org = Organization(id=org_id, name="PG Farms", slug=org_id, owner_user_id=user.id,
                       plan="professional", subscription_status="active")
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(id=f"ws-{org_id}", organization_id=org.id, name="PG WS",
                          crop="Almonds", region="CA", mode="live")
    db.add_all([user, org, membership, workspace])
    db.commit()
    if quota_mb is not None:
        db.add(EntitlementOverride(organization_id=org.id,
                                   feature_key="quota.field_intelligence.storage_mb",
                                   value_json={"value": quota_mb}))
        db.commit()
    return user, org, workspace


def _ctx(db, org_id="org-pg"):
    user = db.get(User, f"user-{org_id}")
    org = db.get(Organization, org_id)
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == org_id)
        .first()
    )
    return AuthContext(user=user, organization=org, membership=membership)


def _capture(db, org, workspace, *, capture_id="cap-pg"):
    from app.models.field_intelligence import FieldCaptureSession

    session = FieldCaptureSession(
        id=capture_id, tenant_id=org.id, workspace_id=workspace.id, user_id=f"user-{org.id}",
        client_capture_id=capture_id, idempotency_key=capture_id, capture_source="typed",
        status="received", asset_manifest_json=[], metadata_json={},
    )
    db.add(session)
    db.commit()
    return session


def _spool(body: bytes) -> str:
    handle = tempfile.NamedTemporaryFile(prefix="agroai-field-pg-", delete=False)
    handle.write(body)
    handle.flush()
    handle.close()
    return handle.name


def _register(db, ctx, capture_id, *, client_asset_id, body):
    return svc.register_asset(
        db, ctx, capture_id,
        client_asset_id=client_asset_id, kind="photo", content_type="image/png",
        filename="p.png", content_sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body), duration_seconds=None, spool_path=_spool(body),
    )


def test_pg_shared_object_deletion_exactly_one_physical_delete(pg_sessions, fake_store, monkeypatch):
    db, factory = pg_sessions
    assert db.get_bind().dialect.name == "postgresql"
    monkeypatch.setattr(svc, "_OBJECT_DELETE_LOCKS", _ForbiddenProcessLocks())

    user, org, workspace = _seed(db)
    _capture(db, org, workspace)
    ctx = _ctx(db)
    body = b"\x89PNG\r\n\x1a\n" + b"S" * 64
    a1 = _register(db, ctx, "cap-pg", client_asset_id="s1", body=body)
    a2 = _register(db, ctx, "cap-pg", client_asset_id="s2", body=body)
    assert a1.object_ref == a2.object_ref  # dedupe shares one physical object

    svc.delete_asset(db, ctx, a1.id)
    svc.delete_asset(db, ctx, a2.id)

    delete_calls: list[str] = []
    calls_lock = threading.Lock()
    real_delete = fake_store.client.delete_object

    def slow_counted_delete(Bucket, Key):
        if "/pending-registration/" not in Key:
            with calls_lock:
                delete_calls.append(Key)
            time.sleep(0.1)  # widen the race window across the two sessions
        return real_delete(Bucket, Key)

    monkeypatch.setattr(fake_store.client, "delete_object", slow_counted_delete)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(name: str) -> None:
        session = factory()
        try:
            barrier.wait(timeout=10)
            svc.run_field_intelligence_deletions(session, worker_id=name)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(f"pgw{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors

    db.expire_all()
    assert len(delete_calls) == 1, f"exactly one physical delete expected, got {delete_calls}"
    assert db.get(FieldObservationAsset, a1.id).status == "deleted"
    assert db.get(FieldObservationAsset, a2.id).status == "deleted"
    data_objects = [k for (_b, k) in fake_store.client.items if "/pending-registration/" not in k]
    assert data_objects == []  # no orphan object
    stuck = (
        db.query(IngestionJob)
        .filter(IngestionJob.job_type == svc.ASSET_DELETE_JOB_TYPE)
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .count()
    )
    assert stuck == 0  # no permanently running job


def test_pg_concurrent_uploads_cannot_overshoot_quota(pg_sessions, fake_store, monkeypatch):
    db, factory = pg_sessions
    user, org, workspace = _seed(db, quota_mb=1)  # 1 MiB quota
    _capture(db, org, workspace)

    chunk = 700 * 1024  # two of these exceed 1 MiB
    bodies = [b"\x89PNG\r\n\x1a\n" + bytes([i]) * chunk for i in range(2)]

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()
    errors: list[Exception] = []

    def worker(index: int) -> None:
        session = factory()
        try:
            ctx = _ctx(session)
            barrier.wait(timeout=10)
            try:
                _register(session, ctx, "cap-pg", client_asset_id=f"c{index}", body=bodies[index])
                with outcomes_lock:
                    outcomes.append("stored")
            except Exception as exc:  # noqa: BLE001
                detail = getattr(exc, "detail", None)
                if isinstance(detail, dict) and detail.get("code") == "storage_quota_exceeded":
                    with outcomes_lock:
                        outcomes.append("quota")
                else:
                    errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors
    assert sorted(outcomes) == ["quota", "stored"], outcomes

    db.expire_all()
    used = svc.physical_storage_used_bytes(db, org.id)
    assert used <= 1024 * 1024  # never overshoots the quota
    assert db.query(FieldStorageReservation).count() == 0  # nothing leaked


def test_pg_at_quota_identical_replay_succeeds(pg_sessions, fake_store):
    db, _factory = pg_sessions
    user, org, workspace = _seed(db, quota_mb=1)
    _capture(db, org, workspace)
    ctx = _ctx(db)

    body = b"\x89PNG\r\n\x1a\n" + b"Q" * (1024 * 1024 - 8)  # exactly 1 MiB
    stored = _register(db, ctx, "cap-pg", client_asset_id="full", body=body)
    assert svc.physical_storage_used_bytes(db, org.id) == 1024 * 1024

    # Identical replay at exactly-full quota returns the existing asset.
    replay = _register(db, ctx, "cap-pg", client_asset_id="full", body=body)
    assert replay.id == stored.id

    # A genuinely new upload is refused.
    with pytest.raises(Exception) as excinfo:
        _register(db, ctx, "cap-pg", client_asset_id="extra", body=b"\x89PNG\r\n\x1a\n" + b"X" * 64)
    detail = getattr(excinfo.value, "detail", None)
    assert isinstance(detail, dict) and detail.get("code") == "storage_quota_exceeded"
