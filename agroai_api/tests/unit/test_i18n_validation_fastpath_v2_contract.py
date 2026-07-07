from pathlib import Path


def test_active_local_validation_fastpath_is_language_aware_and_nonblocking():
    repo_root = Path(__file__).resolve().parents[3]
    wrangler = (repo_root / "wrangler.toml").read_text(encoding="utf-8")
    entrypoint = (repo_root / "cloudflare" / "edge-gateway" / "src" / "edge-main-v3.ts").read_text(encoding="utf-8")
    handler = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-fastpath-handler.ts").read_text(encoding="utf-8")
    engine = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-translation-engine-v3.ts").read_text(encoding="utf-8")
    validation = (repo_root / "cloudflare" / "edge-gateway" / "src" / "i18n-edge-validation-v2.ts").read_text(encoding="utf-8")

    assert "edge-main-v3.ts" in wrangler
    assert "handleI18nFastpath" in entrypoint
    assert "i18n-translation-engine-v3" in handler
    assert "translateChunkedCatalog" in handler
    assert "translateDedicatedCatalog" in handler
    assert "canonicalRequestedSource" in handler
    assert "ui_source_catalog_mismatch" in handler
    assert "canaryAuthorized" in handler
    assert "source_lang" in engine
    assert "target_lang" in engine
    assert "CALL_TIMEOUT_MS" in engine
    assert "validCatalog(source, output)" in engine
    assert "matchesConfiguredToken" in validation
