from pathlib import Path


def test_workers_ai_wrapper_reports_actual_model_identity():
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "cloudflare" / "ollama-compat" / "src" / "index.js").read_text(encoding="utf-8")

    assert 'provider: "cloudflare-workers-ai"' in source
    assert "model: env.MODEL" in source
    assert "requested_model: body.model ?? null" in source
    assert "model: body.model ?? env.MODEL" not in source


def test_edge_and_local_runtime_settings_are_separate():
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "agroai_api" / "app" / "core" / "config.py").read_text(encoding="utf-8")

    assert 'AI_LOCAL_BASE_URL: str = ""' in source
    assert 'AI_EDGE_BASE_URL: str = ""' in source
    assert 'AI_EDGE_MODEL: str = "@cf/zai-org/glm-4.7-flash"' in source
