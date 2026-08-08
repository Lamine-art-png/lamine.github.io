from __future__ import annotations


def test_public_runtime_diagnostics_are_minimal_and_non_cacheable(client):
    ai = client.get("/v1/runtime/ai-status")
    assert ai.status_code == 200
    assert set(ai.json()) <= {"status", "runtime", "configured", "checked_at"}
    assert ai.headers["cache-control"].startswith("no-store")

    email = client.get("/v1/auth/email-delivery/status")
    assert email.status_code == 200
    assert set(email.json()) == {"status", "configured"}
    assert email.headers["cache-control"].startswith("no-store")


def test_readiness_preserves_health_contract_without_configuration_inventory(client):
    response = client.get("/v1/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload["schema"]) == {"ready"}
    assert set(payload["production"]) == {
        "ready",
        "target_scale",
        "blocker_count",
        "warning_count",
    }
    rendered = response.text.lower()
    assert "missing_env" not in rendered
    assert "platform_api_key_pepper" not in rendered
    assert response.headers["cache-control"].startswith("no-store")


def test_platform_responses_are_non_cacheable_and_expose_operational_headers(client):
    response = client.get(
        "/v1/platform/health",
        headers={"origin": "https://app.agroai-pilot.com"},
    )
    assert response.headers["cache-control"].startswith("no-store")
    exposed = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-request-id" in exposed
    assert "ratelimit-limit" in exposed
    assert "retry-after" in exposed
    assert "x-agroai-error" not in exposed
