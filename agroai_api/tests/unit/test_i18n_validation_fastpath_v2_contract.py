from pathlib import Path


def test_active_validation_fastpath_is_language_aware_and_nonblocking():
    repo_root = Path(__file__).resolve().parents[3]
    wrangler = (repo_root / "wrangler.toml").read_text(encoding="utf-8")
    entrypoint = (repo_root / "cloudflare" / "edge-gateway" / "src" / "edge-main-v2.ts").read_text(encoding="utf-8")
    handler = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-fastpath-handler.ts").read_text(encoding="utf-8")
    engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-workers-ai-v2.ts").read_text(encoding="utf-8")
    validation = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-edge-validation-v2.ts").read_text(encoding="utf-8")

    assert 'main = "cloudflare/edge-gateway/src/edge-main-v2.ts"' in wrangler
    assert 'handleI18nFastpath' in entrypoint
    assert 'englishValidationRequest' in handler
    assert 'canaryAuthorized(request, env.' in handler
    assert 'translateCatalog(env.AI, locale.code, source, locale.name)' in handler
    assert 'i18n-workers-ai-v2' in handler
    assert 'languageName' in engine
    assert 'BCP-47 locale ${locale}' in engine
    assert 'validCatalog(source, output)' in engine
    assert 'matchesConfiguredToken' in validation
