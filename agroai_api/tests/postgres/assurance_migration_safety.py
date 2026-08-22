"""Real-PostgreSQL safety contracts for Assurance Intelligence revision 030.

This file is intentionally outside default ``test_*.py`` discovery so the
generic backend suite keeps its existing PostgreSQL skip count. CI and local
operators invoke it explicitly with a dedicated disposable database.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.assurance.models import AssuranceAuditEvent, AssurancePassport
from app.models.saas import Organization, User, Workspace


PG_URL = os.environ.get("ASSURANCE_MIGRATION_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not PG_URL.startswith("postgresql"),
    reason="ASSURANCE_MIGRATION_TEST_DATABASE_URL is not a PostgreSQL URL",
)


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", PG_URL)
    return config


def _reset_public_schema(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))


@pytest.fixture(autouse=True)
def isolated_database():
    database = make_url(PG_URL).database or ""
    assert "assurance_migration" in database, (
        "refusing to reset a database not explicitly named for assurance_migration tests"
    )
    assert os.environ.get("DATABASE_URL") == PG_URL, (
        "DATABASE_URL must equal ASSURANCE_MIGRATION_TEST_DATABASE_URL because Alembic env.py "
        "uses the application database setting"
    )
    engine = sa.create_engine(PG_URL)
    _reset_public_schema(engine)
    try:
        yield engine
    finally:
        _reset_public_schema(engine)
        engine.dispose()


def _revision(engine: sa.Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one())


def test_empty_030_roundtrip_is_safe(isolated_database):
    engine = isolated_database
    config = _config()
    command.upgrade(config, "head")
    assert _revision(engine) == "030_assurance_intelligence_v2"

    command.downgrade(config, "029_platform_cli_device_auth")
    inspector = sa.inspect(engine)
    assert _revision(engine) == "029_platform_cli_device_auth"
    assert "assurance_audit_events" not in inspector.get_table_names()
    assert "assurance_review_events" not in inspector.get_table_names()
    assert "organization_id" not in {column["name"] for column in inspector.get_columns("assurance_passports")}

    command.upgrade(config, "head")
    assert _revision(engine) == "030_assurance_intelligence_v2"


def test_modern_workspace_rows_block_before_destructive_schema_changes(isolated_database):
    engine = isolated_database
    config = _config()
    command.upgrade(config, "head")

    with Session(engine) as db:
        user = User(id="user-modern", email="modern@example.com", name="Modern", password_hash="x")
        organization = Organization(
            id="org-modern",
            name="Modern Farms",
            slug="modern-farms",
            owner_user_id=user.id,
            plan="team",
            subscription_status="active",
        )
        workspace = Workspace(
            id="ws-modern",
            organization_id=organization.id,
            name="Modern workspace",
            mode="live",
        )
        passport = AssurancePassport(
            id="passport-modern",
            tenant_id=None,
            organization_id=organization.id,
            workspace_id=workspace.id,
            entity_type="farm",
            farm_name="Modern Ranch",
            status="draft",
            rule_pack_ids=["water_assurance_generic_v1"],
            parcel_ids=[],
            metadata_json={},
        )
        audit = AssuranceAuditEvent(
            id="audit-modern",
            tenant_id=None,
            organization_id=organization.id,
            workspace_id=workspace.id,
            passport_id=passport.id,
            event_type="passport_created",
            actor_user_id=user.id,
            source_system="assurance",
            rule_pack_versions={},
            details_json={"data_must_survive": True},
        )
        # These models intentionally do not expose relationships for every
        # foreign key, so make the ownership chain explicit for PostgreSQL.
        db.add(user)
        db.commit()
        db.add(organization)
        db.commit()
        db.add(workspace)
        db.commit()
        db.add(passport)
        db.commit()
        db.add(audit)
        db.commit()

    with pytest.raises(RuntimeError, match="blocked before schema changes") as excinfo:
        command.downgrade(config, "029_platform_cli_device_auth")
    message = str(excinfo.value)
    assert "assurance_passports=1" in message
    assert "assurance_audit_events=1" in message

    inspector = sa.inspect(engine)
    assert _revision(engine) == "030_assurance_intelligence_v2"
    assert "assurance_audit_events" in inspector.get_table_names()
    passport_columns = {column["name"] for column in inspector.get_columns("assurance_passports")}
    assert {"organization_id", "workspace_id", "entity_type"} <= passport_columns
    with engine.connect() as connection:
        row = connection.execute(sa.text(
            "SELECT tenant_id, organization_id, workspace_id FROM assurance_passports "
            "WHERE id = 'passport-modern'"
        )).one()
        assert tuple(row) == (None, "org-modern", "ws-modern")
        details = connection.execute(sa.text(
            "SELECT details_json FROM assurance_audit_events WHERE id = 'audit-modern'"
        )).scalar_one()
        assert details == {"data_must_survive": True}


def test_legacy_tenant_only_rows_can_downgrade_safely(isolated_database):
    engine = isolated_database
    config = _config()
    command.upgrade(config, "029_platform_cli_device_auth")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO tenants (id, name, active) VALUES ('tenant-legacy', 'Legacy Farm', true)"
        ))
        connection.execute(
            sa.text(
                "INSERT INTO assurance_passports "
                "(id, tenant_id, farm_name, status, rule_pack_ids, parcel_ids, metadata_json) "
                "VALUES ('passport-legacy', 'tenant-legacy', 'Legacy Ranch', 'draft', "
                "CAST(:rules AS JSON), CAST(:parcels AS JSON), CAST(:metadata AS JSON))"
            ),
            {
                "rules": json.dumps(["water_assurance_generic_v1"]),
                "parcels": json.dumps([]),
                "metadata": json.dumps({"legacy": True}),
            },
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(sa.text(
            "SELECT tenant_id, organization_id, workspace_id FROM assurance_passports "
            "WHERE id = 'passport-legacy'"
        )).one()
        assert tuple(row) == ("tenant-legacy", None, None)

    command.downgrade(config, "029_platform_cli_device_auth")
    inspector = sa.inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("assurance_passports")}
    assert _revision(engine) == "029_platform_cli_device_auth"
    assert "organization_id" not in columns and "workspace_id" not in columns
    assert columns["tenant_id"]["nullable"] is False
    with engine.connect() as connection:
        legacy = connection.execute(sa.text(
            "SELECT tenant_id, farm_name, metadata_json FROM assurance_passports "
            "WHERE id = 'passport-legacy'"
        )).one()
        assert legacy.tenant_id == "tenant-legacy"
        assert legacy.farm_name == "Legacy Ranch"
        assert legacy.metadata_json == {"legacy": True}

    command.upgrade(config, "head")
    assert _revision(engine) == "030_assurance_intelligence_v2"
