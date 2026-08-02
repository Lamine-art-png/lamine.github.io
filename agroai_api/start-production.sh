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

# The founder approved the live Developer and Scale catalog and migration 028
# activated it in the production database. Lock that launch decision into the
# release process so stale or incorrectly saved Render booleans cannot silently
# return live pricing, Checkout, overage export, or quota enforcement to 404 or
# disabled behavior. Non-production and non-live Stripe environments retain
# their explicit feature flags.
case "${APP_ENV:-development}" in
  production|prod)
    if [ "${PLATFORM_API_STRIPE_MODE:-test}" = "live" ] \
      && [ "${PLATFORM_API_PLAN_CATALOG_VERSION:-2026-07-provisional}" = "2026-07-provisional" ] \
      && [ "${PLATFORM_API_OPERATION_COST_CATALOG_VERSION:-2026-07-provisional}" = "2026-07-provisional" ]; then
      export PLATFORM_API_BILLING_ENABLED=true
      export PLATFORM_API_STRIPE_CHECKOUT_ENABLED=true
      export PLATFORM_API_STRIPE_METER_EXPORT_ENABLED=true
      export PLATFORM_API_PRICING_ENABLED=true
      export PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED=true
      echo "Platform API live billing launch contract: enabled"
    fi
    ;;
esac

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

# Refuse to accept customer traffic when live Platform API billing points to
# missing, test-mode, inactive, or mispriced Stripe resources. This is a
# read-only check; it never creates or changes Stripe objects.
python scripts/verify_platform_billing_config.py

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
