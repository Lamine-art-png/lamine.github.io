from datetime import datetime

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


def test_pending_outbox_row_is_published_once(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    now = datetime.utcnow()
    job = IngestionJobState(tenant_id="tenant-1", job_type="connector_ingest_object", status="queued", input_json={}, output_json={}, attempt_count=0, max_attempts=5, created_at=now, updated_at=now)
    db.add(job)
    db.flush()
    row = TaskOutbox(job_id=job.id, tenant_id="tenant-1", task_type="connector_ingest_object", payload_json={"job_id": job.id}, status="pending", publish_attempts=0, created_at=now, updated_at=now)
    db.add(row)
    db.commit()

    queue = FakeQueue()
    monkeypatch.setattr("app.services.task_outbox_service.get_task_queue", lambda: queue)
    result = publish_pending_outbox(db)
    db.refresh(row)

    assert result == {"published": 1, "failed": 0}
    assert queue.sent == [(job.id, "tenant-1", "connector_ingest_object")]
    assert row.status == "published"
    assert row.published_at is not None
    assert publish_pending_outbox(db) == {"published": 0, "failed": 0}
