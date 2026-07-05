"""Database package initialization for persisted schema contracts."""

from . import schema_contract as _schema_contract

# Migrations added after the original hardening contract extend the same
# fail-closed adoption proof. Keeping this extension at package initialization
# avoids a second competing contract implementation.
_schema_contract.HEAD_SCHEMA_REQUIREMENTS.setdefault(
    "connector_sync_cursors",
    {"id", "tenant_id", "connection_id", "provider", "cursor_json", "status", "updated_at"},
)
