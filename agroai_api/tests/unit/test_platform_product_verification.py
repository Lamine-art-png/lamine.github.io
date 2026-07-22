from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request

from app.api.v1.auth import _verification_product_surface
from app.core.config import settings
from app.services.email_verification import (
    _product_copy,
    normalize_product_surface,
    verification_base_url,
    verification_url,
)


def _request(*, origin: str | None = None, referer: str | None = None) -> Request:
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


def test_exact_standalone_origin_selects_platform_verification_ux():
    assert (
        _verification_product_surface(
            _request(origin="https://platform.agroai-pilot.com")
        )
        == "platform_api"
    )


def test_controlled_app_platform_path_selects_platform_verification_ux():
    request = _request(
        origin="https://app.agroai-pilot.com",
        referer="https://app.agroai-pilot.com/platform/api-keys",
    )
    assert _verification_product_surface(request) == "platform_api"


def test_verification_product_classification_rejects_lookalikes_and_untrusted_referrers():
    assert (
        _verification_product_surface(
            _request(origin="https://platform.agroai-pilot.com.evil.test")
        )
        == "enterprise_portal"
    )
    assert (
        _verification_product_surface(
            _request(
                origin="https://app.agroai-pilot.com",
                referer="https://app.agroai-pilot.com.evil.test/platform",
            )
        )
        == "enterprise_portal"
    )
    assert (
        _verification_product_surface(
            _request(
                origin="https://app.agroai-pilot.com",
                referer="https://evil.test/platform",
            )
        )
        == "enterprise_portal"
    )
    assert (
        _verification_product_surface(
            _request(
                origin="https://app.agroai-pilot.com",
                referer="not a valid URL",
            )
        )
        == "enterprise_portal"
    )


def test_verification_url_uses_only_the_trusted_app_origin(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "RESEND_APP_URL", "https://app.agroai-pilot.com")
    monkeypatch.setattr(settings, "APP_URL", "https://app.agroai-pilot.com")

    parsed = urlsplit(verification_url("single-use-token", product_surface="platform_api"))
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "app.agroai-pilot.com"
    assert parsed.path == "/verify-email"
    assert query == {"token": ["single-use-token"], "product": ["platform_api"]}
    assert "return" not in query
    assert "redirect" not in query
    assert "next" not in query


def test_production_verification_origin_fails_closed_on_external_or_lookalike_configuration(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "APP_URL", "https://app.agroai-pilot.com")

    for candidate in (
        "https://evil.test",
        "https://app.agroai-pilot.com.evil.test",
        "https://user@app.agroai-pilot.com",
        "https://app.agroai-pilot.com/redirect",
        "javascript:alert(1)",
    ):
        monkeypatch.setattr(settings, "RESEND_APP_URL", candidate)
        assert verification_base_url() == "https://app.agroai-pilot.com"
        parsed = urlsplit(verification_url("single-use-token", product_surface="platform_api"))
        assert parsed.scheme == "https"
        assert parsed.netloc == "app.agroai-pilot.com"
        assert parsed.path == "/verify-email"


def test_loopback_verification_origin_is_allowed_only_for_local_environments(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "RESEND_APP_URL", "http://localhost:5173/")
    assert verification_base_url() == "http://localhost:5173"

    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert verification_base_url() == "https://app.agroai-pilot.com"


def test_invalid_product_marker_falls_back_to_enterprise_without_redirect_surface(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "RESEND_APP_URL", "https://app.agroai-pilot.com")

    assert normalize_product_surface("https://evil.test/platform") == "enterprise_portal"
    parsed = urlsplit(
        verification_url(
            "single-use-token",
            product_surface="https://evil.test/platform",
        )
    )
    query = parse_qs(parsed.query)
    assert parsed.netloc == "app.agroai-pilot.com"
    assert query["product"] == ["enterprise_portal"]


def test_platform_verification_copy_preserves_separate_enrollment_boundary():
    copy = _product_copy("platform_api")
    combined = " ".join(copy.values()).lower()

    assert copy["subject"] == "Confirm your AGRO-AI Platform API account"
    assert "platform api" in combined
    assert "separate" in combined or "separately" in combined
    assert "enrollment" in combined
    assert "test projects" in combined
    assert "live access" in combined
    assert "physical actions" in combined


def test_enterprise_verification_copy_remains_available():
    copy = _product_copy("enterprise_portal")
    assert copy["product"] == "AGRO-AI Enterprise Portal"
    assert "Enterprise Portal" in copy["intro"]
