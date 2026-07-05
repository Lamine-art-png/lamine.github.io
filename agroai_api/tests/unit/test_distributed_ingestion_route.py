from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app
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

    def delete(self, uri):
        self.deleted.append(uri)


def test_stream_route_stages_durable_object_and_outbox(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    fake = FakeObjectStore()
    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "CONNECTOR_OBJECT_BUCKET", "agroai-test")
    monkeypatch.setattr(settings, "TASK_QUEUE_BACKEND", "redis_streams")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://queue.example/0")
    monkeypatch.setattr("app.api.v1.connector_stream_api.get_object_store", lambda: fake)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-test"
    try:
        response = TestClient(app).post(
            "/v1/evidence/upload-stream?provider=manual_csv",
            files={"file": ("sample.csv", BytesIO(b"timestamp,value\n2026-07-05,42\n"), "text/csv")},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_current_tenant_id, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["object_uri"] == "s3://agroai-test/raw/object.csv"
    assert body["job_id"]
    assert fake.uploaded
