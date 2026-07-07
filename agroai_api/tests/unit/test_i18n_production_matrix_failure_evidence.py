from pathlib import Path


def test_workers_ai_validation_fastpath_is_bound_for_production_release():
    repo_root = Path(__file__).resolve().parents[3]
    wrangler = (repo_root / "wrangler.toml").read_text(encoding="utf-8")
    entrypoint = (repo_root / "cloudflare" / "edge-gateway" / "src" / "edge-main-v2.ts").read_text(encoding="utf-8")
    handler = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-fastpath-handler.ts").read_text(encoding="utf-8")
    engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-workers-ai.ts").read_text(encoding="utf-8")

    assert 'main = "cloudflare/edge-gateway/src/edge-main-v2.ts"' in wrangler
    assert '[ai]' in wrangler
    assert 'binding = "AI"' in wrangler
    assert 'handleI18nFastpath' in entrypoint
    assert 'englishValidationRequest' in handler
    assert 'canaryAuthorized' in handler
    assert 'cloudflare_workers_ai' in handler
    assert '@cf/zai-org/glm-4.7-flash' in engine
    assert 'PLACEHOLDER_RE' in engine
