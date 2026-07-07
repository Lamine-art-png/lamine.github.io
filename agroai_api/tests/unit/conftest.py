from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stable_connector_runtime_database(request, monkeypatch, tmp_path):
    """Make the multi-request connector runtime contract runner-independent.

    ``test_connector_runtime_v21`` intentionally crosses several TestClient
    requests and SQLAlchemy sessions. Python 3.11 / pytest 9 exposed that its
    anonymous in-memory SQLite + StaticPool fixture could route follow-up
    sessions to state that did not contain the issued OAuth nonce during the
    complete suite, even though the same contract passed in isolation.

    Preserve the test's production behavior and assertions, but transparently
    replace only that module's anonymous ``sqlite://`` engine with a unique
    file-backed SQLite database for each test. This models real durable
    multi-request persistence and avoids cross-runner pool/thread artifacts.
    """
    module = getattr(request, "module", None)
    if module is None or not module.__name__.endswith("test_connector_runtime_v21"):
        yield
        return

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
