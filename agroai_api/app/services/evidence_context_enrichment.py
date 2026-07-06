from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.hardened_records import EvidenceFreshnessState
from app.models.operational_records import DataSource, EvidenceRecord


def enrich_evidence_context(db: Session, context: Any, *, tenant_id: str) -> Any:
    evidence = list(getattr(context, "evidence", []) or [])
    ids = {str(item.get("id")) for item in evidence if isinstance(item, dict) and item.get("id")}
    if not ids:
        return context

    records = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id, EvidenceRecord.id.in_(ids)).all()
    record_by_id = {row.id: row for row in records}
    freshness_rows = db.query(EvidenceFreshnessState).filter(EvidenceFreshnessState.id.in_(ids)).all()
    fresh_by_id = {row.id: row for row in freshness_rows}
    source_ids = {row.data_source_id for row in records if row.data_source_id}
    sources = db.query(DataSource).filter(DataSource.tenant_id == tenant_id, DataSource.id.in_(source_ids)).all() if source_ids else []
    source_by_id = {row.id: row for row in sources}

    for item in evidence:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        row = record_by_id.get(str(item["id"]))
        if row is None:
            continue
        fresh = fresh_by_id.get(row.id)
        source = source_by_id.get(row.data_source_id)
        item.update({
            "type": row.evidence_type,
            "evidence_type": row.evidence_type,
            "title": row.title,
            "summary": row.summary,
            "data_source_id": row.data_source_id,
            "connector_connection_id": row.connector_connection_id,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "source_updated_at": fresh.source_updated_at.isoformat() if fresh and fresh.source_updated_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "citation_label": row.citation_label,
            "quality_status": row.quality_status,
            "confidence": row.confidence,
            "units": row.units,
            "value_json": row.value_json or {},
            "source_excerpt": row.source_excerpt,
            "source_created_at": source.created_at.isoformat() if source and source.created_at else None,
        })
    context.evidence = evidence
    return context
