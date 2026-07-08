from __future__ import annotations

from types import SimpleNamespace

from app.services.demo_environment import DEMO_SEED_LOCK_KEY, _acquire_demo_seed_lock


class _FakeSession:
    def __init__(self, dialect_name: str):
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self.executions = []

    def get_bind(self):
        return self._bind

    def execute(self, statement, parameters):
        self.executions.append((str(statement), parameters))


def test_postgresql_demo_seed_uses_transaction_advisory_lock():
    db = _FakeSession("postgresql")

    _acquire_demo_seed_lock(db)

    assert db.executions == [
        (
            "SELECT pg_advisory_xact_lock(:lock_key)",
            {"lock_key": DEMO_SEED_LOCK_KEY},
        )
    ]


def test_non_postgresql_demo_seed_lock_is_noop():
    db = _FakeSession("sqlite")

    _acquire_demo_seed_lock(db)

    assert db.executions == []
