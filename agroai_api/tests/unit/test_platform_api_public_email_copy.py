from app.core.config import settings
from app.services import email_verification


def test_platform_verification_email_remains_private_beta_when_auto_enroll_is_off(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", False, raising=False)
    copy = email_verification._product_copy("platform_api")
    assert "private beta" in copy["intro"].lower()
    assert "reviewed api enrollment" in copy["footer"].lower()
    assert "no api-access review" not in copy["body"].lower()


def test_platform_verification_email_switches_to_test_self_service_only_when_launch_flag_is_on(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", True, raising=False)
    copy = email_verification._product_copy("platform_api")
    assert "private beta" not in copy["intro"].lower()
    assert "activate bounded test access" in copy["body"].lower()
    assert "do not need an api-access review" in copy["body"].lower()
    assert "live projects" in copy["body"].lower()
    assert "physical actions" in copy["body"].lower()
    assert "self-service test access" in copy["footer"].lower()


def test_enterprise_portal_email_copy_is_unchanged_by_platform_launch(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", True, raising=False)
    copy = email_verification._product_copy("enterprise_portal")
    assert copy["product"] == "AGRO-AI Enterprise Portal"
    assert "self-service" not in copy["body"].lower()
