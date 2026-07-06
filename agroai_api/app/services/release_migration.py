from __future__ import annotations

import os
import time

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


MIGRATION_LOCK_ID = 6174020260705


def acquire_migration_lock(connection: sa.Connection, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        acquired = connection.execute(
            sa.text("SELECT pg_try_advisory_lock(:value)"),
            {"value": MIGRATION_LOCK_ID},
        ).scalar_one()
        if bool(acquired):
            return
        time.sleep(2)
    raise RuntimeError("Timed out waiting for the AGRO-AI migration lock")


def release_migration_lock(connection: sa.Connection) -> None:
    connection.execute(
        sa.text("SELECT pg_advisory_unlock(:value)"),
        {"value": MIGRATION_LOCK_ID},
    )


def run_alembic_upgrade(database_url: str, api_root) -> None:
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
