from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import AuthContext, get_auth_context
from app.db.base import Base, get_db
from app.main import app
from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord, IngestionJob
from app.models.saas import Organization, OrganizationMembership, UsageEvent, User, Workspace
from app.models.task_outbox import TaskOutbox


class FakeObjectStore:
    def __init__(self):
        self.deleted: list[tuple[str, dict]] = []

    def delete(self, uri: str, **kwargs):
        self.deleted.append((uri, dict(kwargs)))


def _runtime(role: str = "operator"):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    with Session() as db:
        user = User(id="source-user", email="source-user@example.com", password_hash="x", is_active=True)
        org = Organization(
            id="source-org",
            name="Source Delete Org",
            slug="source-delete-org",
            owner_user_id=user.id,
            plan="enterprise",
            subscription_status="active",
        )
        db.add(user)
        db.flush()
        db.add(org)
        db.flush()
        membership = OrganizationMembership(
            id="source-membership",
            organization_id=org.id,
            user_id=user.id,
            role=role,
        )
        workspace = Workspace(id="source-workspace", organization_id=org.id, name="Source operation", mode="evaluation")
        connection = ConnectorConnection(
            id="source-connection",
            tenant_id=org.id,
            workspace_id=workspace.id,
            provider="manual_csv",
            display_name="Manual upload",
            status="synced",
            mode="manual_upload",
            required_plan="free",
            config_json={},
        )
        db.add_all([membership, workspace, connection])
        db.commit()
        db.refresh(user)
        db.refresh(org)
        db.refresh(membership)
        auth = AuthContext(user=user, organization=org, membership=membership)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_auth_context] = lambda: auth
    return Session, auth


def _cleanup_overrides():
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_auth_context, None)


def test_completed_source_delete_removes_object_evidence_jobs_and_allows_reupload(monkeypatch):
    Session, _auth = _runtime()
    fake = FakeObjectStore()
    monkeypatch.setattr("app.services.source_deletion.get_object_store", lambda: fake)
    with Session() as db:
        source = DataSource(
            id="source-complete",
            tenant_id="source-org",
            workspace_id="source-workspace",
            connector_connection_id="source-connection",
            provider="manual_csv",
            source_type="telemetry_csv",
            filename="field-data.csv",
            content_type="text/csv",
            storage_path="s3://agroai-test/agroai/tenants/source/raw/field-data.csv",
            raw_text="field,value\nA,1\n",
            metadata_json={"rows_parsed": 1, "durable_object_uri": "s3://agroai-test/agroai/tenants/source/raw/field-data.csv"},
            status="parsed",
            content_sha256="a" * 64,
            object_size_bytes=18,
        )
        db.add(source)
        db.flush()
        db.add(
            EvidenceRecord(
                id="source-evidence",
                tenant_id="source-org",
                workspace_id="source-workspace",
                data_source_id=source.id,
                connector_connection_id="source-connection",
                evidence_type="uploaded_record",
                title="Field A",
                summary="Value 1",
                value_json={"field": "A", "value": 1},
                confidence=0.9,
                quality_status="usable",
                citation_label="manual_csv:field-data.csv:1",
                metadata_json={},
            )
        )
        job = IngestionJob(
            id="source-job",
            tenant_id="source-org",
            workspace_id="source-workspace",
            connector_connection_id="source-connection",
            data_source_id=source.id,
            job_type="connector_ingest_object",
            status="succeeded",
            input_json={"object_uri": source.storage_path, "filename": source.filename},
            output_json={"data_source_id": source.id},
            idempotency_key="b" * 64,
            attempt_count=1,
            max_attempts=5,
            completed_at=datetime.utcnow(),
        )
        db.add(job)
        db.flush()
        db.add(TaskOutbox(job_id=job.id, tenant_id="source-org", task_type="connector_ingest_object", payload_json={"job_id": job.id}, status="published"))
        db.commit()

    try:
        response = TestClient(app).delete("/v1/source-library/source-complete")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "deleted"
        assert body["evidence_deleted"] == 1
        assert body["jobs_deleted"] == 1
        assert body["object_deleted"] is True
        assert fake.deleted == [(
            "s3://agroai-test/agroai/tenants/source/raw/field-data.csv",
            {"tenant_id": "source-org", "connection_id": "source-connection"},
        )]

        with Session() as db:
            assert db.get(DataSource, "source-complete") is None
            assert db.get(EvidenceRecord, "source-evidence") is None
            assert db.get(IngestionJob, "source-job") is None
            assert db.query(TaskOutbox).filter(TaskOutbox.job_id == "source-job").count() == 0
            event = db.query(UsageEvent).filter(UsageEvent.event_type == "source_deleted").one()
            assert event.metadata_json["filename"] == "field-data.csv"
    finally:
        _cleanup_overrides()


