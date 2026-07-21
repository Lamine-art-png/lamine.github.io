#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$SCRIPT_DIR"

for asset in \
  "$APP_ROOT/shared/supported-locales.json" \
  "$APP_ROOT/shared/chatgpt-language-targets.json" \
  "$APP_ROOT/shared/ui-catalog.en.json" \
  "$APP_ROOT/shared/ui-commercial-boundary.en.json"
do
  if [ ! -s "$asset" ]; then
    echo "fatal: required runtime asset is missing: $asset" >&2
    exit 78
  fi
done

python - <<'PY'
from app.main import app

if app.title != "AGRO-AI API":
    raise RuntimeError("FastAPI application import preflight failed")
PY

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
