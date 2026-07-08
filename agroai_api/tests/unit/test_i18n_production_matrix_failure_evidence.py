from pathlib import Path


def test_workers_ai_validation_fastpath_is_bound_for_production_release():
    repo_root = Path(__file__).resolve().parents[3]
    wrangler = (repo_root / "wrangler.toml").read_text(encoding="utf-8")
    entrypoint = (repo_root / "cloudflare" / "edge-gateway" / "src" / "edge-main-v3.ts").read_text(encoding="utf-8")
    handler = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-fastpath-handler.ts").read_text(encoding="utf-8")
    canonical = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-canonical-source.ts").read_text(encoding="utf-8")
    chunked_engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-workers-ai-v2.ts").read_text(encoding="utf-8")
    dedicated_engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-translation-engine-v3.ts").read_text(encoding="utf-8")

    assert 'main = "cloudflare/edge-gateway/src/edge-main-v3.ts"' in wrangler
    assert '[ai]' in wrangler
    assert 'binding = "AI"' in wrangler
    assert 'handleI18nFastpath' in entrypoint
    assert 'DedicatedTranslationAdapter' not in entrypoint
    assert 'translateChunkedCatalog' in handler
    assert 'translateDedicatedCatalog' in handler
    assert 'localeManifest' in handler
    assert 'canonicalRequestedSource' in handler
    assert 'englishValidationRequest' not in handler
    assert 'cloudflare_workers_ai' in handler
    assert 'I18N_EDGE_GENERATION_TIMEOUT_MS = 12_000' in handler
    assert 'I18N_UPSTREAM_TIMEOUT_MS = 30_000' in handler
    assert 'edge_i18n_generation_timeout' in handler
    assert 'ui-commercial-boundary.en.json' in canonical
    assert '@cf/zai-org/glm-4.7-flash' in chunked_engine
    assert '@cf/meta/m2m100-1.2b' in dedicated_engine
    assert 'CALL_TIMEOUT_MS' in dedicated_engine
    assert 'PLACEHOLDER_RE' in dedicated_engine
