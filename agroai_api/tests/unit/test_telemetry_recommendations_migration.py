from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Float, JSON, MetaData, String, Table, create_engine, event, inspect

from app.core.config import settings
from app.db import base as db_base
from app.models import Block, Tenant


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _bootstrap_legacy_baseline(db_path: Path) -> None:
    """Create only the legitimate pre-Alembic adoption baseline.

    Historical migration 001 is adoption-safe for Tenant/Block. Pre-creating later
    migration-owned tables (for example users from migration 006) while stamping
    the database at base manufactures duplicate-table failures and does not model
    a real previous-head database.
    """
    engine = create_engine(f"sqlite:///{db_path}")
    event.listen(engine, "connect", lambda conn, _record: conn.execute("PRAGMA foreign_keys=ON"))
    db_base.Base.metadata.create_all(bind=engine, tables=[Tenant.__table__, Block.__table__])


def _compatible_telemetry(metadata: MetaData) -> Table:
    return Table(
        "telemetry", metadata,
        Column("id", String, primary_key=True),
        Column("tenant_id", String, nullable=False),
        Column("block_id", String, nullable=False),
        Column("type", String, nullable=False),
        Column("timestamp", String, nullable=False),
        Column("value", Float, nullable=False),
        Column("unit", String), Column("source", String), Column("meta_data", JSON), Column("ingested_at", String),
    )


def _compatible_recommendations(metadata: MetaData) -> Table:
    return Table(
        "recommendations", metadata,
        Column("id", String, primary_key=True),
        Column("tenant_id", String, nullable=False),
        Column("block_id", String, nullable=False),
        Column("idempotency_key", String), Column("body_hash", String), Column("feature_hash", String),
        Column("when", String, nullable=False),
        Column("duration_min", Float, nullable=False),
        Column("volume_m3", Float, nullable=False),
        Column("confidence", Float, nullable=False),
        Column("horizon_hours", Float, nullable=False),
        Column("explanations", JSON),
        Column("version", String, nullable=False),
        Column("meta_data", JSON), Column("created_at", String), Column("expires_at", String), Column("decision_run_id", String),
    )


def test_forward_migration_fresh_and_previous_head(tmp_path, monkeypatch):
    fresh_path = tmp_path / "fresh_009.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{fresh_path}")
    _bootstrap_legacy_baseline(fresh_path)
    command.upgrade(_alembic_config(fresh_path), "head")
    inspector = inspect(create_engine(f"sqlite:///{fresh_path}"))
    assert {"telemetry", "recommendations"}.issubset(inspector.get_table_names())
    assert "ix_telemetry_lookup" in {index["name"] for index in inspector.get_indexes("telemetry")}
    assert {"ix_rec_idem", "ix_rec_cache", "ix_rec_block_date"}.issubset({index["name"] for index in inspector.get_indexes("recommendations")})

    previous_path = tmp_path / "previous_009.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{previous_path}")
    _bootstrap_legacy_baseline(previous_path)
    cfg = _alembic_config(previous_path)
    command.upgrade(cfg, "008_saas_portal_v2_1_security")
    engine = create_engine(f"sqlite:///{previous_path}")
    assert "telemetry" not in inspect(engine).get_table_names()
    command.upgrade(cfg, "head")
    assert {"telemetry", "recommendations"}.issubset(inspect(engine).get_table_names())


def test_forward_migration_adopts_compatible_tables_and_downgrade_is_non_destructive(tmp_path, monkeypatch):
    db_path = tmp_path / "adoption_009.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    _bootstrap_legacy_baseline(db_path)
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "008_saas_portal_v2_1_security")
    engine = create_engine(f"sqlite:///{db_path}")
    metadata = MetaData()
    _compatible_telemetry(metadata)
    _compatible_recommendations(metadata)
    metadata.create_all(engine)

    command.upgrade(cfg, "head")
    inspector = inspect(engine)
    assert "ix_telemetry_lookup" in {index["name"] for index in inspector.get_indexes("telemetry")}
    assert "ix_rec_cache" in {index["name"] for index in inspector.get_indexes("recommendations")}

    command.downgrade(cfg, "008_saas_portal_v2_1_security")
    assert {"telemetry", "recommendations"}.issubset(inspect(engine).get_table_names())


def test_forward_migration_adopts_missing_nullable_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "partial_009.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    _bootstrap_legacy_baseline(db_path)
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "008_saas_portal_v2_1_security")
    engine = create_engine(f"sqlite:///{db_path}")
    metadata = MetaData()
    Table(
        "telemetry", metadata,
        Column("id", String, primary_key=True), Column("tenant_id", String, nullable=False),
        Column("block_id", String, nullable=False), Column("type", String, nullable=False),
        Column("timestamp", String, nullable=False), Column("value", Float, nullable=False),
    )
    Table(
        "recommendations", metadata,
        Column("id", String, primary_key=True), Column("tenant_id", String, nullable=False),
        Column("block_id", String, nullable=False), Column("when", String, nullable=False),
        Column("duration_min", Float, nullable=False), Column("volume_m3", Float, nullable=False),
        Column("confidence", Float, nullable=False), Column("horizon_hours", Float, nullable=False),
        Column("version", String, nullable=False),
    )
    metadata.create_all(engine)

    command.upgrade(cfg, "head")
    inspector = inspect(engine)
    telemetry_columns = {column["name"] for column in inspector.get_columns("telemetry")}
    recommendation_columns = {column["name"] for column in inspector.get_columns("recommendations")}
    assert {"unit", "source", "meta_data", "ingested_at"}.issubset(telemetry_columns)
    assert {"idempotency_key", "body_hash", "feature_hash", "explanations", "meta_data", "created_at", "expires_at", "decision_run_id"}.issubset(recommendation_columns)


def test_forward_migration_rejects_incompatible_existing_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "incompatible_009.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    _bootstrap_legacy_baseline(db_path)
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "008_saas_portal_v2_1_security")
    engine = create_engine(f"sqlite:///{db_path}")
    metadata = MetaData()
    Table(
        "telemetry", metadata,
        Column("id", String, primary_key=True), Column("tenant_id", String, nullable=False),
        Column("block_id", String, nullable=False), Column("type", String, nullable=False),
        Column("timestamp", String, nullable=False), Column("value", String, nullable=False),
    )
    metadata.create_all(engine)

    with pytest.raises(RuntimeError, match="incompatible"):
        command.upgrade(cfg, "head")
