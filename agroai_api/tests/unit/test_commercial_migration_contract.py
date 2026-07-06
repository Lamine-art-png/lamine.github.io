from importlib import import_module
from pathlib import Path


def test_commercial_migration_extends_current_main_head():
    migration = import_module("alembic.versions.016_commercial_control_plane")
    assert migration.revision == "016_commercial_control_plane"
    assert migration.down_revision == "015_saas_requests_repair"


def test_commercial_migration_contains_only_canonical_legacy_backfills():
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "016_commercial_control_plane.py"
    source = path.read_text(encoding="utf-8")
    assert "lower(plan) = 'pilot'" in source
    assert "SET plan = 'free'" in source
    assert "'pro', 'waterops', 'assurance_audit'" in source
    assert "SET plan = 'professional'" in source
    assert "lower(plan) = 'assurance'" in source
    assert "SET plan = 'team'" in source
    assert "waterops' WHERE" not in source


def test_commercial_migration_owns_contract_override_and_quota_tables():
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "016_commercial_control_plane.py"
    source = path.read_text(encoding="utf-8")
    for table in ("entitlement_overrides", "commercial_contracts", "managed_entities", "quota_reservations"):
        assert f'"{table}"' in source
