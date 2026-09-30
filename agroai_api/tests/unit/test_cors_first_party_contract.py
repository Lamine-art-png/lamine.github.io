"""The direct API hostname admits exactly the first-party origins and headers
the edge gateway admits, and nothing else."""
import pytest

PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,x-request-id,idempotency-key"}


@pytest.mark.parametrize("origin", ["https://app.agroai-pilot.com", "https://platform.agroai-pilot.com", "https://agroai-pilot.com"])
def test_first_party_preflight_allowed(client, origin):
    response = client.options("/v1/auth/email-verification/confirm", headers={"Origin": origin, **PREFLIGHT})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["https://evil.example", "https://app.agroai-pilot.com.evil.example", "null"])
def test_foreign_origin_preflight_rejected(client, origin):
    response = client.options("/v1/auth/email-verification/confirm", headers={"Origin": origin, **PREFLIGHT})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_unlisted_header_still_rejected(client):
    response = client.options(
        "/v1/auth/email-verification/confirm",
        headers={"Origin": "https://app.agroai-pilot.com", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-debug-override"},
    )
    assert response.status_code == 400
