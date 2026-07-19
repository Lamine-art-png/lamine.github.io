"""Production database rollout tooling for Field Intelligence.

Subcommands (all operate on ``DATABASE_URL`` unless ``--database-url`` is
given; every check prints a JSON report and exits nonzero on failure):

    preflight        — safe pre-migration validation (no writes)
    upgrade          — advisory-locked upgrade to the repository head
    verify           — full post-migration integrity validation
    downgrade        — advisory-locked rollback to 022_account_access_appeals
    verify-rollback  — prove only Field Intelligence schema was removed

The rollback floor is ``022_account_access_appeals``: rolling back removes
Field Intelligence schema only and must preserve every Platform API,
verification, suspension and appeal table and column.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

ROLLBACK_FLOOR = "022_account_access_appeals"

FIELD_TABLES = {
    "field_capture_sessions",
    "field_observations",
    "field_observation_assets",
    "field_observation_processing_runs",
    "field_observation_audit_events",
    "field_storage_reservations",
    "field_runtime_flags",
    "field_worker_heartbeats",
}
PRESERVED_TABLES = {
    "organization_verification_profiles",
    "security_audit_events",
    "account_access_appeals",
    "api_projects",
    "platform_api_keys",
    "platform_webhook_endpoints",
    "platform_webhook_outbox",
    "platform_webhook_audit_events",
    "users",
    "organizations",
    "workspaces",
}
PRESERVED_USER_COLUMNS = {
    "account_status", "failed_login_attempts", "locked_until",
    "access_restriction_reason", "access_restricted_at",
}
PRESERVED_ORG_COLUMNS = {"verification_status", "verification_score", "verified_at"}

# table -> (required columns, required FK target tables, required unique constraints)
FIELD_TABLE_CONTRACT: dict[str, tuple[set[str], set[str], set[str]]] = {
    "field_capture_sessions": (
        {"id", "tenant_id", "workspace_id", "user_id", "client_capture_id", "idempotency_key",
         "payload_fingerprint", "status", "asset_manifest_json", "metadata_json", "observation_id",
         "created_at", "updated_at"},
        {"organizations", "workspaces", "users"},
        {"uq_field_capture_idempotency", "uq_field_capture_client_id"},
    ),
    "field_observations": (
        {"id", "tenant_id", "workspace_id", "capture_session_id", "status", "structured_json",
         "confidence", "uncertain_fields_json", "correlation_json", "provenance_json",
         "task_ids_json", "evidence_ids_json", "audit_json", "observed_at", "created_at"},
        {"organizations", "workspaces", "users", "field_capture_sessions"},
        {"uq_field_obs_capture_session"},
    ),
    "field_observation_assets": (
        {"id", "tenant_id", "capture_session_id", "observation_id", "client_asset_id", "kind",
         "storage_backend", "object_ref", "content_sha256", "size_bytes", "status",
         "delete_attempts", "created_at"},
        {"organizations", "workspaces", "field_capture_sessions", "field_observations"},
        {"uq_field_asset_identity"},
    ),
    "field_observation_processing_runs": (
        {"id", "tenant_id", "observation_id", "capture_session_id", "stage", "status",
         "attempt_count", "input_json", "output_json", "created_at"},
        {"organizations", "workspaces", "field_observations"},
        set(),
    ),
    "field_observation_audit_events": (
        {"id", "tenant_id", "observation_id", "capture_session_id", "asset_id", "action",
         "actor_type", "details_json", "created_at"},
        {"organizations"},
        set(),
    ),
    "field_storage_reservations": (
        {"id", "tenant_id", "capture_session_id", "size_bytes", "created_at", "expires_at"},
        {"organizations"},
        set(),
    ),
    "field_runtime_flags": ({"key", "value_json", "updated_at"}, set(), set()),
    "field_worker_heartbeats": (
        {"worker_id", "git_sha", "started_at", "last_heartbeat_at"}, set(), set(),
    ),
}

REQUIRED_INDEXES = {
    "field_observation_assets": {"ix_field_asset_checksum", "ix_field_asset_status"},
    "field_observations": {"ix_field_obs_tenant_ws_time", "ix_field_obs_status"},
    "field_capture_sessions": {"ix_field_capture_status"},
    "field_storage_reservations": {"ix_field_storage_res_tenant"},
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    os.environ["DATABASE_URL"] = database_url
    return config


def _repository_head() -> str:
    config = _alembic_config(os.environ.get("DATABASE_URL", "sqlite://"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise SystemExit(f"FAIL: repository must have exactly one Alembic head, found {heads}")
    return heads[0]


def _database_revisions(engine: sa.Engine) -> list[str]:
    inspector = sa.inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        return []
    with engine.connect() as connection:
        return sorted(
            str(row[0]) for row in connection.execute(sa.text("SELECT version_num FROM alembic_version"))
        )


def _fail(report: dict, message: str) -> None:
    report.setdefault("failures", []).append(message)


def _finish(report: dict) -> int:
    report["ok"] = not report.get("failures")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


def cmd_preflight(engine: sa.Engine) -> int:
    report: dict = {"command": "preflight"}
    head = _repository_head()
    report["repository_head"] = head
    revisions = _database_revisions(engine)
    report["database_revisions"] = revisions
    if len(revisions) > 1:
        _fail(report, f"database reports multiple revisions: {revisions}")
    current = revisions[0] if revisions else None
    allowed = {ROLLBACK_FLOOR, "023_field_intelligence", head, None}
    if current not in allowed:
        _fail(report, f"database revision {current!r} is not a supported upgrade baseline {sorted(str(a) for a in allowed)}")
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    if current is not None:
        missing = PRESERVED_TABLES - tables
        if missing:
            _fail(report, f"baseline is missing required current-main tables: {sorted(missing)}")
    report["current_revision"] = current
    report["upgrade_needed"] = current != head
    return _finish(report)


def _with_lock(engine: sa.Engine, fn) -> None:
    if engine.dialect.name == "postgresql":
        from app.services.release_migration import acquire_migration_lock, release_migration_lock

        with engine.connect() as connection:
            acquire_migration_lock(connection)
            try:
                fn()
            finally:
                release_migration_lock(connection)
    else:
        fn()


def cmd_upgrade(engine: sa.Engine, database_url: str) -> int:
    report: dict = {"command": "upgrade", "target": _repository_head()}
    config = _alembic_config(database_url)
    _with_lock(engine, lambda: command.upgrade(config, "head"))
    report["database_revisions"] = _database_revisions(engine)
    if report["database_revisions"] != [report["target"]]:
        _fail(report, "database did not reach the repository head")
    return _finish(report)


def cmd_verify(engine: sa.Engine) -> int:
    report: dict = {"command": "verify", "tables": {}}
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    revisions = _database_revisions(engine)
    if revisions != [_repository_head()]:
        _fail(report, f"database revision {revisions} != repository head")
    for table, (columns, fk_targets, uniques) in FIELD_TABLE_CONTRACT.items():
        entry: dict = {}
        if table not in tables:
            _fail(report, f"missing table {table}")
            continue
        have_columns = {c["name"] for c in inspector.get_columns(table)}
        missing_columns = columns - have_columns
        if missing_columns:
            _fail(report, f"{table}: missing columns {sorted(missing_columns)}")
        have_fk_targets = {fk["referred_table"] for fk in inspector.get_foreign_keys(table)}
        missing_fks = fk_targets - have_fk_targets
        if missing_fks:
            _fail(report, f"{table}: missing foreign keys to {sorted(missing_fks)}")
        have_uniques = {u["name"] for u in inspector.get_unique_constraints(table)}
        have_unique_indexes = {i["name"] for i in inspector.get_indexes(table) if i.get("unique")}
        missing_uniques = uniques - have_uniques - have_unique_indexes
        if missing_uniques:
            _fail(report, f"{table}: missing unique constraints {sorted(missing_uniques)}")
        have_indexes = {i["name"] for i in inspector.get_indexes(table)}
        missing_indexes = REQUIRED_INDEXES.get(table, set()) - have_indexes
        if missing_indexes:
            _fail(report, f"{table}: missing indexes {sorted(missing_indexes)}")
        entry["columns"] = len(have_columns)
        entry["foreign_key_targets"] = sorted(have_fk_targets)
        report["tables"][table] = entry
    # Status-domain sanity on live data (cheap enum/status contract check).
    with engine.connect() as connection:
        if "field_observation_assets" in tables:
            bad = connection.execute(sa.text(
                "SELECT COUNT(*) FROM field_observation_assets "
                "WHERE status NOT IN ('stored','pending_deletion','deleted')"
            )).scalar()
            if bad:
                _fail(report, f"field_observation_assets: {bad} rows outside the status contract")
        if "field_observations" in tables:
            orphaned = connection.execute(sa.text(
                "SELECT COUNT(*) FROM field_observations o "
                "LEFT JOIN organizations org ON org.id = o.tenant_id WHERE org.id IS NULL"
            )).scalar()
            if orphaned:
                _fail(report, f"field_observations: {orphaned} rows with broken tenant lineage")
    return _finish(report)


def cmd_downgrade(engine: sa.Engine, database_url: str) -> int:
    report: dict = {"command": "downgrade", "target": ROLLBACK_FLOOR}
    config = _alembic_config(database_url)
    _with_lock(engine, lambda: command.downgrade(config, ROLLBACK_FLOOR))
    report["database_revisions"] = _database_revisions(engine)
    if report["database_revisions"] != [ROLLBACK_FLOOR]:
        _fail(report, "database did not reach the rollback floor")
    return _finish(report)


def cmd_verify_rollback(engine: sa.Engine) -> int:
    report: dict = {"command": "verify-rollback"}
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    leftover = FIELD_TABLES & tables
    if leftover:
        _fail(report, f"rollback left Field Intelligence tables behind: {sorted(leftover)}")
    missing = PRESERVED_TABLES - tables
    if missing:
        _fail(report, f"rollback removed protected current-main tables: {sorted(missing)}")
    if "users" in tables:
        user_columns = {c["name"] for c in inspector.get_columns("users")}
        lost = PRESERVED_USER_COLUMNS - user_columns
        if lost:
            _fail(report, f"rollback removed protected user columns: {sorted(lost)}")
    if "organizations" in tables:
        org_columns = {c["name"] for c in inspector.get_columns("organizations")}
        lost = PRESERVED_ORG_COLUMNS - org_columns
        if lost:
            _fail(report, f"rollback removed protected organization columns: {sorted(lost)}")
    report["database_revisions"] = _database_revisions(engine)
    return _finish(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Field Intelligence production migration tooling")
    parser.add_argument("command", choices=["preflight", "upgrade", "verify", "downgrade", "verify-rollback"])
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    args = parser.parse_args()
    if not args.database_url:
        print(json.dumps({"ok": False, "failures": ["DATABASE_URL is required"]}))
        return 1
    engine = sa.create_engine(args.database_url)
    try:
        if args.command == "preflight":
            return cmd_preflight(engine)
        if args.command == "upgrade":
            return cmd_upgrade(engine, args.database_url)
        if args.command == "verify":
            return cmd_verify(engine)
        if args.command == "downgrade":
            return cmd_downgrade(engine, args.database_url)
        return cmd_verify_rollback(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
