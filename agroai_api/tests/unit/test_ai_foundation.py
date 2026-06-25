import asyncio

from app.core.security import create_access_token
from app.models.block import Block
from app.models.tenant import Tenant
from app.services.ai_gateway import AIGateway, AIGatewayResult


def _headers(tenant_id: str = "test-tenant") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'tenant_id': tenant_id})}"}


def test_ai_gateway_missing_env_returns_unavailable(monkeypatch):
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_PROVIDER", "")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_BASE_URL", "")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_API_KEY", "")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_MODEL", "")

    result = asyncio.run(AIGateway().chat([{"role": "user", "content": "Assess irrigation"}]))

    assert result.status == "unavailable"
    assert result.demo_fallback is True
    assert result.provider == "offline"
    assert "AI unavailable/demo fallback" in result.content


def test_ai_gateway_mocked_provider_returns_content(monkeypatch):
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_PROVIDER", "openai_compatible")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_BASE_URL", "https://models.example.test/v1")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_API_KEY", "test-key")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_MODEL", "farm-model")

    async def fake_chat(self, messages, temperature, response_format):
        return AIGatewayResult(
            status="ok",
            content='{"summary":"Use verified field evidence only."}',
            provider=self.provider,
            model=self.model,
        )

    monkeypatch.setattr(AIGateway, "_chat_openai_compatible", fake_chat)

    result = asyncio.run(AIGateway().chat([{"role": "user", "content": "Draft report"}]))

    assert result.status == "ok"
    assert result.provider == "openai_compatible"
    assert result.model == "farm-model"
    assert "verified field evidence" in result.content


def test_ai_routes_require_auth(client):
    response = client.post("/v1/ai/chat", json={"message": "What is ready?"})

    assert response.status_code == 401


def test_agent_run_returns_unavailable_when_provider_missing(client, test_block, monkeypatch):
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_PROVIDER", "")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_BASE_URL", "")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_API_KEY", "")
    monkeypatch.setattr("app.services.ai_gateway.settings.AI_MODEL", "")

    response = client.post(
        "/v1/agents/run",
        json={"task": "irrigation_recommendation", "block_id": test_block.id},
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["demo_fallback"] is True
    assert body["verification"]["status"] == "unavailable"


def test_ai_route_preserves_tenant_isolation(client, db):
    db.add(Tenant(id="other-tenant", name="Other", tier="enterprise", active=True))
    db.add(
        Block(
            id="other-block",
            tenant_id="other-tenant",
            name="Other Field",
            area_ha=4.0,
            crop_type="almonds",
            soil_type="clay",
        )
    )
    db.commit()

    response = client.post(
        "/v1/ai/chat",
        json={"message": "Review this block", "block_id": "other-block"},
        headers=_headers("test-tenant"),
    )

    assert response.status_code == 404


def test_mocked_successful_ai_route_returns_structured_json(client, test_block, monkeypatch):
    async def fake_chat(self, messages, temperature=0.2, response_format=None):
        return AIGatewayResult(
            status="ok",
            content=(
                '{"recommendation":"Irrigate only after validating fresh soil moisture",'
                '"confidence":"medium","evidence_used":["block","telemetry"],'
                '"missing_data":["current flow meter reading"],'
                '"risk_flags":["telemetry is limited"],'
                '"next_action":"Collect current flow and valve status."}'
            ),
            provider="mock",
            model="mock-farm-model",
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)

    response = client.post(
        "/v1/ai/irrigation-recommendation",
        json={"task": "irrigation_recommendation", "block_id": test_block.id},
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["output"]["recommendation"].startswith("Irrigate only")
    assert body["provider"] == "mock"
    assert body["evidence_context"]["organization_id"] == "test-tenant"
    assert body["citations"]
