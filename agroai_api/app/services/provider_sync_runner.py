from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, update
from sqlalchemy.orm import Session

from app.models.connector_security import ConnectorCredential
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.services.ag_connector_runtime import AG_PROVIDERS, AUTH_ERRORS, RATE_LIMIT_ERRORS, sync_ag_provider
from app.services.connector_vault import load_connector_credentials, store_connector_credentials
from app.services.google_drive_sync import sync_google_drive
from app.services.ingestion_job_runner import _claim, _complete, _fail_or_retry, job_lease_heartbeat
from app.services.outlook_sync import sync_outlook
from app.services.provider_oauth import (
    ProviderOAuthError,
    refresh_provider_credentials,
    scopes_from_payload,
    token_expiry,
)
from app.services.provider_sync_jobs import TASK_TYPE, SUPPORTED_PROVIDERS


async def _access_value(db: Session, connection: ConnectorConnection) -> str:
    payload = load_connector_credentials(db, tenant_id=connection.tenant_id, connection_id=connection.id)
    vault_row = db.query(ConnectorCredential).filter(
        ConnectorCredential.tenant_id == connection.tenant_id,
        ConnectorCredential.connection_id == connection.id,
        ConnectorCredential.revoked_at.is_(None),
    ).one()

    needs_refresh = not payload.get("access_token")
    if vault_row.token_expires_at is not None:
        needs_refresh = needs_refresh or vault_row.token_expires_at <= datetime.utcnow() + timedelta(seconds=90)
    if needs_refresh:
        payload = await refresh_provider_credentials(connection.provider, payload)
        scopes = scopes_from_payload(payload) or list(vault_row.scopes_json or [])
        store_connector_credentials(
            db,
            tenant_id=connection.tenant_id,
            connection=connection,
            provider=connection.provider,
            payload=payload,
            token_expires_at=token_expiry(payload),
            scopes=scopes,
        )
        db.commit()

    value = str(payload.get("access_token") or "")
    if not value:
        raise ProviderOAuthError("provider access credential is unavailable", reconnect_required=True)
    return value


def _reconnect_failure(db: Session, *, job_id: str, exc: ProviderOAuthError, worker_id: str) -> str:
    db.rollback()
    job = db.get(IngestionJob, job_id)
    if job is None:
        return "failed"
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status
    if job.status != "running" or job.worker_id != worker_id:
        return "deferred"

    now = datetime.utcnow()
    connection_id = job.connector_connection_id
    statement = (
        update(IngestionJob)
        .where(
            and_(
                IngestionJob.id == job_id,
                IngestionJob.status == "running",
                IngestionJob.worker_id == worker_id,
            )
        )
        .values(
            status="failed",
            error=str(exc)[:700],
            completed_at=now,
            next_attempt_at=None,
            lease_expires_at=None,
            worker_id=None,
            updated_at=now,
        )
    )
    result = db.execute(statement)
    if result.rowcount != 1:
        db.rollback()
        return "deferred"

    if connection_id:
        connection = db.get(ConnectorConnection, connection_id)
        if connection is not None and connection.tenant_id == job.tenant_id:
            connection.status = "reconnect_required"
            connection.last_error = str(exc)[:700]
            connection.updated_at = now
    db.commit()
    return "failed"


def _persist_connection_failure_state(
    db: Session,
    *,
    connection_id: str | None,
    tenant_id: str,
    state: str,
    exc: Exception,
) -> None:
    if not connection_id:
        return
    connection = db.get(ConnectorConnection, connection_id)
    if connection is None or connection.tenant_id != tenant_id:
        return
    connection.status = state
    connection.last_error = str(exc)[:700]
    connection.updated_at = datetime.utcnow()
    db.commit()


def _retry_with_connection_state(
    db: Session,
    *,
    job_id: str,
    connection_id: str | None,
    tenant_id: str,
    worker_id: str,
    exc: Exception,
    retry_state: str,
) -> str:
    result = _fail_or_retry(db, job_id, exc, worker_id=worker_id)
    if result == "failed":
        _persist_connection_failure_state(
            db,
            connection_id=connection_id,
            tenant_id=tenant_id,
            state="failed",
            exc=exc,
        )
    elif result == "retrying":
        _persist_connection_failure_state(
            db,
            connection_id=connection_id,
            tenant_id=tenant_id,
            state=retry_state,
            exc=exc,
        )
    return result


async def process_provider_sync_job(
    db: Session,
    *,
    job_id: str,
    tenant_id: str,
    worker_id: str,
) -> str:
    job = _claim(db, job_id=job_id, tenant_id=tenant_id, worker_id=worker_id)
    if job is None:
        return "deferred"
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status
    if job.job_type != TASK_TYPE:
        return _fail_or_retry(db, job_id, RuntimeError("worker task type mismatch"), worker_id=worker_id)

    connection_id = job.connector_connection_id
    with job_lease_heartbeat(job_id=job_id, tenant_id=tenant_id, worker_id=worker_id) as heartbeat:
        try:
            connection = db.get(ConnectorConnection, connection_id)
            if connection is None or connection.tenant_id != tenant_id:
                raise RuntimeError("provider sync connection is unavailable")
            if connection.provider not in SUPPORTED_PROVIDERS:
                raise RuntimeError("provider sync adapter is unavailable")
            if connection.status not in {"connected", "synced", "syncing", "rate_limited", "degraded"} or not connection.credentials_ref:
                raise ProviderOAuthError("provider authorization is not active", reconnect_required=True)

            connection.status = "syncing"
            connection.updated_at = datetime.utcnow()
            db.commit()

            if connection.provider in AG_PROVIDERS:
                output = await sync_ag_provider(db, connection=connection)
            else:
                access_value = await _access_value(db, connection)
                if heartbeat.lost:
                    db.rollback()
                    return "deferred"
                if connection.provider == "google_drive":
                    output = await sync_google_drive(db, connection=connection, access_value=access_value)
                else:
                    output = await sync_outlook(db, connection, access_value)

            if heartbeat.lost:
                db.rollback()
                return "deferred"

            job = db.get(IngestionJob, job_id)
            connection = db.get(ConnectorConnection, connection.id)
            if job is None or connection is None:
                raise RuntimeError("provider sync state disappeared")
            connection.status = "synced"
            connection.last_sync_at = datetime.utcnow()
            connection.last_error = None
            connection.updated_at = datetime.utcnow()
            return _complete(db, job, output, worker_id=worker_id)
        except AUTH_ERRORS as exc:
            return _reconnect_failure(
                db,
                job_id=job_id,
                exc=ProviderOAuthError(str(exc), reconnect_required=True),
                worker_id=worker_id,
            )
        except RATE_LIMIT_ERRORS as exc:
            return _retry_with_connection_state(
                db,
                job_id=job_id,
                connection_id=connection_id,
                tenant_id=tenant_id,
                worker_id=worker_id,
                exc=exc,
                retry_state="rate_limited",
            )
        except ProviderOAuthError as exc:
            if exc.reconnect_required:
                return _reconnect_failure(db, job_id=job_id, exc=exc, worker_id=worker_id)
            return _retry_with_connection_state(
                db,
                job_id=job_id,
                connection_id=connection_id,
                tenant_id=tenant_id,
                worker_id=worker_id,
                exc=exc,
                retry_state="degraded",
            )
        except Exception as exc:
            return _retry_with_connection_state(
                db,
                job_id=job_id,
                connection_id=connection_id,
                tenant_id=tenant_id,
                worker_id=worker_id,
                exc=exc,
                retry_state="degraded",
            )
