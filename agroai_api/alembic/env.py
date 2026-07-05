"""Alembic environment configuration."""
from logging.config import fileConfig
import os
import sys

from alembic import context
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy import engine_from_config
from sqlalchemy import pool

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.base import Base
from app.core.config import settings
from app.db.schema_contract import has_any_managed_schema, schema_contract_gaps, schema_matches_head_contract
from app import models  # noqa
# Register hardening models that intentionally live outside the legacy package export list.
from app.models import connector_security as _connector_security  # noqa: F401,E402
from app.models import hardened_records as _hardened_records  # noqa: F401,E402
from app.models import task_outbox as _task_outbox  # noqa: F401,E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

if settings.DATABASE_URL:
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def _alembic_heads() -> list[str]:
    return list(ScriptDirectory.from_config(config).get_heads())


def _table_names(connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _current_alembic_versions(connection) -> set[str]:
    if "alembic_version" not in _table_names(connection):
        return set()
    rows = connection.execute(sa.text("SELECT version_num FROM alembic_version")).fetchall()
    return {row[0] for row in rows}


def _stamp_connection_to_heads(connection, heads: list[str]) -> None:
    connection.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(255) NOT NULL)"))
    connection.execute(sa.text("DELETE FROM alembic_version"))
    for head in heads:
        connection.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES (:head)"), {"head": head})
    connection.commit()


def _adopt_dirty_render_schema(connection) -> None:
    """Adopt only an unversioned schema that proves complete current-head shape.

    Historical runtime DDL could leave tables present but missing columns. Such a
    partial schema is never stamped forward. It fails closed with explicit gaps
    so an operator can repair or restore it deliberately.
    """
    if connection.dialect.name == "sqlite":
        return
    heads = set(_alembic_heads())
    if not heads or _current_alembic_versions(connection):
        return
    if schema_matches_head_contract(connection):
        print(f"Alembic adopting unversioned current-head-shaped schema; heads={sorted(heads)}")
        _stamp_connection_to_heads(connection, sorted(heads))
        return
    if has_any_managed_schema(connection):
        gaps = schema_contract_gaps(connection)
        preview = "; ".join(f"{table}: {','.join(columns)}" for table, columns in list(gaps.items())[:12])
        raise RuntimeError(
            "Refusing to stamp an unversioned partial AGRO-AI schema. "
            f"Missing required table/column contract: {preview}"
        )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _adopt_dirty_render_schema(connection)
        if connection.in_transaction():
            connection.rollback()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
