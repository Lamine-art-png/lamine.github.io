from __future__ import annotations

from types import SimpleNamespace

from app.core.config import settings
from app.models.operational_records import IntelligenceRun
from tests.unit.test_platform_api_foundation import _project_and_key


async def _fake_live_run(**kwargs):
    context = kwargs["context"]
    return (
        {
            "summary": "Irrigate before peak heat based on the supplied field context.",
            "recommendation": "Run the next irrigation in the early morning window.",
            "available_data": ["Customer-supplied request context"],
            "recommendations": ["Verify flow at startup", "Review soil moisture after the set"],
            "next_actions": ["Confirm actual flow rate"],
            "risk_flags": [],
            "missing_data": list(context.missing_data),
            "confidence": "medium",
        },
        SimpleNamespace(
            status="ok",
            provider="test-provider",
            model="test-model",
            demo_fallback=False,
            error=None,
            content="{}",
        ),
    )


async def _fake_failed_run(**_kwargs):
    return (
        {
            "summary": "Live intelligence is temporarily unavailable.",
            "recommendations": [],
            "next_actions": [],
            "risk_flags": ["Provider unavailable"],
            "missing_data": [],
            "confidence": "low",
        },
        SimpleNamespace(
            status="unavailable",
            provider="test-provider",
            model="test-model",
            demo_fallback=False,
            error="provider_unavailable",
            content="",
        ),
    )


def _headers(key: str, idem: str) -> dict[str, str]:
    return {"X-API-Key": key, "Idempotency-Key": idem}


def test_intelligence_run_is_one_call_project_scoped_and_idempotent(client, db, monkeypatch):
    *_parts, project, _service_account, _key, plaintext = _project_and_key(
        db,
        scopes=["recommendations:read"],
        environment="test",
    )
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED", False, raising=False)
    monkeypatch.setattr("app.api.v1.platform_intelligence_api._run_ai", _fake_live_run)

    payload = {
        "task": "irrigation_plan",
        "question": "What should this field do over the next 24 hours?",
        "input": {
            "crop": "almond",
            "location": "Fresno, California",
            "soil_moisture_pct": 24.8,
            "temperature_c": 34.1,
            "et_mm": 6.2,
        },
    }
    first = client.post(
        "/v1/platform/intelligence",
        json=payload,
        headers=_headers(plaintext, "intel-idem-1"),
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["object"] == "agroai.intelligence_run"
    assert body["task"] == "irrigation_plan"
    assert body["status"] == "completed"
    assert body["summary"].startswith("Irrigate")
    assert body["usage"]["billable"] is True
    assert body["provider"] == "test-provider"

    replay = client.post(
        "/v1/platform/intelligence",
        json=payload,
        headers=_headers(plaintext, "intel-idem-1"),
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == body["id"]

    rows = db.query(IntelligenceRun).filter(IntelligenceRun.id == body["id"]).all()
    assert len(rows) == 1
    assert rows[0].provenance_json["api_project_id"] == project.id

    fetched = client.get(
        f"/v1/platform/intelligence/{body['id']}",
        headers={"X-API-Key": plaintext},
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_failed_provider_is_not_billable(client, db, monkeypatch):
    *_parts, _project, _service_account, _key, plaintext = _project_and_key(
        db,
        scopes=["recommendations:read"],
        environment="test",
    )
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED", False, raising=False)
    monkeypatch.setattr("app.api.v1.platform_intelligence_api._run_ai", _fake_failed_run)

    response = client.post(
        "/v1/platform/intelligence",
        json={"task": "general", "question": "What needs attention?", "input": {"crop": "corn"}},
        headers=_headers(plaintext, "intel-idem-fail"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["usage"]["billable"] is False
    assert body["usage"]["credits"] == 0


def test_intelligence_run_rejects_secrets_in_customer_context(client, db, monkeypatch):
    *_parts, _project, _service_account, _key, plaintext = _project_and_key(
        db,
        scopes=["recommendations:read"],
        environment="test",
    )
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True, raising=False)

    response = client.post(
        "/v1/platform/intelligence",
        json={"task": "general", "question": "Analyze this", "input": {"api_key": "secret"}},
        headers=_headers(plaintext, "intel-idem-secret"),
    )
    assert response.status_code == 422
