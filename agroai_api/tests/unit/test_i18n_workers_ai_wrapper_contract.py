from pathlib import Path


def test_workers_ai_fastpath_preserves_backend_validation_and_internal_canary_auth():
    repo_root = Path(__file__).resolve().parents[3]
    entrypoint = (repo_root / "cloudflare" / "edge-gateway" / "src" / "edge-main-v2.ts").read_text(encoding="utf-8")
    handler = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-fastpath-handler.ts").read_text(encoding="utf-8")
    validation = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-edge-validation.ts").read_text(encoding="utf-8")
    engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-workers-ai.ts").read_text(encoding="utf-8")

    assert 'handleI18nFastpath' in entrypoint
    assert 'englishValidationRequest' in handler
    assert 'if (!checked.ok) return checked' in handler
    assert 'canaryAuthorized(request, env.QUEUE_CONSUMER_TOKEN)' in handler
    assert 'matchesConfiguredToken' in validation
    assert 'validCatalog(source, output)' in engine
    assert 'changed.length < 2' in handler
    assert 'providers: ["cloudflare_workers_ai"]' in handler
