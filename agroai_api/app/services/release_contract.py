from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.redis_task_queue import queue_configured


@lru_cache(maxsize=1)
def repository_alembic_heads() -> tuple[str, ...]:
    root = Path(__file__).resolve().parents[2]
    config_path = root / "alembic.ini"
    config = Config(str(config_path))
    config.set_main_option("script_location", str(root / "alembic"))
    heads = tuple(sorted(ScriptDirectory.from_config(config).get_heads()))
    if not heads:
        raise RuntimeError("repository Alembic head is unavailable")
    return heads


def database_alembic_heads(db: Session) -> tuple[str, ...]:
    rows = db.execute(text("SELECT version_num FROM alembic_version")).all()
    return tuple(sorted(str(row[0]) for row in rows if row and row[0]))


def runtime_build_sha() -> str:
    for name in ("RENDER_GIT_COMMIT", "GIT_SHA", "COMMIT_SHA", "SOURCE_VERSION"):
        value = os.getenv(name, "").strip()
        if value and value.lower() != "dev":
            return value
    return ""


def evaluate_release_contract(db: Session) -> dict:
    repository_heads = repository_alembic_heads()
    database_heads = database_alembic_heads(db)
    build_sha = runtime_build_sha()
    queue_ready = queue_configured()
    schema_current = database_heads == repository_heads
    return {
        "status": "ok" if build_sha and schema_current and queue_ready else "blocked",
        "build_sha": build_sha or None,
        "schema_current": schema_current,
        "database_heads": list(database_heads),
        "repository_heads": list(repository_heads),
        "queue_configured": queue_ready,
    }