def test_pending_upload_can_be_cancelled_and_deleted(monkeypatch):
    Session, _auth = _runtime()
    fake = FakeObjectStore()
    monkeypatch.setattr("app.services.source_deletion.get_object_store", lambda: fake)
    with Session() as db:
        job = IngestionJob(
            id="pending-job",
            tenant_id="source-org",
            workspace_id="source-workspace",
            connector_connection_id="source-connection",
            job_type="connector_ingest_object",
            status="queued",
            input_json={
                "object_uri": "s3://agroai-test/agroai/tenants/source/raw/pending.pdf",
                "filename": "pending.pdf",
                "connection_id": "source-connection",
            },
            output_json={},
            idempotency_key="c" * 64,
            attempt_count=0,
            max_attempts=5,
        )
        db.add(job)
        db.flush()
        db.add(TaskOutbox(job_id=job.id, tenant_id="source-org", task_type="connector_ingest_object", payload_json={"job_id": job.id}, status="pending"))
        db.commit()

    try:
        response = TestClient(app).delete("/v1/source-library/job:pending-job")
        assert response.status_code == 200, response.text
        assert response.json()["pending_upload"] is True
        with Session() as db:
            assert db.get(IngestionJob, "pending-job") is None
            assert db.query(TaskOutbox).filter(TaskOutbox.job_id == "pending-job").count() == 0
        assert fake.deleted[0][0].endswith("pending.pdf")
    finally:
        _cleanup_overrides()


def test_running_upload_delete_fails_closed(monkeypatch):
    Session, _auth = _runtime()
    fake = FakeObjectStore()
    monkeypatch.setattr("app.services.source_deletion.get_object_store", lambda: fake)
    with Session() as db:
        db.add(
            IngestionJob(
                id="running-job",
                tenant_id="source-org",
                workspace_id="source-workspace",
                connector_connection_id="source-connection",
                job_type="connector_ingest_object",
                status="running",
                input_json={"object_uri": "s3://agroai-test/agroai/tenants/source/raw/running.csv", "filename": "running.csv"},
                output_json={},
                attempt_count=1,
                max_attempts=5,
                worker_id="worker-1",
            )
        )
        db.commit()

    try:
        response = TestClient(app).delete("/v1/source-library/job:running-job")
        assert response.status_code == 409, response.text
        with Session() as db:
            assert db.get(IngestionJob, "running-job") is not None
        assert fake.deleted == []
    finally:
        _cleanup_overrides()


def test_viewer_cannot_delete_sources(monkeypatch):
    Session, _auth = _runtime(role="viewer")
    fake = FakeObjectStore()
    monkeypatch.setattr("app.services.source_deletion.get_object_store", lambda: fake)
    with Session() as db:
        db.add(
            DataSource(
                id="viewer-source",
                tenant_id="source-org",
                workspace_id="source-workspace",
                connector_connection_id="source-connection",
                provider="manual_csv",
                source_type="text",
                filename="viewer.txt",
                content_type="text/plain",
                storage_path="/tmp/viewer.txt",
                raw_text="viewer",
                metadata_json={},
                status="parsed",
            )
        )
        db.commit()

    try:
        response = TestClient(app).delete("/v1/source-library/viewer-source")
        assert response.status_code == 403, response.text
        with Session() as db:
            assert db.get(DataSource, "viewer-source") is not None
    finally:
        _cleanup_overrides()
