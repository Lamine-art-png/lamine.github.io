from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def stable_unified_connector_database(request):
    module = getattr(request, "module", None)
    if module is None or not module.__name__.endswith("test_connector_unification_v3_api"):
        yield
        return

    patcher = request.getfixturevalue("monkeypatch")
    temp_dir = request.getfixturevalue("tmp_path")
    original = module.create_engine
    database_path = temp_dir / "connector-unification-v3.db"

    def create_stable_engine(url, *args, **kwargs):
        if str(url) == "sqlite://":
            options = dict(kwargs)
            options.pop("poolclass", None)
            connect_args = dict(options.get("connect_args") or {})
            connect_args["check_same_thread"] = False
            options["connect_args"] = connect_args
            return original(f"sqlite:///{database_path}", *args, **options)
        return original(url, *args, **kwargs)

    patcher.setattr(module, "create_engine", create_stable_engine)
    yield
