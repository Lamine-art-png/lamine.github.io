from pathlib import Path


def test_workers_ai_model_is_current_multilingual_cloudflare_hosted_model():
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "cloudflare" / "edge-gateway" / "src" / "production-wrapper.ts").read_text(encoding="utf-8")
    assert 'const MODEL = "@cf/zai-org/glm-4.7-flash"' in source
    assert 'max_completion_tokens: 4096' in source
    assert 'temperature: 0' in source
