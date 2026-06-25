"""Alembic environment configuration."""
from logging.config import fileConfig
import os
import sys

from alembic import context
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy import engine_from_config
from sqlalchemy import pool

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.base import Base
from app.core.config import settings
# Import all models to ensure they're registered
from app import models  # noqa

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# Override sqlalchemy.url from settings if DATABASE_URL is set
if settings.DATABASE_URL:
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


# Tables from later AGRO-AI portal/assurance migrations. If these already
# exist in Render while alembic_version is behind, the DB is not clean: it was
# created by earlier startup/schema mutation or partially applied migrations.
# In that case, trying to replay every historical CREATE TABLE is destructive
# and causes DuplicateTable/DuplicateObject loops. We adopt the existing schema
# by stamping Alembic to the current head before running migrations.
_DIRTY_SCHEMA_SENTINELS = {
    "agent_workflow_runs",
    "assurance_passports",
    "assurance_audit_reports",
    "compliance_jurisdictions",
    "compliance_measurements",
    "ingestion_runs",
}


def _alembic_heads() -> list[str]:
    return list(ScriptDirectory.from_config(config).get_heads())


def _table_names(connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _current_alembic_versions(connection) -> set[str]:
    tables = _table_names(connection)
    if "alembic_version" not in tables:
        return set()
    rows = connection.execute(sa.text("SELECT version_num FROM alembic_version")).fetchall()
    return {row[0] for row in rows}


def _stamp_connection_to_heads(connection, heads: list[str]) -> None:
    connection.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(255) NOT NULL)"
        )
    )
    connection.execute(sa.text("DELETE FROM alembic_version"))
    for head in heads:
        connection.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
            {"head": head},
        )
    connection.commit()


def _adopt_dirty_render_schema(connection) -> None:
    """Stamp known dirty Render preview schemas instead of replaying DDL.

    This is intentionally narrow: clean databases with no later-stage AGRO-AI
    tables still run migrations normally. Dirty preview/prod databases that
    already contain portal/assurance tables are adopted to Alembic head so
    deploys stop failing on DuplicateTable/DuplicateObject while preserving data.
    """

    if connection.dialect.name == "sqlite":
        return
    heads = set(_alembic_heads())
    if not heads:
        return

    tables = _table_names(connection)
    has_dirty_schema = bool(tables.intersection(_DIRTY_SCHEMA_SENTINELS))
    if not has_dirty_schema:
        return

    current_versions = _current_alembic_versions(connection)
    if current_versions == heads:
        return

    print(
        "Alembic adopting existing Render schema; "
        f"current_versions={sorted(current_versions)} heads={sorted(heads)}"
    )
    _stamp_connection_to_heads(connection, sorted(heads))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _adopt_dirty_render_schema(connection)

        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
