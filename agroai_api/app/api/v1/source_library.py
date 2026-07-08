from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import DataSource, EvidenceRecord, IngestionJob
from app.models.saas import Workspace
from app.services.operator_cockpit import build_context, readiness_summary
from app.services.source_content import content_available, parsed_rows_preview, source_content_excerpt


router = APIRouter(tags=["source-library"])


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _metadata(source: DataSource) -> dict[str, Any]:
    return dict(source.metadata_json or {}) if isinstance(source.metadata_json, dict) else {}


def _job_source_id(job: IngestionJob) -> str | None:
    output = job.output_json if isinstance(job.output_json, dict) else {}
    return str(output.get("data_source_id") or job.data_source_id or "") or None


def _latest_jobs(db: Session, tenant_id: str) -> dict[str, IngestionJob]:
    jobs = (
        db.query(IngestionJob)
        .filter(IngestionJob.tenant_id == tenant_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1_000)
        .all()
    )
    latest: dict[str, IngestionJob] = {}
    for job in jobs:
        source_id = _job_source_id(job)
        if source_id and source_id not in latest:
            latest[source_id] = job
    return latest


def _evidence_counts(db: Session, tenant_id: str) -> dict[str, int]:
    rows = (
        db.query(EvidenceRecord.data_source_id, func.count(EvidenceRecord.id))
        .filter(EvidenceRecord.tenant_id == tenant_id, EvidenceRecord.data_source_id.is_not(None))
        .group_by(EvidenceRecord.data_source_id)
        .all()
    )
    return {str(source_id): int(count or 0) for source_id, count in rows if source_id}


def source_public(source: DataSource, *, evidence_count: int = 0, job: IngestionJob | None = None) -> dict[str, Any]:
    metadata = _metadata(source)
    warnings = metadata.get("warnings") if isinstance(metadata.get("warnings"), list) else []
    mapping = metadata.get("mapping_suggestions") or metadata.get("mapping") or {}
    durable = bool(str(source.storage_path or "").startswith(("s3://", "r2://"))) or bool(metadata.get("durable_object_uri"))
    job_status = job.status if job is not None else None
    return {
        "id": source.id,
        "workspace_id": source.workspace_id,
        "connection_id": source.connector_connection_id,
        "provider": source.provider,
        "source_type": source.source_type,
        "filename": source.filename,
        "content_type": source.content_type,
        "status": source.status,
        "processing_status": job_status,
        "rows_parsed": int(metadata.get("rows_parsed") or 0),
        "evidence_count": int(evidence_count),
        "mapping_count": len(mapping) if isinstance(mapping, dict) else 0,
        "warning_count": len(warnings),
        "warnings": [str(item)[:300] for item in warnings[:8]],
        "size_bytes": int(source.object_size_bytes or metadata.get("object_size_bytes") or 0),
        "checksum_verified": bool(source.content_sha256 or metadata.get("content_sha256")),
        "durable_stored": durable,
        "intelligence_ready": bool(evidence_count) or content_available(source),
        "created_at": _iso(source.created_at),
        "job_updated_at": _iso(job.updated_at) if job is not None else None,
        "job_completed_at": _iso(job.completed_at) if job is not None else None,
    }


def _source_query(db: Session, tenant_id: str, workspace_id: str | None):
    query = db.query(DataSource).filter(DataSource.tenant_id == tenant_id)
    if workspace_id:
        query = query.filter(or_(DataSource.workspace_id == workspace_id, DataSource.workspace_id.is_(None)))
    return query


@router.get("/source-library")
def list_source_library(
    workspace_id: str | None = Query(default=None),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sources = _source_query(db, tenant_id, workspace_id).order_by(DataSource.created_at.desc()).limit(500).all()
    counts = _evidence_counts(db, tenant_id)
    jobs = _latest_jobs(db, tenant_id)
    return {
        "status": "ok",
        "source_count": len(sources),
        "sources": [source_public(source, evidence_count=counts.get(source.id, 0), job=jobs.get(source.id)) for source in sources],
    }


@router.get("/source-library/summary")
def source_library_summary(
    workspace_id: str | None = Query(default=None),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    workspace = None
    if workspace_id:
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.organization_id == tenant_id).first()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

    ctx = build_context(db, tenant_id, workspace)
    readiness = readiness_summary(ctx)
    by_provider = Counter(source.provider for source in ctx.sources)
    by_type = Counter(record.evidence_type for record in ctx.evidence)
    return {
        "status": "ok",
        "evidence_count": len(ctx.evidence),
        "source_count": len(ctx.sources),
        "uploaded_files": len([source for source in ctx.sources if source.filename]),
        "readiness_score": int(readiness.get("readiness_score") or 0),
        "readiness_level": readiness.get("readiness_level"),
        "missing_data": list(readiness.get("missing_source_types") or []),
        "by_type": dict(by_type),
        "by_provider": dict(by_provider),
        "last_import_at": readiness.get("last_import_at"),
    }


@router.get("/source-library/{source_id}")
def source_library_detail(
    source_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = db.get(DataSource, source_id)
    if source is None or source.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Source not found")

    evidence = (
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.tenant_id == tenant_id, EvidenceRecord.data_source_id == source.id)
        .order_by(EvidenceRecord.created_at.desc())
        .limit(30)
        .all()
    )
    jobs = _latest_jobs(db, tenant_id)
    public = source_public(source, evidence_count=len(evidence), job=jobs.get(source.id))
    return {
        "status": "ok",
        "source": {
            **public,
            "content_excerpt": source_content_excerpt(source, max_chars=8_000),
            "parsed_rows_preview": parsed_rows_preview(source, limit=20),
        },
        "evidence": [
            {
                "id": row.id,
                "type": row.evidence_type,
                "title": row.title,
                "summary": row.summary,
                "quality_status": row.quality_status,
                "citation_label": row.citation_label,
                "occurred_at": _iso(row.occurred_at),
                "created_at": _iso(row.created_at),
            }
            for row in evidence
        ],
    }
