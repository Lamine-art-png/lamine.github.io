#!/bin/sh
set -eu

python - <<'PY'
from pathlib import Path

import sqlalchemy as sa

from app.core.config import settings
from app.services.release_migration import acquire_migration_lock, release_migration_lock, run_alembic_upgrade

engine = sa.create_engine(settings.DATABASE_URL, pool_pre_ping=True, poolclass=sa.pool.NullPool)
if engine.dialect.name != "postgresql":
    raise RuntimeError("Production startup requires PostgreSQL")

with engine.connect() as connection:
    acquire_migration_lock(connection, 180)
    try:
        run_alembic_upgrade(settings.DATABASE_URL, Path.cwd())
    finally:
        release_migration_lock(connection)
PY

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
