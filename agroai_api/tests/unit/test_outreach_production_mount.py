from __future__ import annotations

import importlib


def test_production_app_mounts_outreach_status_route(monkeypatch):
    monkeypatch.setenv("OUTREACH_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_SECRET", "test-unsubscribe-secret")
    monkeypatch.setenv("OUTREACH_RESEND_API_KEY", "re_test_outreach")

    main = importlib.import_module("app.main")
    paths = {getattr(route, "path", "") for route in main.app.routes}

    assert "/v1/outreach/status" in paths
    assert "/v1/outreach/preview" in paths
    assert "/v1/outreach/send" in paths
    assert "/v1/outreach/batch" in paths


def test_outreach_uses_dedicated_resend_key_name(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_transactional")
    monkeypatch.setenv("OUTREACH_RESEND_API_KEY", "re_outreach")

    from app.outreach.config import OutreachSettings

    settings = OutreachSettings.from_env()
    assert settings.resend_api_key == "re_outreach"


def test_outreach_defaults_to_dry_run(monkeypatch):
    monkeypatch.delenv("OUTREACH_DRY_RUN", raising=False)
    from app.outreach.config import OutreachSettings

    assert OutreachSettings.from_env().dry_run is True
