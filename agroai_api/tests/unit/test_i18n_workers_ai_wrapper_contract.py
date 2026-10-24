from pathlib import Path


def test_workers_ai_fastpath_preserves_local_source_validation_and_internal_canary_auth():
    repo_root = Path(__file__).resolve().parents[3]
    entrypoint = (repo_root / "cloudflare" / "edge-gateway" / "src" / "edge-main-v3.ts").read_text(encoding="utf-8")
    handler = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-fastpath-handler.ts").read_text(encoding="utf-8")
    validation = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-edge-validation-v2.ts").read_text(encoding="utf-8")
    chunked_engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-workers-ai-v2.ts").read_text(encoding="utf-8")
    dedicated_engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-translation-engine-v3.ts").read_text(encoding="utf-8")
    public_fallback = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-public-translate-fallback.ts").read_text(encoding="utf-8")

    assert 'handleI18nFastpath' in entrypoint
    assert 'const I18N_EDGE_RELEASE = "provider-chain-v2"' in entrypoint
    assert 'x-agroai-i18n-release' in entrypoint
    assert 'canonicalRequestedSource' in handler
    assert 'if (!source)' in handler
    assert 'ui_source_catalog_mismatch' in handler
    assert 'canaryAuthorized(request, env.QUEUE_CONSUMER_TOKEN)' in handler
    assert 'matchesConfiguredToken' in validation
    assert 'validCatalog(source, output)' in chunked_engine
    assert 'validCatalog(source, output)' in dedicated_engine
    assert 'translateWithPublicFallback' in handler
    assert 'public_translation_provider_chain_v5' in public_fallback
    assert 'providers: [translated.provider]' in handler
    assert 'source: translated.provider' in handler
    assert 'changed.length < 2' in handler
