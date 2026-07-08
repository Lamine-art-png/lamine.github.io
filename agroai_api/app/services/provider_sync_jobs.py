from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.v1.connectors import CATALOG
from app.core.config import settings
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.models.task_outbox import TaskOutbox


TASK_TYPE = "connector_provider_sync"
SUPPORTED_PROVIDERS = {"google_drive", "outlook", "john_deere", "wiseconn", "talgil", "openet"}

JOHN_DEERE_CATALOG_ITEM = {
    "id": "john_deere",
    "name": "John Deere Operations Center",
    "category": "Farm operations platforms",
    "status": "not_configured",
    "required_plan": "professional",
    "connection_methods": ["oauth"],
    "upload_supported": False,
    "imports": [
        "organizations",
        "clients",
        "farms",
        "fields",
        "boundaries",
        "field operations",
        "equipment reference",
        "crop types",
        "guidance lines",
        "users",
        "organization settings",
    ],
    "used_by": ["Ask AGRO-AI", "Decisions", "Evidence", "Reports", "Assurance"],
    "promise": "Authorize an Operations Center customer account for approved read-only operational context. Work Plans are excluded from phase one.",
    "required_env": ["JOHN_DEERE_OAUTH_CLIENT_ID", "JOHN_DEERE_OAUTH_CLIENT_SECRET"],
}

# `create_or_get_connection` validates against the canonical catalog. Register the
# provider once at import time so OAuth launch, catalog readiness, connection
# metadata, and durable sync all agree on the same first-class provider id.
if not any(item.get("id") == "john_deere" for item in CATALOG):
    CATALOG.append(JOHN_DEERE_CATALOG_ITEM)


def queue_provider_sync(db: Session, *, tenant_id: str, connection: ConnectorConnection) -> tuple[IngestionJob, bool]:
    if connection.tenant_id != tenant_id:
        raise ValueError("provider sync ownership mismatch")
    if connection.provider not in SUPPORTED_PROVIDERS:
        raise ValueError("provider does not have a production sync adapter")

    existing = db.query(IngestionJob).filter(
        IngestionJob.tenant_id == tenant_id,
        IngestionJob.connector_connection_id == connection.id,
        IngestionJob.job_type == TASK_TYPE,
        IngestionJob.status.in_(["queued", "running", "retrying"]),
    ).order_by(IngestionJob.created_at.desc()).first()
    if existing is not None:
        return existing, True

    now = datetime.utcnow()
    request_id = uuid.uuid4().hex
    identity = hashlib.sha256(
        f"{tenant_id}|{connection.id}|{TASK_TYPE}|{request_id}".encode("utf-8")
    ).hexdigest()
    job = IngestionJob(
        tenant_id=tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        job_type=TASK_TYPE,
        status="queued",
        input_json={"provider": connection.provider, "connection_id": connection.id},
        output_json={},
        idempotency_key=identity,
        attempt_count=0,
        max_attempts=int(getattr(settings, "TASK_QUEUE_MAX_ATTEMPTS", 5) or 5),
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    db.add(
        TaskOutbox(
            job_id=job.id,
            tenant_id=tenant_id,
            task_type=TASK_TYPE,
            payload_json={"job_id": job.id, "provider": connection.provider},
            status="pending",
            publish_attempts=0,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    db.refresh(job)
    return job, False
