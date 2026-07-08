from __future__ import annotations

import pytest


_STABLE_SQLITE_TARGETS = {
    "test_connector_runtime_v21": "connector-runtime.db",
    "test_connector_unification_v3_api": "connector-unification-v3.db",
}


@pytest.fixture(autouse=True)
def _unit_test_runtime_compatibility(request):
    """Keep focused unit fixtures aligned with the production runtime contract.

    Connector contracts that span TestClient threads use a stable temporary
    SQLite file. Intelligence-core tests exercise the paid execution engine, so
    their synthetic organization is promoted to an active Professional fixture
    after the legacy helper seeds it. Free-plan 402 behavior is covered by the
    dedicated Ask AGRO-AI commercial-boundary tests.
    """
    module = getattr(request, "module", None)
    if module is None:
        yield
        return

    if module.__name__.endswith("test_intelligence_core"):
        monkeypatch = request.getfixturevalue("monkeypatch")
        original_seed = module._seed_auth_context

        def paid_intelligence_seed(db):
            user, org, workspace = original_seed(db)
            org.plan = "professional"
            org.subscription_status = "active"
            db.commit()
            return user, org, workspace

        monkeypatch.setattr(module, "_seed_auth_context", paid_intelligence_seed)
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
