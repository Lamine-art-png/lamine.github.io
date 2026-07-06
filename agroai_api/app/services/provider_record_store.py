from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord


def parse_observed_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def store_provider_record(
    db: Session,
    *,
    connection: ConnectorConnection,
    object_id: str,
    version: str,
    name: str,
    record_type: str,
    summary: str,
    observed_at: datetime | None,
    metadata: dict[str, Any],
) -> bool:
    digest = hashlib.sha256(
        (connection.provider + "|" + object_id + "|" + version).encode("utf-8")
    ).hexdigest()
    existing = db.query(DataSource).filter(
        DataSource.tenant_id == connection.tenant_id,
        DataSource.connector_connection_id == connection.id,
        DataSource.content_sha256 == digest,
    ).first()
    if existing is not None:
        return False

    source = DataSource(
        tenant_id=connection.tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        source_type=record_type,
        provider=connection.provider,
        filename=name[:500],
        content_type=None,
        storage_path=None,
        raw_text=summary[:5000],
        metadata_json=metadata,
        status="indexed",
        content_sha256=digest,
    )
    db.add(source)
    db.flush()
    evidence = EvidenceRecord(
        tenant_id=connection.tenant_id,
        workspace_id=connection.workspace_id,
        data_source_id=source.id,
        connector_connection_id=connection.id,
        evidence_type=record_type,
        occurred_at=observed_at,
        source_updated_at=observed_at,
        title=name[:500],
        summary=summary[:5000],
        value_json={"provider_object_id": object_id, "version": version},
        confidence=0.84,
        quality_status="usable",
        citation_label=connection.provider + ":" + object_id,
        source_excerpt=summary[:1600],
        metadata_json=metadata,
    )
    db.add(evidence)
    return True
