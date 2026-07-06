from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import settings


APP_ROOT = Path(__file__).resolve().parents[2] / "app"
API_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DDL_TOKENS = (
    "CREATE TABLE",
    "ALTER TABLE",
    "Base.metadata.create_all",
    ".metadata.create_all",
    "__table__.create",
)


def test_app_runtime_code_does_not_mutate_database_schema():
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text()
        for token in RUNTIME_DDL_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(APP_ROOT)} contains {token}")
    assert offenders == []


def test_alembic_head_creates_runtime_required_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime-schema.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "user_preferences",
        "connector_connections",
        "data_sources",
        "ingestion_jobs",
        "evidence_records",
        "intelligence_runs",
        "generated_artifacts",
        "chat_conversations",
        "chat_messages",
        "oauth_state_nonces",
        "connector_credentials",
        "task_outbox",
        "connector_sync_cursors",
    }.issubset(tables)
    assert {"content_sha256", "object_size_bytes"}.issubset({item["name"] for item in inspector.get_columns("data_sources")})
    assert {"idempotency_key", "attempt_count", "lease_expires_at", "worker_id"}.issubset({item["name"] for item in inspector.get_columns("ingestion_jobs")})
    assert {"provenance_json", "freshness_json"}.issubset({item["name"] for item in inspector.get_columns("intelligence_runs")})
    assert {"tenant_id", "connection_id", "provider", "cursor_json", "status"}.issubset({item["name"] for item in inspector.get_columns("connector_sync_cursors")})
