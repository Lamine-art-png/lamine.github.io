from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stable_connector_runtime_database(request):
    """Make only the multi-request connector runtime contract runner-independent.

    The target contract crosses several TestClient requests and SQLAlchemy
    sessions. Python 3.11 / pytest 9 exposed a runner-specific anonymous
    in-memory SQLite + StaticPool artifact where follow-up sessions could not see
    the issued OAuth nonce during the complete suite. Resolve helper fixtures
    lazily so unrelated unit tests pay no filesystem or monkeypatch overhead.
    """
    module = getattr(request, "module", None)
    if module is None or not module.__name__.endswith("test_connector_runtime_v21"):
        yield
        return

    monkeypatch = request.getfixturevalue("monkeypatch")
    tmp_path = request.getfixturevalue("tmp_path")
    original_create_engine = module.create_engine
    database_path = tmp_path / "connector-runtime.db"

    def stable_create_engine(url, *args, **kwargs):
        if str(url) == "sqlite://":
            options = dict(kwargs)
            options.pop("poolclass", None)
            connect_args = dict(options.get("connect_args") or {})
            connect_args["check_same_thread"] = False
            options["connect_args"] = connect_args
            return original_create_engine(f"sqlite:///{database_path}", *args, **options)
        return original_create_engine(url, *args, **kwargs)

    monkeypatch.setattr(module, "create_engine", stable_create_engine)
    yield
