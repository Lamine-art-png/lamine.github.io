"""CLI contract tests — offline, no network. They mock the SDK transport."""
from __future__ import annotations

import io
import json

import pytest

from agroai_platform import cli
from agroai_platform import client as client_module


class _FakeResp:
    def __init__(self, status_code, payload, request_id="req_cli_1"):
        self.status_code = status_code
        self._payload = payload
        self.headers = {"X-Request-Id": request_id}
        self.content = b"{}"  # truthy so the SDK parses json()
        self.ok = status_code < 400

    def json(self):
        return self._payload


def _mock_transport(monkeypatch, status_code, payload):
    def fake_request(method, url, **kwargs):
        return _FakeResp(status_code, payload)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    # The SDK retries 429/5xx with a sleep; keep the tests instant.
    monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)


def _run(argv, monkeypatch, *, key="agro_test_examplekey0000000000000000"):
    monkeypatch.setenv("AGROAI_API_KEY", key)
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "agroai" in capsys.readouterr().out


def test_me_json_output(monkeypatch):
    _mock_transport(monkeypatch, 200, {"organization_id": "org_1", "environment": "test"})
    code, out, _ = _run(["--json", "me"], monkeypatch)
    assert code == cli.EXIT_OK
    assert json.loads(out)["organization_id"] == "org_1"


def test_fields_list_human_output(monkeypatch):
    _mock_transport(monkeypatch, 200, {"items": [{"id": "fld_1"}], "next_cursor": None})
    code, out, _ = _run(["fields", "list"], monkeypatch)
    assert code == cli.EXIT_OK
    assert "items" in out


def test_missing_api_key_is_config_error(monkeypatch):
    monkeypatch.delenv("AGROAI_API_KEY", raising=False)
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["me"], out=out, err=err)
    assert code == cli.EXIT_CONFIG
    assert "AGROAI_API_KEY" in err.getvalue()


def test_auth_error_maps_to_exit_3(monkeypatch):
    _mock_transport(monkeypatch, 401, {"code": "invalid_key", "message": "bad key"})
    code, _, err = _run(["me"], monkeypatch)
    assert code == cli.EXIT_AUTH
    assert "bad key" in err


def test_rate_limited_maps_to_exit_4(monkeypatch):
    _mock_transport(monkeypatch, 429, {"code": "rate_limited", "message": "slow down"})
    code, _, _ = _run(["me"], monkeypatch)
    assert code == cli.EXIT_RATE_LIMITED


def test_not_found_maps_to_exit_5(monkeypatch):
    _mock_transport(monkeypatch, 404, {"code": "not_found", "message": "no field"})
    code, _, _ = _run(["fields", "get", "fld_missing"], monkeypatch)
    assert code == cli.EXIT_NOT_FOUND


def test_login_is_honest_stub_not_fake_success(monkeypatch):
    code, _, err = _run(["login"], monkeypatch)
    assert code == cli.EXIT_ERROR
    assert "not yet available" in err.lower()


def test_doctor_never_prints_full_key(monkeypatch):
    _mock_transport(monkeypatch, 200, {"organization_id": "org_1", "environment": "test"})
    secret = "agro_test_SUPERSECRETdonotprintaaaaaaaaaaaaa"
    code, out, err = _run(["doctor"], monkeypatch, key=secret)
    combined = out + err
    assert secret not in combined  # full key must never appear
    assert "test" in combined  # environment is derived and safe to show
    assert code == cli.EXIT_OK


def test_doctor_json_healthy_flag(monkeypatch):
    _mock_transport(monkeypatch, 200, {"organization_id": "org_1"})
    code, out, _ = _run(["--json", "doctor"], monkeypatch)
    doc = json.loads(out)
    assert doc["healthy"] is True
    assert code == cli.EXIT_OK
    # No check may echo the full key.
    assert "SUPERSECRET" not in out
