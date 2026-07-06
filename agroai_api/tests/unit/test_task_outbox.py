from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.hardened_records import IngestionJobState
from app.models.task_outbox import TaskOutbox
from app.services.task_outbox_service import publish_pending_outbox


class FakeQueue:
    def __init__(self):
        self.sent = []

    def enqueue(self, job_id, tenant_id, task_type):
        self.sent.append((job_id, tenant_id, task_type))
        return "1-0"


def _pending_row(db):
    now = datetime.utcnow()
    job = IngestionJobState(
        tenant_id="tenant-1",
        job_type="connector_ingest_object",
        status="queued",
        input_json={},
        output_json={},
        attempt_count=0,
        max_attempts=5,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    row = TaskOutbox(
        job_id=job.id,
        tenant_id="tenant-1",
        task_type="connector_ingest_object",
        payload_json={"job_id": job.id},
        status="pending",
        publish_attempts=0,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    return job, row


def test_pending_outbox_row_is_published_once(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    job, row = _pending_row(db)

    queue = FakeQueue()
    monkeypatch.setattr("app.services.task_outbox_service.get_task_publisher", lambda: queue)
    result = publish_pending_outbox(db)
    db.refresh(row)

    assert result == {"published": 1, "failed": 0}
    assert queue.sent == [(job.id, "tenant-1", "connector_ingest_object")]
    assert row.status == "published"
    assert row.published_at is not None
    assert publish_pending_outbox(db) == {"published": 0, "failed": 0}


def test_atomic_publication_claim_blocks_reentrant_duplicate_drain(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    first_db = Session()
    second_db = Session()
    job, _row = _pending_row(first_db)

    class ReentrantQueue(FakeQueue):
        def __init__(self):
            super().__init__()
            self.nested_result = None

        def enqueue(self, job_id, tenant_id, task_type):
            if self.nested_result is None:
                self.nested_result = publish_pending_outbox(second_db)
            return super().enqueue(job_id, tenant_id, task_type)

    queue = ReentrantQueue()
    monkeypatch.setattr("app.services.task_outbox_service.get_task_publisher", lambda: queue)
    try:
        result = publish_pending_outbox(first_db)
        assert result == {"published": 1, "failed": 0}
        assert queue.nested_result == {"published": 0, "failed": 0}
        assert queue.sent == [(job.id, "tenant-1", "connector_ingest_object")]
    finally:
        second_db.close()
        first_db.close()


def test_stale_publication_claim_is_recovered(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    job, row = _pending_row(db)
    row.status = "publishing"
    row.updated_at = datetime.utcnow() - timedelta(minutes=10)
    db.commit()

    queue = FakeQueue()
    monkeypatch.setattr("app.services.task_outbox_service.get_task_publisher", lambda: queue)
    result = publish_pending_outbox(db)
    db.refresh(row)

    assert result == {"published": 1, "failed": 0}
    assert queue.sent == [(job.id, "tenant-1", "connector_ingest_object")]
    assert row.status == "published"
