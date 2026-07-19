from collections import Counter
from pathlib import Path

from app.main import _origin_allowed, app


def test_runtime_cors_fallback_uses_exact_pages_origin_policy():
    assert _origin_allowed("https://agroai-portal.pages.dev") is True
    assert _origin_allowed("https://preview.agroai-command-center-v2-preview.pages.dev") is True
    assert _origin_allowed("https://agroai-portal-evil.pages.dev") is False
    assert _origin_allowed("https://evil-agroai-portal.pages.dev") is False
    assert _origin_allowed("https://agroai-portal.pages.dev.evil.test") is False


def test_streamed_upload_path_is_registered_once():
    counts = Counter(
        route.path
        for route in app.routes
        if getattr(route, "path", None) == "/v1/evidence/upload-stream"
    )
    assert counts["/v1/evidence/upload-stream"] == 1


def test_production_edge_owns_app_and_legacy_api_hostnames():
    wrangler = Path(__file__).resolve().parents[3] / "wrangler.toml"
    text = wrangler.read_text(encoding="utf-8")
    assert 'pattern = "app.agroai-pilot.com/v1/*"' in text
    assert 'pattern = "api.agroai-pilot.com/v1/*"' in text


def test_edge_deployment_keeps_queue_tokens_required_and_edge_auth_activation_gated():
    root = Path(__file__).resolve().parents[3]
    wrangler = (root / "wrangler.toml").read_text(encoding="utf-8")
    deploy = (root / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    required_line = next(line for line in wrangler.splitlines() if line.startswith("required ="))
    assert "QUEUE_PUBLISH_TOKEN" in required_line
    assert "QUEUE_CONSUMER_TOKEN" in required_line
    assert "EDGE_ORIGIN_AUTH_TOKEN" not in required_line
    assert (
        "for name in CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID "
        "QUEUE_PUBLISH_TOKEN QUEUE_CONSUMER_TOKEN; do"
    ) in deploy
    assert "platform_api_enabled == true" in deploy
    assert (
        'if [ "$platform_api_enabled" = "true" ] '
        '&& [ -z "${EDGE_ORIGIN_AUTH_TOKEN:-}" ]; then'
    ) in deploy
    assert 'if $edge_origin_auth == "" then {} else {EDGE_ORIGIN_AUTH_TOKEN: $edge_origin_auth} end' in deploy


def test_operation_production_proof_accepts_only_deployed_descendants_in_current_history():
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/operation-workspaces-production-contract.yml").read_text(
        encoding="utf-8"
    )

    assert 'git cat-file -e "${deployed_sha}^{commit}"' in workflow
    assert 'git merge-base --is-ancestor "$EXPECTED_FEATURE_SHA" "$deployed_sha"' in workflow
    assert 'git merge-base --is-ancestor "$deployed_sha" "$GITHUB_SHA"' in workflow
    assert ".build_sha == $sha" not in workflow
    assert "deployed_backend_sha" in workflow
    assert "operation-workspaces-production-v3" in workflow
