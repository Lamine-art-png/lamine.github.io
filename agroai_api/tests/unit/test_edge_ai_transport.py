from __future__ import annotations

import asyncio

from app.core.config import settings
from app.services.ai_gateway import AIGateway
from app.services.local_ui_translation import run_local_ui_translation


def _configure_edge(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "AI_BASE_URL", "https://local-ai.agroai-pilot.com")
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    monkeypatch.setattr(settings, "AI_MODEL", "@cf/zai-org/glm-4.7-flash")
    monkeypatch.setattr(settings, "AI_MODEL_FALLBACKS", "")
    monkeypatch.setattr(settings, "AI_EDGE_BASE_URL", "https://local-ai.agroai-pilot.com")
    monkeypatch.setattr(settings, "AI_EDGE_MODEL", "@cf/zai-org/glm-4.7-flash")
    monkeypatch.setattr(settings, "AI_EDGE_AUTH_TOKEN", "edge-secret")
    monkeypatch.setattr(settings, "AI_TIMEOUT_SECONDS", 30)


def test_gateway_attaches_edge_origin_bearer_and_uses_actual_identity(monkeypatch):
    _configure_edge(monkeypatch)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "provider": "cloudflare-workers-ai",
                "model": "@cf/zai-org/glm-4.7-flash",
                "requested_model": "fake/requested-alias",
                "message": {"content": '{"answer":"edge gateway online"}'},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self.headers = kwargs.get("headers")
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.ai_gateway.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    result = asyncio.run(
        AIGateway().chat(
            [{"role": "user", "content": "test"}],
            model_override="fake/requested-alias",
        )
    )

    assert result.status == "ok"
    assert result.content == "edge gateway online"
    assert result.provider == "cloudflare-workers-ai"
    assert result.model == "@cf/zai-org/glm-4.7-flash"
    assert fake_client.headers == {"Authorization": "Bearer edge-secret"}


def test_edge_ui_translation_allows_cloudflare_model_id_and_sends_auth(monkeypatch):
    _configure_edge(monkeypatch)

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "provider": "cloudflare-workers-ai",
                "model": "@cf/zai-org/glm-4.7-flash",
                "translation_mode": True,
                "message": {"content": '{"title":"Bonjour","button":"Envoyer"}'},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.local_ui_translation.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    result = asyncio.run(
        run_local_ui_translation(
            base_url="https://local-ai.agroai-pilot.com",
            model="@cf/zai-org/glm-4.7-flash",
            messages=[
                {"role": "system", "content": "Translate every JSON string value into French (fr)."},
                {"role": "user", "content": 'QUESTION: {"title":"Hello","button":"Send"}'},
            ],
        )
    )

    assert result.status == "ok"
    assert result.provider == "cloudflare-workers-ai"
    assert result.model == "@cf/zai-org/glm-4.7-flash"
    assert result.content == '{"title":"Bonjour","button":"Envoyer"}'
    assert len(fake_client.calls) == 1
    url, kwargs = fake_client.calls[0]
    assert url == "https://local-ai.agroai-pilot.com/api/chat"
    assert kwargs["headers"] == {"Authorization": "Bearer edge-secret"}


def test_actual_local_translation_keeps_generate_fallback_without_edge_auth(monkeypatch):
    _configure_edge(monkeypatch)
    monkeypatch.setattr(settings, "AI_EDGE_BASE_URL", "https://local-ai.agroai-pilot.com")

    class FakeResponse:
        def __init__(self, status_code, body=None):
            self.status_code = status_code
            self._body = body or {}
            self.text = "failed" if status_code >= 400 else ""

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if url.endswith("/api/chat"):
                return FakeResponse(500)
            return FakeResponse(200, {"response": '{"title":"Bonjour"}'})

    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.local_ui_translation.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    result = asyncio.run(
        run_local_ui_translation(
            base_url="http://127.0.0.1:11434",
            model="qwen3.5:4b",
            messages=[{"role": "user", "content": "translate"}],
        )
    )

    assert result.status == "ok"
    assert result.provider == "ollama"
    assert [url for url, _ in fake_client.calls] == [
        "http://127.0.0.1:11434/api/chat",
        "http://127.0.0.1:11434/api/generate",
    ]
    assert all(kwargs["headers"] == {} for _, kwargs in fake_client.calls)
