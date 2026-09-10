from __future__ import annotations

import asyncio

from app.core.config import settings
from app.services.resilient_intelligence import _run_edge, _run_openai, _run_openrouter, run_resilient_intelligence


def _base(monkeypatch):
    monkeypatch.setattr(settings, "AI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "AI_FREE_MODEL", "provider/free-model:free")
    monkeypatch.setattr(settings, "AI_REASONING_MODEL", "z-ai/glm-5.2")
    monkeypatch.setattr(settings, "AI_REPORT_MODEL", "z-ai/glm-5.2")
    monkeypatch.setattr(settings, "AI_FAST_MODEL", "qwen/qwen3.5-flash-02-23")
    monkeypatch.setattr(settings, "AI_CHALLENGER_MODEL", "deepseek/deepseek-v4-pro")
    monkeypatch.setattr(settings, "AI_MODEL", "")
    monkeypatch.setattr(settings, "AI_MODEL_FALLBACKS", "")
    monkeypatch.setattr(settings, "APP_URL", "https://app.agroai-pilot.com")
    monkeypatch.setattr(settings, "AI_EDGE_BASE_URL", "")
    monkeypatch.setattr(settings, "AI_EDGE_MODEL", "@cf/zai-org/glm-4.7-flash")
    monkeypatch.setattr(settings, "AI_EDGE_AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "AI_EDGE_TIMEOUT_SECONDS", 45)


def test_free_hosted_model_is_attempted_before_paid_primary(monkeypatch):
    _base(monkeypatch)

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "free route online"}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.models = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            self.models.append(kwargs["json"]["model"])
            return FakeResponse()

    fake = FakeClient()
    monkeypatch.setattr(
        "app.services.resilient_intelligence.httpx.AsyncClient",
        lambda *args, **kwargs: fake,
    )

    result = asyncio.run(
        _run_openrouter(messages=[{"role": "user", "content": "test"}], profile="reasoning")
    )

    assert result == ("free route online", "provider/free-model:free")
    assert fake.models == ["provider/free-model:free"]


def test_edge_recovery_uses_known_production_origin_when_render_env_missing(monkeypatch):
    _base(monkeypatch)

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"message": {"content": '{"answer":"edge recovery online"}'}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.url = ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            self.url = url
            return FakeResponse()

    fake = FakeClient()
    monkeypatch.setattr(
        "app.services.resilient_intelligence.httpx.AsyncClient",
        lambda *args, **kwargs: fake,
    )

    result = asyncio.run(
        _run_edge(messages=[{"role": "user", "content": "test"}], profile="reasoning")
    )

    assert result == ("edge recovery online", "@cf/zai-org/glm-4.7-flash")
    assert fake.url == "https://local-ai.agroai-pilot.com/api/chat"


def test_hosted_402_does_not_block_later_free_candidate(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(settings, "AI_FREE_MODEL", "")
    monkeypatch.setattr(
        settings,
        "AI_MODEL_FALLBACKS",
        "z-ai/glm-5.2,provider/another-free:free",
    )

    class FakeResponse:
        def __init__(self, status_code, body=None):
            self.status_code = status_code
            self._body = body or {}

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.models = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            model = kwargs["json"]["model"]
            self.models.append(model)
            if model == "z-ai/glm-5.2":
                return FakeResponse(402)
            return FakeResponse(200, {"choices": [{"message": {"content": "free after 402"}}]})

    fake = FakeClient()
    monkeypatch.setattr(
        "app.services.resilient_intelligence.httpx.AsyncClient",
        lambda *args, **kwargs: fake,
    )

    result = asyncio.run(
        _run_openrouter(messages=[{"role": "user", "content": "test"}], profile="reasoning")
    )

    assert result == ("free after 402", "provider/another-free:free")
    assert fake.models == ["z-ai/glm-5.2", "provider/another-free:free"]



def test_openai_recovery_lane_uses_responses_api(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("AGROAI_INTELLIGENCE_API_KEY", "openai-test-key")
    monkeypatch.setenv("AGROAI_RECOVERY_MODEL", "gpt-5.6-luna")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"output_text": "Você deve revisar primeiro as áreas com alertas ativos."}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.url = ""
            self.payload = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            self.url = url
            self.payload = kwargs["json"]
            return FakeResponse()

    fake = FakeClient()
    monkeypatch.setattr(
        "app.services.resilient_intelligence.httpx.AsyncClient",
        lambda *args, **kwargs: fake,
    )

    result = asyncio.run(
        _run_openai(
            messages=[{"role": "user", "content": "MANDATORY RESPONSE LANGUAGE: Portuguese (pt)."}],
            profile="reasoning",
        )
    )

    assert result == ("Você deve revisar primeiro as áreas com alertas ativos.", "gpt-5.6-luna")
    assert fake.url == "https://api.openai.com/v1/responses"


def test_resilient_runtime_accepts_portuguese_from_independent_openai_lane(monkeypatch):
    _base(monkeypatch)

    async def no_edge(**kwargs):
        return None

    async def no_hosted(**kwargs):
        return None

    async def portuguese_openai(**kwargs):
        return ("Você deve revisar primeiro as áreas com alertas ativos e dados recentes.", "gpt-5.6-luna")

    monkeypatch.setattr("app.services.resilient_intelligence._run_edge", no_edge)
    monkeypatch.setattr("app.services.resilient_intelligence._run_openrouter", no_hosted)
    monkeypatch.setattr("app.services.resilient_intelligence._run_openai", portuguese_openai)
    monkeypatch.setattr("app.services.live_intelligence.LiveIntelligence.ollama_model", lambda self: None)

    result = asyncio.run(
        run_resilient_intelligence(
            task="chat",
            question="Quais áreas da fazenda precisam de mais atenção hoje?",
            messages=[
                {
                    "role": "user",
                    "content": "Preferred portal language code: pt\nMANDATORY RESPONSE LANGUAGE: Portuguese (pt).",
                }
            ],
            preferred_language="pt",
        )
    )

    assert result.status == "ok"
    assert result.provider == "openai"
    assert result.response_language == "pt"
    assert "Você" in result.content
