from __future__ import annotations

import io
import json

from agroai_platform import cli
from agroai_platform import session


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_service_account_commands_are_human_control_plane(monkeypatch):
    calls = []

    def fake(method, path, *, json_body=None, timeout=20.0):
        calls.append((method, path, json_body))
        if method == "GET":
            return FakeResponse({"status": "ok", "service_accounts": []})
        return FakeResponse({"status": "ok", "service_account": {"id": "sa_1"}}, 201)

    monkeypatch.setattr(session, "control_plane_request", fake)
    code, _, _ = run_cli(["service-accounts", "list", "--project-id", "prj_1"])
    assert code == cli.EXIT_OK
    code, _, _ = run_cli([
        "service-accounts", "create", "--project-id", "prj_1", "--name", "local-dev",
        "--scope", "fields:read", "--scope", "fields:write",
    ])
    assert code == cli.EXIT_OK
    assert calls[0][:2] == ("GET", "/v1/platform/developer/service-accounts?project_id=prj_1")
    assert calls[1][0:2] == ("POST", "/v1/platform/developer/projects/prj_1/service-accounts")
    assert calls[1][2]["scopes"] == ["fields:read", "fields:write"]


def test_bootstrap_creates_test_project_service_account_and_one_time_key(monkeypatch):
    calls = []

    def fake(method, path, *, json_body=None, timeout=20.0):
        calls.append((method, path, json_body))
        if path == "/v1/platform/developer/projects":
            assert json_body["environment"] == "test"
            return FakeResponse({"status": "ok", "project": {"id": "prj_test_1"}}, 201)
        if path == "/v1/platform/developer/projects/prj_test_1/service-accounts":
            assert "actions:execute" not in json_body["scopes"]
            return FakeResponse({"status": "ok", "service_account": {"id": "sa_test_1"}}, 201)
        if path == "/v1/platform/developer/service-accounts/sa_test_1/keys":
            assert "actions:execute" not in json_body["scopes"]
            return FakeResponse({
                "status": "ok",
                "key": {"id": "key_test_1"},
                "plaintext_key": "agro_test_example-one-time-secret",
                "plaintext_display": "one_time_only",
            }, 201)
        raise AssertionError(path)

    monkeypatch.setattr(session, "control_plane_request", fake)
    code, out, err = run_cli(["--json", "bootstrap", "--name", "First integration"])
    assert code == cli.EXIT_OK, err
    payload = json.loads(out)
    assert payload["environment"] == "test"
    assert payload["project_id"] == "prj_test_1"
    assert payload["service_account_id"] == "sa_test_1"
    assert payload["key_id"] == "key_test_1"
    assert payload["api_key"].startswith("agro_test_")
    assert payload["plaintext_display"] == "one_time_only"
    assert len(calls) == 3


def test_bootstrap_never_requests_live_or_physical_scope(monkeypatch):
    captured = []

    def fake(method, path, *, json_body=None, timeout=20.0):
        captured.append((path, json_body or {}))
        if path.endswith("/projects"):
            return FakeResponse({"project": {"id": "p"}}, 201)
        if path.endswith("/service-accounts"):
            return FakeResponse({"service_account": {"id": "s"}}, 201)
        return FakeResponse({"key": {"id": "k"}, "plaintext_key": "agro_test_x"}, 201)

    monkeypatch.setattr(session, "control_plane_request", fake)
    code, _, _ = run_cli(["bootstrap"])
    assert code == cli.EXIT_OK
    project_body = captured[0][1]
    assert project_body["environment"] == "test"
    for _path, body in captured:
        scopes = body.get("scopes") or []
        assert "actions:execute" not in scopes
        assert "connectors:write" not in scopes
