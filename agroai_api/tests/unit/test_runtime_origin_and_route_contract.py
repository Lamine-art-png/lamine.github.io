from collections import Counter

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
