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

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

if settings.DATABASE_URL:
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


# Automatic adoption is an escape hatch only for unversioned legacy Render
# databases whose schema already proves current-head shape. Requiring a
# representative object from every later migration layer prevents an older or
# partially migrated schema from being silently stamped past required DDL.
_HEAD_SCHEMA_SENTINELS = {
    # 003 global compliance kernel
    "compliance_export_metadata",
    # 004 assurance audit MVP
    "assurance_passports",
    # 005 deterministic agent workflow layer
    "agent_workflow_runs",
    # 006 SaaS auth/billing foundation
    "users",
    "organizations",
    "workspaces",
    # 007 portal v2
    "conversations",
    "conversation_messages",
    # 008 portal v2.1 security
    "email_verification_tokens",
    "team_invitations",
    # 009 starter field context
    "telemetry",
    "recommendations",
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
    """Adopt only unversioned legacy databases that already match head shape.

    Any explicit Alembic version is authoritative and must advance through
    normal migrations. Unversioned partial schemas are also migrated normally;
    they are never promoted merely because one historical table exists.
    """
    if connection.dialect.name == "sqlite":
        return

    heads = set(_alembic_heads())
    if not heads:
        return

    current_versions = _current_alembic_versions(connection)
    if current_versions:
        return

    tables = _table_names(connection)
    if not _HEAD_SCHEMA_SENTINELS.issubset(tables):
        return

    print(
        "Alembic adopting unversioned current-head-shaped Render schema; "
        f"current_versions=[] heads={sorted(heads)}"
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
