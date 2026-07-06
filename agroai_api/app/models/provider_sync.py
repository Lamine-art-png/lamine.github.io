from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, JSON, String, Text

from app.db.base import Base


class ConnectorSyncCursor(Base):
    __tablename__ = "connector_sync_cursors"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    connection_id = Column(String, nullable=False, unique=True, index=True)
    provider = Column(String, nullable=False, index=True)
    cursor = Column(Text, nullable=True)
    cursor_json = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, default="ready", index=True)
    last_attempt_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
