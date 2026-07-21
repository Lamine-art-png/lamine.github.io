from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request

from app.api.v1.auth import _verification_product_surface
from app.core.config import settings
from app.main import _origin_allowed, app
from app.services.email_verification import verification_url


def _auth_request(*, origin: str | None = None, referer: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if origin is not None:
        headers.append((b"origin", origin.encode("utf-8")))
    if referer is not None:
        headers.append((b"referer", referer.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/v1/auth/register",
            "raw_path": b"/v1/auth/register",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("api.agroai-pilot.com", 443),
        }
    )


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


def test_production_edge_owns_enterprise_platform_and_legacy_api_hostnames():
    wrangler = Path(__file__).resolve().parents[3] / "wrangler.toml"
    text = wrangler.read_text(encoding="utf-8")
    assert 'pattern = "app.agroai-pilot.com/v1/*"' in text
    assert 'pattern = "platform.agroai-pilot.com/v1/*"' in text
    assert 'pattern = "api.agroai-pilot.com/v1/*"' in text
    allowed = next(line for line in text.splitlines() if line.startswith("ALLOWED_ORIGINS ="))
    assert "https://platform.agroai-pilot.com" in allowed


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


def test_platform_custom_domain_smoke_is_explicitly_gated_and_recorded():
    root = Path(__file__).resolve().parents[3]
    deploy = (root / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert "PLATFORM_URL: https://platform.agroai-pilot.com" in deploy
    assert "PLATFORM_API_CUSTOM_DOMAIN_ENABLED" in deploy
    assert "Smoke standalone Platform product when custom domain is enabled" in deploy
    assert 'case "${PLATFORM_CUSTOM_DOMAIN_ENABLED,,}" in' in deploy
    assert "smoke skipped without claiming activation" in deploy
    assert 'curl --fail --silent --show-error --max-time 20 "${PLATFORM_URL}/v1/edge-health"' in deploy
    assert 'curl --fail --silent --show-error --max-time 30 "${PLATFORM_URL}/v1/health"' in deploy
    assert "Build on AGRO-AI." in deploy
    assert "Permanent API keys never enter browser JavaScript." in deploy
    assert 'echo "platform_custom_domain_enabled=${PLATFORM_CUSTOM_DOMAIN_ENABLED}"' in deploy


def test_platform_verification_release_contract_uses_only_first_party_surfaces(monkeypatch):
    assert (
        _verification_product_surface(
            _auth_request(origin="https://platform.agroai-pilot.com")
        )
        == "platform_api"
    )
    assert (
        _verification_product_surface(
            _auth_request(
                origin="https://app.agroai-pilot.com",
                referer="https://app.agroai-pilot.com/platform/projects",
            )
        )
        == "platform_api"
    )
    assert (
        _verification_product_surface(
            _auth_request(origin="https://platform.agroai-pilot.com.evil.test")
        )
        == "enterprise_portal"
    )

    monkeypatch.setattr(settings, "RESEND_APP_URL", "https://app.agroai-pilot.com")
    parsed = urlsplit(verification_url("release-proof-token", product_surface="platform_api"))
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "app.agroai-pilot.com"
    assert parsed.path == "/verify-email"
    assert query == {
        "token": ["release-proof-token"],
        "product": ["platform_api"],
    }
    assert not ({"return", "redirect", "redirect_uri", "next"} & set(query))


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
