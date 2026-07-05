from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from app.db.schema_contract import HEAD_SCHEMA_REQUIREMENTS, schema_contract_gaps


API_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_INDEX_CONTRACTS: dict[str, list[set[str]]] = {
    "data_sources": [{"tenant_id", "connector_connection_id", "content_sha256"}],
    "ingestion_jobs": [
        {"tenant_id", "idempotency_key"},
        {"status", "next_attempt_at", "lease_expires_at"},
    ],
    "task_outbox": [{"status", "next_attempt_at", "created_at"}],
    "oauth_state_nonces": [{"nonce_hash"}],
    "connector_credentials": [{"connection_id"}],
}

DUPLICATE_HAZARDS: list[tuple[str, tuple[str, ...]]] = [
    ("data_sources", ("tenant_id", "connector_connection_id", "content_sha256")),
    ("ingestion_jobs", ("tenant_id", "idempotency_key")),
    ("task_outbox", ("job_id",)),
    ("oauth_state_nonces", ("nonce_hash",)),
    ("connector_credentials", ("connection_id",)),
]

ORPHAN_CHECKS: list[tuple[str, str, str, str]] = [
    ("task_outbox", "job_id", "ingestion_jobs", "id"),
    ("connector_credentials", "connection_id", "connector_connections", "id"),
    ("oauth_state_nonces", "connection_id", "connector_connections", "id"),
    ("data_sources", "connector_connection_id", "connector_connections", "id"),
    ("evidence_records", "data_source_id", "data_sources", "id"),
]


def _heads() -> list[str]:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    return sorted(ScriptDirectory.from_config(cfg).get_heads())


def _fingerprint(database_url: str) -> dict[str, Any]:
    url = make_url(database_url)
    stable = f"{url.drivername}|{url.host or ''}|{url.port or ''}|{url.database or ''}"
    return {
        "driver": url.drivername,
        "host_hash": hashlib.sha256((url.host or "").encode("utf-8")).hexdigest()[:12] if url.host else None,
        "database_hash": hashlib.sha256((url.database or "").encode("utf-8")).hexdigest()[:12] if url.database else None,
        "identity_fingerprint": hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16],
        "credentials_exposed": False,
    }


def _index_contract_gaps(inspector: sa.Inspector, tables: set[str]) -> dict[str, list[list[str]]]:
    gaps: dict[str, list[list[str]]] = {}
    for table, expected_sets in REQUIRED_INDEX_CONTRACTS.items():
        if table not in tables:
            continue
        actual: list[set[str]] = []
        for item in inspector.get_indexes(table):
            actual.append(set(item.get("column_names") or []))
        for item in inspector.get_unique_constraints(table):
            actual.append(set(item.get("column_names") or []))
        missing = [sorted(expected) for expected in expected_sets if expected not in actual]
        if missing:
            gaps[table] = missing
    return gaps


def _duplicate_hazards(connection: sa.Connection, inspector: sa.Inspector, tables: set[str]) -> list[dict[str, Any]]:
    hazards: list[dict[str, Any]] = []
    for table, columns in DUPLICATE_HAZARDS:
        if table not in tables:
            continue
        actual = {column["name"] for column in inspector.get_columns(table)}
        if not set(columns).issubset(actual):
            continue
        quoted_table = inspector.dialect.identifier_preparer.quote(table)
        quoted_columns = [inspector.dialect.identifier_preparer.quote(column) for column in columns]
        not_null = " AND ".join(f"{column} IS NOT NULL" for column in quoted_columns)
        query = sa.text(
            f"SELECT COUNT(*) FROM ("
            f"SELECT {', '.join(quoted_columns)}, COUNT(*) AS n "
            f"FROM {quoted_table} WHERE {not_null} "
            f"GROUP BY {', '.join(quoted_columns)} HAVING COUNT(*) > 1"
            f") AS duplicate_groups"
        )
        count = int(connection.execute(query).scalar_one())
        if count:
            hazards.append({"table": table, "columns": list(columns), "duplicate_groups": count})
    return hazards


def _orphan_hazards(connection: sa.Connection, inspector: sa.Inspector, tables: set[str]) -> list[dict[str, Any]]:
    hazards: list[dict[str, Any]] = []
    quote = inspector.dialect.identifier_preparer.quote
    for child, child_column, parent, parent_column in ORPHAN_CHECKS:
        if child not in tables or parent not in tables:
            continue
        child_columns = {column["name"] for column in inspector.get_columns(child)}
        parent_columns = {column["name"] for column in inspector.get_columns(parent)}
        if child_column not in child_columns or parent_column not in parent_columns:
            continue
        query = sa.text(
            f"SELECT COUNT(*) FROM {quote(child)} c "
            f"LEFT JOIN {quote(parent)} p ON c.{quote(child_column)} = p.{quote(parent_column)} "
            f"WHERE c.{quote(child_column)} IS NOT NULL AND p.{quote(parent_column)} IS NULL"
        )
        count = int(connection.execute(query).scalar_one())
        if count:
            hazards.append({
                "child_table": child,
                "child_column": child_column,
                "parent_table": parent,
                "orphan_rows": count,
            })
    return hazards


def inspect_database(database_url: str) -> dict[str, Any]:
    engine = sa.create_engine(database_url, pool_pre_ping=True)
    expected_heads = _heads()
    identity = _fingerprint(database_url)
    with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            server_version = str(connection.execute(sa.text("SHOW server_version")).scalar_one())
        else:
            server_version = str(getattr(connection.dialect, "server_version_info", None))

        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        managed_present = sorted(tables.intersection(HEAD_SCHEMA_REQUIREMENTS))
        gaps = schema_contract_gaps(connection)

        versions: list[str] = []
        if "alembic_version" in tables:
            versions = sorted(str(row[0]) for row in connection.execute(sa.text("SELECT version_num FROM alembic_version")))

        index_gaps = _index_contract_gaps(inspector, tables)
        duplicates = _duplicate_hazards(connection, inspector, tables)
        orphans = _orphan_hazards(connection, inspector, tables)

        if not managed_present and not versions:
            classification = "A_fresh_clean"
        elif versions:
            classification = "C_current_head" if versions == expected_heads and not gaps else "B_versioned_requires_upgrade_or_repair"
        elif managed_present and not gaps:
            classification = "D_complete_unversioned_adoptable"
        elif managed_present:
            classification = "E_partial_unsafe_managed_schema"
        else:
            classification = "F_unknown_manual_review"

        safe = classification in {
            "A_fresh_clean",
            "B_versioned_requires_upgrade_or_repair",
            "C_current_head",
            "D_complete_unversioned_adoptable",
        } and not duplicates and not orphans

        result = {
            "identity": identity,
            "dialect": connection.dialect.name,
            "server_version": server_version,
            "classification": classification,
            "safe_for_controlled_migration": safe,
            "current_alembic_revisions": versions,
            "repository_alembic_heads": expected_heads,
            "managed_tables_present": managed_present,
            "schema_contract_gaps": gaps,
            "index_contract_gaps": index_gaps,
            "duplicate_hazards": duplicates,
            "orphan_hazards": orphans,
            "table_count": len(tables),
            "read_only": True,
        }
        connection.rollback()
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only AGRO-AI deployment database migration preflight")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--allow-unsafe", action="store_true", help="Return zero even when the preflight classifies the database unsafe")
    parser.add_argument("--output", default="", help="Optional JSON output path")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    report = inspect_database(args.database_url)
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    if not report["safe_for_controlled_migration"] and not args.allow_unsafe:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
