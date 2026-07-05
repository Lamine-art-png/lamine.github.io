from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services import release_contract as contract


def db_at(version: str):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": version})
    return sessionmaker(bind=engine)()


def test_release_contract_is_ready_only_for_exact_build_schema_and_queue(monkeypatch):
    db = db_at("head-1")
    monkeypatch.setattr(contract, "repository_alembic_heads", lambda: ("head-1",))
    monkeypatch.setattr(contract, "runtime_build_sha", lambda: "abc123")
    monkeypatch.setattr(contract, "queue_configured", lambda: True)
    report = contract.evaluate_release_contract(db)
    assert report["status"] == "ok"
    assert report["schema_current"] is True
    assert report["build_sha"] == "abc123"
    assert report["queue_configured"] is True


def test_release_contract_blocks_schema_drift(monkeypatch):
    db = db_at("old-head")
    monkeypatch.setattr(contract, "repository_alembic_heads", lambda: ("new-head",))
    monkeypatch.setattr(contract, "runtime_build_sha", lambda: "abc123")
    monkeypatch.setattr(contract, "queue_configured", lambda: True)
    report = contract.evaluate_release_contract(db)
    assert report["status"] == "blocked"
    assert report["schema_current"] is False


def test_release_contract_blocks_missing_build_or_queue(monkeypatch):
    db = db_at("head-1")
    monkeypatch.setattr(contract, "repository_alembic_heads", lambda: ("head-1",))
    monkeypatch.setattr(contract, "runtime_build_sha", lambda: "")
    monkeypatch.setattr(contract, "queue_configured", lambda: False)
    report = contract.evaluate_release_contract(db)
    assert report["status"] == "blocked"
