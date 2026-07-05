from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.hardened_records import IngestionJobState
from app.services.ingestion_job_runner import _claim


def test_job_lease_prevents_concurrent_worker_claims(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    now = datetime.utcnow()
    job = IngestionJobState(tenant_id="tenant-1", job_type="connector_ingest_object", status="queued", input_json={}, output_json={}, attempt_count=0, max_attempts=5, created_at=now, updated_at=now)
    db.add(job)
    db.commit()

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
    now = datetime.utcnow()
    job = IngestionJobState(tenant_id="tenant-1", job_type="connector_ingest_object", status="running", input_json={}, output_json={}, attempt_count=1, max_attempts=5, worker_id="dead-worker", lease_expires_at=now - timedelta(seconds=1), created_at=now, updated_at=now)
    db.add(job)
    db.commit()

    claimed = _claim(db, job_id=job.id, tenant_id="tenant-1", worker_id="worker-b")
    assert claimed is not None
    assert claimed.worker_id == "worker-b"
    assert claimed.attempt_count == 2
