from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.operational_records import ConnectorConnection
from app.models.provider_sync import ConnectorSyncCursor


def get_sync_cursor(db: Session, *, connection: ConnectorConnection) -> ConnectorSyncCursor:
    row = db.query(ConnectorSyncCursor).filter(
        ConnectorSyncCursor.tenant_id == connection.tenant_id,
        ConnectorSyncCursor.connection_id == connection.id,
    ).first()
    if row is None:
        row = ConnectorSyncCursor(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            provider=connection.provider,
            cursor_json={},
            status="ready",
        )
        db.add(row)
        db.flush()
    return row
