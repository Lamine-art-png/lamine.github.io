from pathlib import Path


def test_active_validation_fastpath_is_language_aware_and_nonblocking():
    repo_root = Path(__file__).resolve().parents[3]
    wrangler = (repo_root / "wrangler.toml").read_text(encoding="utf-8")
    entrypoint = (repo_root / "cloudflare" / "edge-gateway" / "src" / "edge-main-v3.ts").read_text(encoding="utf-8")
    handler = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-fastpath-handler.ts").read_text(encoding="utf-8")
    canonical = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-canonical-source.ts").read_text(encoding="utf-8")
    chunked_engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-workers-ai-v2.ts").read_text(encoding="utf-8")
    dedicated_engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-translation-engine-v3.ts").read_text(encoding="utf-8")
    validation = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-edge-validation-v2.ts").read_text(encoding="utf-8")

    assert "edge-main-v3.ts" in wrangler
    assert "handleI18nFastpath" in entrypoint
    assert "translationPaths" in entrypoint
    assert "DedicatedTranslationAdapter" not in entrypoint
    assert "localeManifest" in handler
    assert "canonicalRequestedSource" in handler
    assert "translateChunkedCatalog" in handler
    assert "translateDedicatedCatalog" in handler
    assert "englishValidationRequest" not in handler
    assert "canonicalRequestedSource" in canonical
    assert "CHUNK_SIZE" in chunked_engine
    assert "MAX_PARALLEL" in chunked_engine
    assert "source_lang" in dedicated_engine
    assert "target_lang" in dedicated_engine
    assert "CALL_TIMEOUT_MS" in dedicated_engine
    assert "validCatalog(source, output)" in dedicated_engine
    assert "matchesConfiguredToken" in validation
