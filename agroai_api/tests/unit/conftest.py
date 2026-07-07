from __future__ import annotations

import pytest


_STABLE_SQLITE_TARGETS = {
    "test_connector_runtime_v21": "connector-runtime.db",
    "test_connector_unification_v3_api": "connector-unification-v3.db",
}


@pytest.fixture(autouse=True)
def _stable_connector_runtime_database(request):
    """Make multi-request connector contract tests runner-independent.

    The target contracts cross several TestClient requests and SQLAlchemy
    sessions. Python 3.11 / pytest 9 can expose a runner-specific anonymous
    in-memory SQLite + StaticPool artifact where follow-up sessions do not see
    rows committed through the TestClient thread. Resolve helper fixtures lazily
    so unrelated unit tests pay no filesystem or monkeypatch overhead.
    """
    module = getattr(request, "module", None)
    if module is None:
        yield
        return

    database_filename = next(
        (
            filename
            for module_suffix, filename in _STABLE_SQLITE_TARGETS.items()
            if module.__name__.endswith(module_suffix)
        ),
        None,
    )
    if database_filename is None:
        yield
        return

    monkeypatch = request.getfixturevalue("monkeypatch")
    tmp_path = request.getfixturevalue("tmp_path")
    original_create_engine = module.create_engine
    database_path = tmp_path / database_filename

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
