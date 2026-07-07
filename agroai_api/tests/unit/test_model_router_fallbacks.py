from app.core.config import settings
from app.services.model_router import DEFAULT_MODEL_FALLBACKS, ModelRouter


def test_task_router_propagates_fallbacks_into_gateway_retry_loop(monkeypatch):
    monkeypatch.setattr(settings, "AI_MODEL_FALLBACKS", "custom/fast-backup,custom/second-backup")

    router = ModelRouter()

    assert router.gateway.fallback_models == router.fallback_models
    assert router.fallback_models[:2] == ["custom/fast-backup", "custom/second-backup"]
    assert all(model in router.fallback_models for model in DEFAULT_MODEL_FALLBACKS)

    candidates = router.gateway._candidate_models(router.fast_model, max_model_attempts=4)
    assert candidates[0] == router.fast_model
    assert len(candidates) == 4
    assert len(set(candidates)) == 4
