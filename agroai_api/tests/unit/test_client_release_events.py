"""Portal release diagnostics accept only privacy-safe categories."""
import logging

from app.api.v1 import client_release_events as events


def test_release_event_is_logged_with_only_safe_fields(client, caplog):
    caplog.set_level(logging.INFO, logger="agroai.frontend_release")
    response = client.post("/v1/client/release-events", json={
        "event": "stale_build_detected", "running_build": "a" * 40, "latest_build": "b" * 40,
        "route": "/team", "visibility": "visible", "reason": "peer_tab",
        "token": "secret-bearer", "email": "person@example.com",
    })
    assert response.status_code == 202
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "stale_build_detected" in logged and "a" * 40 in logged and "/team" in logged
    assert "secret-bearer" not in logged and "person@example.com" not in logged


def test_free_text_reasons_and_unknown_events_are_dropped(client, caplog):
    caplog.set_level(logging.INFO, logger="agroai.frontend_release")
    client.post("/v1/client/release-events", json={"event": "dynamic_import_failure", "reason": "TypeError: Failed to fetch https://app/assets/x.js?token=abc", "route": "/team/123"})
    client.post("/v1/client/release-events", json={"event": "arbitrary", "running_build": "x"})
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "TypeError" in logged and "token=abc" not in logged and "/team/123" not in logged
    assert "arbitrary" not in logged
    assert client.post("/v1/client/release-events", content=b"x" * 5000, headers={"content-type": "application/json"}).status_code == 202


def test_stale_client_build_is_logged_once_per_interval(client, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger="agroai.frontend_release")
    monkeypatch.setattr("app.services.release_contract.runtime_build_sha", lambda: "c" * 40)
    events._SKEW_LOGGED.clear()
    for _ in range(3):
        client.get("/v1/health", headers={"X-AGROAI-Client-Build": "d" * 40})
    client.get("/v1/health", headers={"X-AGROAI-Client-Build": "c" * 40})
    skew = [r.getMessage() for r in caplog.records if "frontend_build_skew" in r.getMessage()]
    assert len(skew) == 1 and "d" * 40 in skew[0]
