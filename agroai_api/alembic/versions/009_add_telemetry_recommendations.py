"""Add telemetry and recommendation tables for starter field context.

Revision ID: 009_add_telemetry_recommendations
Revises: 008_saas_portal_v2_1_security
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa


revision = "009_add_telemetry_recommendations"
down_revision = "008_saas_portal_v2_1_security"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _column_names(table_name: str) -> set[str]:
    if not _table_exists(table_name):
        return set()
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _columns_by_name(table_name: str) -> dict[str, dict]:
    if not _table_exists(table_name):
        return {}
    return {column["name"]: column for column in _inspector().get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def _type_family(column_type: sa.types.TypeEngine) -> str:
    class_name = column_type.__class__.__name__.lower()
    if class_name in {"json", "jsonb"} or isinstance(column_type, sa.JSON):
        return "json"
    if isinstance(column_type, (sa.String, sa.Text, sa.Unicode, sa.UnicodeText)):
        return "string"
    if isinstance(column_type, sa.Integer):
        return "integer"
    if isinstance(column_type, (sa.Float, sa.Numeric)):
        return "real_number"
    if isinstance(column_type, sa.DateTime):
        return "datetime"
    if isinstance(column_type, sa.Date):
        return "date"
    if isinstance(column_type, sa.Time):
        return "time"
    return class_name


def _is_compatible_type(actual: sa.types.TypeEngine, expected: sa.types.TypeEngine) -> bool:
    expected_family = _type_family(expected)
    actual_family = _type_family(actual)
    if actual_family == expected_family:
        return True
    # SQLite-backed legacy fixtures may represent DateTime/JSON as text.
    # PostgreSQL and production databases must still use canonical families.
    if op.get_bind().dialect.name == "sqlite":
        if expected_family == "datetime" and actual_family == "string":
            return True
        if expected_family == "json" and actual_family == "string":
            return True
    return False


def _assert_existing_column_compatible(table_name: str, existing: dict, expected: sa.Column) -> None:
    if not _is_compatible_type(existing["type"], expected.type):
        raise RuntimeError(
            f"Existing {table_name}.{expected.name} column is incompatible with migration "
            f"009: found {existing['type']!s}, expected {expected.type!s}."
        )
    if not expected.nullable and existing.get("nullable") is True:
        raise RuntimeError(
            f"Existing {table_name}.{expected.name} column is nullable, but migration 009 "
            "requires a non-null column. Repair the schema before upgrading."
        )


def _primary_key_columns(table_name: str) -> set[str]:
    if not _table_exists(table_name):
        return set()
    return set((_inspector().get_pk_constraint(table_name) or {}).get("constrained_columns") or [])


def _foreign_key_pairs(table_name: str) -> set[tuple[str, str, str]]:
    if not _table_exists(table_name):
        return set()
    pairs: set[tuple[str, str, str]] = set()
    for foreign_key in _inspector().get_foreign_keys(table_name):
        local_columns = foreign_key.get("constrained_columns") or []
        remote_columns = foreign_key.get("referred_columns") or []
        remote_table = foreign_key.get("referred_table")
        if not remote_table:
            continue
        for local, remote in zip(local_columns, remote_columns):
            pairs.add((str(local), str(remote_table), str(remote)))
    return pairs


def _assert_existing_table_constraints(table_name: str) -> None:
    # SQLite legacy fixtures and customer-side evaluation databases may not
    # preserve/enforce FK metadata consistently. Production PostgreSQL adoption
    # must match the ORM's PK and tenant/block FK contract exactly.
    if op.get_bind().dialect.name == "sqlite":
        return

    primary_key = _primary_key_columns(table_name)
    if primary_key != {"id"}:
        raise RuntimeError(
            f"Existing {table_name} primary key is incompatible with migration 009: "
            f"found {sorted(primary_key)!r}, expected ['id']."
        )

    foreign_keys = _foreign_key_pairs(table_name)
    required_foreign_keys = {
        ("tenant_id", "tenants", "id"),
        ("block_id", "blocks", "id"),
    }
    missing = required_foreign_keys - foreign_keys
    if missing:
        raise RuntimeError(
            f"Existing {table_name} foreign keys are incompatible with migration 009: "
            f"missing {sorted(missing)!r}. Repair the schema before upgrading."
        )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _table_exists(table_name) or _index_exists(table_name, index_name):
        return
    if set(columns).issubset(_column_names(table_name)):
        op.create_index(index_name, table_name, columns)


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _table_exists(table_name):
        return
    existing = _columns_by_name(table_name)
    if column.name in existing:
        _assert_existing_column_compatible(table_name, existing[column.name], column)
        return
    if not column.nullable:
        raise RuntimeError(
            f"Existing {table_name} table is missing required non-null column {column.name}. "
            "Migration 009 can adopt missing nullable columns, but required columns must be "
            "repaired explicitly before upgrading."
        )
    op.add_column(table_name, column)


def _ensure_existing_columns(table_name: str, columns: list[sa.Column]) -> None:
    for column in columns:
        _add_column_if_missing(table_name, column)


def _telemetry_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("block_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("meta_data", sa.JSON(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=True),
    ]


def _recommendation_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("block_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("body_hash", sa.String(), nullable=True),
        sa.Column("feature_hash", sa.String(), nullable=True),
        sa.Column("when", sa.DateTime(), nullable=False),
        sa.Column("duration_min", sa.Float(), nullable=False),
        sa.Column("volume_m3", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("horizon_hours", sa.Float(), nullable=False),
        sa.Column("explanations", sa.JSON(), nullable=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("meta_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("decision_run_id", sa.String(), nullable=True),
    ]


def upgrade() -> None:
    if not _table_exists("telemetry"):
        op.create_table(
            "telemetry",
            *_telemetry_columns(),
            sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        _ensure_existing_columns("telemetry", _telemetry_columns())
        _assert_existing_table_constraints("telemetry")

    _create_index_if_missing("ix_telemetry_id", "telemetry", ["id"])
    _create_index_if_missing("ix_telemetry_tenant_id", "telemetry", ["tenant_id"])
    _create_index_if_missing("ix_telemetry_block_id", "telemetry", ["block_id"])
    _create_index_if_missing("ix_telemetry_type", "telemetry", ["type"])
    _create_index_if_missing("ix_telemetry_timestamp", "telemetry", ["timestamp"])
    _create_index_if_missing("ix_telemetry_ingested_at", "telemetry", ["ingested_at"])
    _create_index_if_missing("ix_telemetry_lookup", "telemetry", ["block_id", "type", "timestamp"])

    if not _table_exists("recommendations"):
        op.create_table(
            "recommendations",
            *_recommendation_columns(),
            sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        _ensure_existing_columns("recommendations", _recommendation_columns())
        _assert_existing_table_constraints("recommendations")

    _create_index_if_missing("ix_recommendations_id", "recommendations", ["id"])
    _create_index_if_missing("ix_recommendations_tenant_id", "recommendations", ["tenant_id"])
    _create_index_if_missing("ix_recommendations_block_id", "recommendations", ["block_id"])
    _create_index_if_missing("ix_recommendations_idempotency_key", "recommendations", ["idempotency_key"])
    _create_index_if_missing("ix_recommendations_body_hash", "recommendations", ["body_hash"])
    _create_index_if_missing("ix_recommendations_feature_hash", "recommendations", ["feature_hash"])
    _create_index_if_missing("ix_recommendations_created_at", "recommendations", ["created_at"])
    _create_index_if_missing("ix_recommendations_expires_at", "recommendations", ["expires_at"])
    _create_index_if_missing("ix_recommendations_decision_run_id", "recommendations", ["decision_run_id"])
    _create_index_if_missing("ix_rec_idem", "recommendations", ["tenant_id", "idempotency_key", "body_hash"])
    _create_index_if_missing("ix_rec_cache", "recommendations", ["block_id", "feature_hash", "expires_at"])
    _create_index_if_missing("ix_rec_block_date", "recommendations", ["block_id", "created_at"])


def downgrade() -> None:
    # Adoption-safe, intentionally non-destructive: these tables may predate
    # Alembic ownership and may contain customer telemetry/recommendation data.
    # Removing them requires a separate data-reviewed destructive migration.
    return
