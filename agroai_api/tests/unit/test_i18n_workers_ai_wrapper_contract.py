from pathlib import Path


def test_workers_ai_wrapper_keeps_backend_authority_and_fails_over_only_generation_503():
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "cloudflare" / "edge-gateway" / "src" / "production-wrapper.ts").read_text(encoding="utf-8")

    assert 'response.status !== 503' in source
    assert 'ui_catalog_generation_unavailable' in source
    assert 'ui_canary_generation_unavailable' in source
    assert 'request.clone()' in source
    assert 'validCatalog(source, output)' in source
    assert 'changedKeys.length < 2' in source
    assert 'providers: ["cloudflare_workers_ai"]' in source
