from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app
from app.models.saas import Organization, User
from app.services.object_storage import StoredObject


class FakeObjectStore:
    def __init__(self):
        self.uploaded = []
        self.deleted = []

    def put_path(self, path, **kwargs):
        self.uploaded.append((str(path), dict(kwargs)))
        return StoredObject(
            uri="s3://agroai-test/raw/object.csv",
            key="raw/object.csv",
            size_bytes=int(kwargs["expected_size"]),
            sha256=str(kwargs["expected_sha256"]),
            content_type=kwargs.get("content_type"),
        )

    def delete(self, uri, **_kwargs):
        self.deleted.append(uri)


def test_stream_route_stages_durable_object_and_republishes_deduplicated_retry(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    with Session() as db:
        owner = User(id="owner-test", email="owner@example.com", password_hash="x")
        db.add(owner)
        db.flush()
        db.add(
            Organization(
                id="org-test",
                name="Manual Ingestion Test Org",
                slug="manual-ingestion-test-org",
                owner_user_id=owner.id,
                plan="free",
            )
        )
        db.commit()

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    publication_calls = []

    def fake_outbox_drain(**kwargs):
        publication_calls.append(dict(kwargs))
        return {"published": 1, "failed": 0}

    async def no_op_fallback(_job_id, _tenant_id):
        return None

    fake = FakeObjectStore()
    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "CONNECTOR_OBJECT_BUCKET", "agroai-test")
    monkeypatch.setattr(settings, "TASK_QUEUE_BACKEND", "redis_streams")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://queue.example/0")
    monkeypatch.setattr("app.api.v1.connector_stream_api.get_object_store", lambda: fake)
    monkeypatch.setattr("app.api.v1.connector_stream_api.drain_pending_outbox", fake_outbox_drain)
    monkeypatch.setattr("app.api.v1.connector_stream_secure._inline_processing_fallback", no_op_fallback)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-test"
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/evidence/upload-stream?provider=manual_csv",
            files={"file": ("sample.csv", BytesIO(b"timestamp,value\n2026-07-05,42\n"), "text/csv")},
        )
        duplicate = client.post(
            "/v1/evidence/upload-stream?provider=manual_csv",
            files={"file": ("sample.csv", BytesIO(b"timestamp,value\n2026-07-05,42\n"), "text/csv")},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_current_tenant_id, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["phase"] == "stored"
    assert body["durable_stored"] is True
    assert body["processing_pending"] is True
    assert body["job_id"]
    assert body["queue_publication"] == {"published": 1, "failed": 0}
    assert body["processing_fallback_scheduled"] is True
    assert "object_uri" not in body
    assert fake.uploaded

    assert duplicate.status_code == 200, duplicate.text
    duplicate_body = duplicate.json()
    assert duplicate_body["job_id"] == body["job_id"]
    assert duplicate_body["deduplicated"] is True
    assert duplicate_body["queue_publication"] == {"published": 1, "failed": 0}
    assert duplicate_body["processing_fallback_scheduled"] is True
    assert len(publication_calls) == 2
    assert fake.deleted == ["s3://agroai-test/raw/object.csv"]
