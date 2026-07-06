from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.hardened_records import IngestionJobState
from app.services.ingestion_job_runner import _claim, _complete, _fail_or_retry, _renew_lease


def _new_job(db, *, status="queued", worker_id=None, lease_expires_at=None, attempt_count=0):
    now = datetime.utcnow()
    job = IngestionJobState(
        tenant_id="tenant-1",
        job_type="connector_ingest_object",
        status=status,
        input_json={},
        output_json={},
        attempt_count=attempt_count,
        max_attempts=5,
        worker_id=worker_id,
        lease_expires_at=lease_expires_at,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    return job


def test_job_lease_prevents_concurrent_worker_claims(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    job = _new_job(db)

    first = _claim(db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-a")
    assert first is not None
    assert first.status == "running"
    assert first.worker_id == "worker-a"
    assert first.attempt_count == 1

    second_db = Session()
    try:
        second = _claim(second_db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-b")
        assert second is None
    finally:
        second_db.close()


def test_expired_lease_can_be_reclaimed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    job = _new_job(
        db,
        status="running",
        worker_id="dead-worker",
        lease_expires_at=datetime.utcnow() - timedelta(seconds=1),
        attempt_count=1,
    )

    claimed = _claim(db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-b")
    assert claimed is not None
    assert claimed.worker_id == "worker-b"
    assert claimed.attempt_count == 2


def test_active_worker_can_renew_lease_but_stale_worker_cannot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    job = _new_job(db)
    claimed = _claim(db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-a")
    assert claimed is not None
    before = claimed.lease_expires_at

    assert _renew_lease(db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-a") is True
    db.refresh(claimed)
    assert claimed.lease_expires_at >= before
    assert _renew_lease(db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-b") is False


def test_reclaimed_job_fences_stale_worker_completion_and_failure():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    stale_db = Session()
    job = _new_job(stale_db)
    stale_claim = _claim(stale_db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-a")
    assert stale_claim is not None

    stale_claim.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    stale_db.commit()
    current_db = Session()
    try:
        current_claim = _claim(current_db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-b")
        assert current_claim is not None
        assert current_claim.worker_id == "worker-b"

        assert _complete(stale_db, stale_claim, {"stale": True}, worker_id="worker-a") == "deferred"
        assert _fail_or_retry(stale_db, job.id, RuntimeError("stale failure"), worker_id="worker-a") == "deferred"

        current_db.expire_all()
        current = current_db.get(IngestionJobState, job.id)
        assert current.status == "running"
        assert current.worker_id == "worker-b"
        assert current.output_json == {}
    finally:
        current_db.close()
        stale_db.close()
