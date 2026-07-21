"""Exact-SHA release alignment across every Field Intelligence surface.

Broad activation (the ``general`` release state) requires the API build, the
live workers, the deployed portal, the edge gateway and the database schema
revision to agree on one release. The API and workers report their own SHAs;
the portal and edge SHAs are supplied by the deployment pipeline via
configuration (they cannot be read from here). A mismatch never blocks the
API from serving — it blocks *broader activation* and surfaces truthfully in
readiness and admin views.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.field_intelligence import FieldWorkerHeartbeat
from app.services.release_contract import (
    database_alembic_heads,
    repository_alembic_heads,
    runtime_build_sha,
)

_PRODUCTION_ENVS = {"production", "staging"}


def _fresh_worker_shas(db: Session) -> tuple[list[str], int]:
    ttl = int(getattr(settings, "FIELD_WORKER_HEARTBEAT_TTL_SECONDS", 120))
    cutoff = datetime.utcnow() - timedelta(seconds=ttl)
    rows = (
        db.query(FieldWorkerHeartbeat)
        .filter(FieldWorkerHeartbeat.last_heartbeat_at >= cutoff)
        .all()
    )
    shas = sorted({str(row.git_sha or "").strip() for row in rows if row.git_sha})
    return shas, len(rows)


def release_alignment(db: Session) -> dict:
    """Compare API, worker, portal, edge and database-revision identity."""
    is_production = str(getattr(settings, "APP_ENV", "development")).strip().lower() in _PRODUCTION_ENVS
    api_sha = runtime_build_sha() or None
    portal_sha = str(getattr(settings, "FIELD_RELEASE_PORTAL_SHA", "") or "").strip() or None
    edge_sha = str(getattr(settings, "FIELD_RELEASE_EDGE_SHA", "") or "").strip() or None
    try:
        repository_heads = list(repository_alembic_heads())
        database_heads = list(database_alembic_heads(db))
        schema_current = database_heads == repository_heads
    except Exception:  # noqa: BLE001 - alembic_version may not exist yet
        repository_heads, database_heads, schema_current = [], [], False
    worker_shas, live_workers = _fresh_worker_shas(db)

    mismatches: list[str] = []
    if not schema_current:
        mismatches.append("database_revision")
    if is_production:
        if not api_sha:
            mismatches.append("api_sha_unreported")
        if not portal_sha:
            mismatches.append("portal_sha_unreported")
        if not edge_sha:
            mismatches.append("edge_sha_unreported")
        if live_workers == 0:
            mismatches.append("no_live_worker")
    for label, value in (("portal_sha", portal_sha), ("edge_sha", edge_sha)):
        if api_sha and value and value != api_sha:
            mismatches.append(label)
    if api_sha and worker_shas and worker_shas != [api_sha]:
        mismatches.append("worker_sha")

    return {
        "aligned": not mismatches,
        "mismatches": mismatches,
        "api_sha": api_sha,
        "worker_shas": worker_shas,
        "live_workers": live_workers,
        "portal_sha": portal_sha,
        "edge_sha": edge_sha,
        "database_heads": database_heads,
        "repository_heads": repository_heads,
        "production": is_production,
    }
