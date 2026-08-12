"""Device auth fails closed in production without a real hashing secret (item 7)."""
from app.core.config import settings
from app.platform_api.device_auth import device_auth_secret_ready
from app.api.v1.platform_api import platform_health


def test_secret_ready_is_true_when_feature_disabled(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    assert device_auth_secret_ready() is True


def test_secret_ready_is_true_in_non_production(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "APP_ENV", "development", raising=False)
    assert device_auth_secret_ready() is True


def test_production_default_secret_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(settings, "PLATFORM_API_KEY_PEPPER", "", raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "dev-secret-key-change-in-production-min-32-chars", raising=False)
    assert device_auth_secret_ready() is False
    # health reflects it and is not "ready"; the secret itself is not exposed.
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True, raising=False)
    h = platform_health()
    assert h["cli_device_auth"]["secret_ready"] is False
    assert h["status"] != "ready"
    assert "dev-secret" not in str(h)


def test_production_with_real_pepper_is_ready(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(settings, "PLATFORM_API_KEY_PEPPER", "a" * 48, raising=False)
    assert device_auth_secret_ready() is True
