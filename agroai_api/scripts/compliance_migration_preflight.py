"""Read-only compliance schema preflight for production database migrations."""
from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import create_engine, inspect, text

from app.core.config import settings

COMPLIANCE_TABLES = {
    "compliance_jurisdictions",
    "compliance_parcels",
    "compliance_wells",
    "compliance_rule_packs",
    "compliance_export_metadata",
}


def _table_exists(tables: set[str], table_name: str) -> bool:
    return table_name in tables


def _columns(inspector, table_name: str, tables: set[str]) -> dict[str, dict[str, Any]]:
    if table_name not in tables:
        return {}
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _current_revision(connection, tables: set[str]) -> str | list[str] | None:
    if "alembic_version" not in tables:
        return None
    rows = connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars().all()
    if not rows:
        return None
    if len(rows) == 1:
        return str(rows[0])
    return [str(row) for row in rows]


def _workflow_type_database_types(inspector, tables: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for table_name in sorted(tables):
        columns = _columns(inspector, table_name, tables)
        if "workflow_type" in columns:
            result[table_name] = str(columns["workflow_type"]["type"])
    return result


def _classify_schema(tables: set[str], parcel_columns: dict[str, dict[str, Any]], current_revision: str | list[str] | None) -> str:
    compliance_tables = {table for table in tables if table.startswith("compliance_")}
    if not compliance_tables:
        return "A_clean_baseline_no_compliance_tables"

    has_core_002 = {
        "compliance_jurisdictions",
        "compliance_parcels",
        "compliance_wells",
        "compliance_rule_packs",
        "compliance_readiness_snapshots",
    }.issubset(compliance_tables)
    has_export_metadata = "compliance_export_metadata" in compliance_tables
    has_parcel_identifier = "parcel_identifier" in parcel_columns

    if has_core_002 and not has_export_metadata and not has_parcel_identifier:
        return "B_migration_002_schema"
    if has_core_002 and has_export_metadata and has_parcel_identifier:
        return "C_migration_003_schema"
    if current_revision == "002_california_compliance_pack" and has_core_002 and not has_export_metadata:
        return "B_migration_002_schema"
    return "D_ambiguous_or_partial_schema_manual_review"


def collect_report(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        parcel_columns = _columns(inspector, "compliance_parcels", tables)
        current_revision = _current_revision(connection, tables)
        compliance_tables = sorted(table for table in tables if table.startswith("compliance_"))
        report = {
            "read_only": True,
            "current_alembic_revision": current_revision,
            "compliance_tables_exist": bool(compliance_tables),
            "compliance_tables": compliance_tables,
            "tables": {
                table_name: _table_exists(tables, table_name)
                for table_name in sorted(COMPLIANCE_TABLES)
            },
            "workflow_type_database_types": _workflow_type_database_types(inspector, tables),
            "parcel_identifier_exists": "parcel_identifier" in parcel_columns,
        }
        report["schema_classification"] = _classify_schema(tables, parcel_columns, current_revision)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only compliance schema preflight")
    parser.add_argument("--database-url", default=settings.DATABASE_URL, help="Database URL to inspect")
    args = parser.parse_args()
    print(json.dumps(collect_report(args.database_url), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
