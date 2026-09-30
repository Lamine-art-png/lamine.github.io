"""Exercise 037 against populated tables, including FK enforcement and rollback."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_invitation_migration_preserves_existing_rows_and_constraints():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/037_team_invitation_delivery.py"
    spec = importlib.util.spec_from_file_location("invitation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE users (id VARCHAR PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE organizations (id VARCHAR PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE team_invitations (id VARCHAR PRIMARY KEY, organization_id VARCHAR REFERENCES organizations(id), email VARCHAR NOT NULL, status VARCHAR NOT NULL, token_hash VARCHAR UNIQUE)")
        connection.exec_driver_sql("INSERT INTO users VALUES ('recipient')")
        connection.exec_driver_sql("INSERT INTO organizations VALUES ('org')")
        connection.exec_driver_sql("INSERT INTO team_invitations VALUES ('legacy', 'org', 'person@example.com', 'pending', 'hash')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT token_hash, delivery_attempts, accepted_by_user_id FROM team_invitations").one() == ("hash", 0, None)
        foreign_keys = sa.inspect(connection).get_foreign_keys("team_invitations")
        assert any(fk["constrained_columns"] == ["accepted_by_user_id"] for fk in foreign_keys)
        with pytest.raises(sa.exc.IntegrityError):
            connection.exec_driver_sql("UPDATE team_invitations SET accepted_by_user_id='missing'")
        connection.exec_driver_sql("UPDATE team_invitations SET accepted_by_user_id='recipient'")
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.exec_driver_sql("SELECT * FROM team_invitations").one() == ("legacy", "org", "person@example.com", "pending", "hash")
        assert "accepted_by_user_id" not in {c["name"] for c in sa.inspect(connection).get_columns("team_invitations")}
        with pytest.raises(sa.exc.IntegrityError):
            connection.exec_driver_sql("INSERT INTO team_invitations VALUES ('duplicate', 'org', 'other@example.com', 'pending', 'hash')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT count(*) FROM team_invitations").scalar() == 1
