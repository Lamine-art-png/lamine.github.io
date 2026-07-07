from pathlib import Path


def test_workers_ai_edge_fallback_is_bound_for_production_release():
    repo_root = Path(__file__).resolve().parents[3]
    wrangler = (repo_root / "wrangler.toml").read_text(encoding="utf-8")
    wrapper = (repo_root / "cloudflare" / "edge-gateway" / "src" / "production-wrapper.ts").read_text(encoding="utf-8")

    assert 'main = "cloudflare/edge-gateway/src/production-wrapper.ts"' in wrangler
    assert '[ai]' in wrangler
    assert 'binding = "AI"' in wrangler
    assert '@cf/zai-org/glm-4.7-flash' in wrapper
    assert 'ui_catalog_generation_unavailable' in wrapper
    assert 'ui_canary_generation_unavailable' in wrapper
    assert 'cloudflare_workers_ai' in wrapper
    assert 'PLACEHOLDER_RE' in wrapper
