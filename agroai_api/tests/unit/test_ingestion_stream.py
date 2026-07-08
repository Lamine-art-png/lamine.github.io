import asyncio
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app
from app.models.operational_records import IngestionJob
from app.models.saas import Organization, User
from app.services.ingestion_stream import read_spooled_bytes, stream_upload_to_spool


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(data))


def test_stream_upload_writes_file_with_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CONNECTOR_MAX_UPLOAD_BYTES", "1048576")
    monkeypatch.setenv("CONNECTOR_STREAM_CHUNK_BYTES", "65536")
    payload = b"timestamp,value\n" + b"2026-07-05,1\n" * 5000

    receipt = asyncio.run(
        stream_upload_to_spool(
            _upload("telemetry.csv", payload),
            tenant_id="tenant-1",
            connection_id="connection-1",
        )
    )

    assert receipt.size_bytes == len(payload)
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()
    assert Path(receipt.path).is_file()
    assert read_spooled_bytes(receipt) == payload


def test_stream_upload_rejects_oversize_and_cleans_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CONNECTOR_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("CONNECTOR_STREAM_CHUNK_BYTES", "65536")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            stream_upload_to_spool(
                _upload("large.csv", b"x" * 2048),
                tenant_id="tenant-1",
                connection_id="connection-1",
            )
        )

    assert exc.value.status_code == 413
    assert not list(tmp_path.rglob("*.part"))
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_checksum_change_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CONNECTOR_MAX_UPLOAD_BYTES", "1048576")
    receipt = asyncio.run(
        stream_upload_to_spool(
            _upload("evidence.csv", b"a,b\n1,2\n"),
            tenant_id="tenant-1",
            connection_id="connection-1",
        )
    )
    Path(receipt.path).write_bytes(b"changed")

    with pytest.raises(RuntimeError):
        read_spooled_bytes(receipt)


def _testing_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        owner = User(id="owner-test", email="owner@example.com", password_hash="x")
        db.add(owner)
        db.flush()
        db.add(
            Organization(
                id="org-test",
                name="Stream Test Org",
                slug="stream-test-org",
                owner_user_id=owner.id,
                plan="free",
            )
        )
        db.commit()
    return TestingSessionLocal


def _override_db_factory(TestingSessionLocal):
    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
    return override_db


def test_stream_upload_route_uses_worker_owned_session(tmp_path, monkeypatch):
    TestingSessionLocal = _testing_db()

    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.services.connector_ingestion_pipeline.SessionLocal", TestingSessionLocal)

    app.dependency_overrides[get_db] = _override_db_factory(TestingSessionLocal)
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-test"
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/evidence/upload-stream?provider=manual_csv",
            files={
                "file": (
                    "sample.csv",
                    BytesIO(b"timestamp,field,flow_gpm\n2026-07-05 06:00,North,42\n"),
                    "text/csv",
                )
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_current_tenant_id, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["upload_receipt"]["streamed"] is True
    assert body["rows_parsed"] == 1
    assert body["evidence_records_created"] == 1


def test_ingestion_job_status_receipt_is_tenant_scoped():
    TestingSessionLocal = _testing_db()
    with TestingSessionLocal() as db:
        job = IngestionJob(
            id="job-visible",
            tenant_id="org-test",
            job_type="connector_ingest_object",
            status="succeeded",
            output_json={
                "data_source_id": "source-123",
                "rows_parsed": 7,
                "evidence_records_created": 4,
                "content_sha256": "a" * 64,
                "object_uri": "s3://must-not-leak/private-object",
            },
        )
        db.add(job)
        db.commit()

    app.dependency_overrides[get_db] = _override_db_factory(TestingSessionLocal)
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-test"
    try:
        client = TestClient(app)
        response = client.get("/v1/connectors/jobs/job-visible")
        assert response.status_code == 200, response.text
        body = response.json()["job"]
        assert body["status"] == "succeeded"
        assert body["data_source_id"] == "source-123"
        assert body["rows_parsed"] == 7
        assert body["evidence_records_created"] == 4
        assert "object_uri" not in body
        assert "content_sha256" not in body

        app.dependency_overrides[require_current_tenant_id] = lambda: "other-org"
        hidden = client.get("/v1/connectors/jobs/job-visible")
        assert hidden.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_current_tenant_id, None)
