from __future__ import annotations

import hashlib
import os
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from app.api.v1.connectors import create_or_get_connection
from app.core.config import settings
from app.db.base import SessionLocal
from app.models.operational_records import DataSource, EvidenceRecord, IngestionJob
from app.models.saas import Organization, User, Workspace
from app.models.task_outbox import TaskOutbox
from app.services.durable_ingestion_staging import stage_durable_object_job
from app.services.object_storage import get_object_store
from app.services.redis_task_queue import get_task_queue


TIMEOUT_SECONDS = int(os.getenv("RUNTIME_SMOKE_TIMEOUT_SECONDS", "90"))


def seed_context() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        user = User(
            email=f"runtime-smoke-{suffix}@example.invalid",
            name="Runtime Smoke",
            password_hash="integration-only",
            email_verification_status="verified",
            email_verified_at=datetime.utcnow(),
        )
        db.add(user)
        db.flush()
        organization = Organization(
            name="Runtime Smoke",
            slug=f"runtime-smoke-{suffix}",
            owner_user_id=user.id,
            plan="enterprise",
            subscription_status="active",
        )
        db.add(organization)
        db.flush()
        workspace = Workspace(
            organization_id=organization.id,
            name="Runtime Workspace",
            crop="Almonds",
            region="California",
            mode="production-smoke",
        )
        db.add(workspace)
        db.commit()
        return organization.id, workspace.id
    finally:
        db.close()


def wait_for_job(job_id: str) -> IngestionJob:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            job = db.get(IngestionJob, job_id)
            if job is not None and job.status in {"succeeded", "failed", "cancelled"}:
                db.expunge(job)
                return job
        finally:
            db.close()
        time.sleep(0.5)
    raise RuntimeError(f"job {job_id} did not reach terminal state")


def main() -> None:
    tenant_id, workspace_id = seed_context()
    db = SessionLocal()
    temp_path: Path | None = None
    try:
        connection = create_or_get_connection(
            db,
            tenant_id=tenant_id,
            provider="manual_csv",
            workspace_id=workspace_id,
            mode="manual_upload",
            config={"created_by": "distributed_runtime_smoke"},
        )
        payload = (
            "timestamp,field,block,crop,flow_gpm,duration_minutes,water_gallons,note\n"
            "2026-07-05T06:00:00Z,North Ranch,Block 7,Almonds,420,45,18900,runtime smoke\n"
        ).encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()
        with tempfile.NamedTemporaryFile(prefix="agroai-runtime-", suffix=".csv", delete=False) as handle:
            handle.write(payload)
            temp_path = Path(handle.name)

        store = get_object_store()
        stored = store.put_path(
            temp_path,
            tenant_id=tenant_id,
            connection_id=connection.id,
            filename="runtime-smoke.csv",
            content_type="text/csv",
            expected_sha256=checksum,
            expected_size=len(payload),
        )
        job, deduplicated = stage_durable_object_job(
            db,
            store=store,
            stored=stored,
            tenant_id=tenant_id,
            connection=connection,
            filename="runtime-smoke.csv",
            content_type="text/csv",
        )
        if deduplicated:
            raise RuntimeError("first runtime smoke object unexpectedly deduplicated")
        job_id = job.id
    finally:
        db.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    terminal = wait_for_job(job_id)
    if terminal.status != "succeeded":
        raise RuntimeError(f"worker job failed: {terminal.status}: {terminal.error}")

    db = SessionLocal()
    try:
        source = db.query(DataSource).filter(
            DataSource.tenant_id == tenant_id,
            DataSource.content_sha256 == checksum,
        ).one_or_none()
        if source is None or not str(source.storage_path or "").startswith("s3://"):
            raise RuntimeError("worker did not persist durable data source identity")
        evidence_count = db.query(EvidenceRecord).filter(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.data_source_id == source.id,
        ).count()
        if evidence_count < 1:
            raise RuntimeError("worker did not persist evidence records")
        outbox = db.query(TaskOutbox).filter(TaskOutbox.job_id == job_id).one_or_none()
        if outbox is None or outbox.status != "published":
            raise RuntimeError("transactional outbox did not reach published state")
    finally:
        db.close()

    pending = get_task_queue().pending_count()
    if pending != 0:
        raise RuntimeError(f"Redis consumer group has {pending} pending entries after ACK")

    print(
        "RUNTIME_SMOKE_OK",
        {
            "job_id": job_id,
            "checksum": checksum,
            "evidence_records": evidence_count,
            "queue_pending": pending,
            "object_uri": source.storage_path,
        },
    )


if __name__ == "__main__":
    main()
