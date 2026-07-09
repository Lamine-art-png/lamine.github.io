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


def test_outreach_defaults_to_hd_16_9_launch_thumbnail(monkeypatch):
    monkeypatch.delenv("OUTREACH_LAUNCH_VIDEO_THUMBNAIL_URL", raising=False)
    from app.outreach.config import OutreachSettings

    settings = OutreachSettings.from_env()
    assert settings.launch_video_thumbnail_url.endswith("/maxresdefault.jpg")


def test_french_market_auto_routes_and_renders_fully_localized_email(monkeypatch):
    monkeypatch.setenv("OUTREACH_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_SECRET", "test-unsubscribe-secret")

    from app.outreach.config import OutreachSettings
    from app.outreach.schemas import OutreachProspect, VerificationStatus
    from app.outreach.templates import render_email

    prospect = OutreachProspect(
        prospect_id="fr-001",
        email="martin@example.fr",
        email_verification_status=VerificationStatus.verified_public_direct,
        first_name="Martin",
        person_name="Martin Dupont",
        title="Directeur des opérations",
        account="Ferme Exemple",
        country="France",
        segment="Enterprise Grower / Operator",
        observation="your team operates across several production sites",
        role_relevance="your role connects field execution and management decisions",
        pilot_wedge="unify operating evidence and unresolved actions across sites",
        why_now="The operating footprint is expanding.",
        localized_observation="votre équipe opère sur plusieurs sites de production",
        localized_role_relevance="votre rôle relie l’exécution terrain aux décisions de gestion",
        localized_pilot_wedge="unifier les preuves opérationnelles et les actions non résolues entre les sites",
        localized_why_now="Le périmètre opérationnel est en expansion.",
    )
    rendered = render_email(prospect, OutreachSettings.from_env(), unsubscribe_url="https://example.test/u")

    assert rendered.language == "fr"
    assert rendered.language_source == "country_market"
    assert rendered.localization_ready is True
    assert 'lang="fr"' in rendered.html
    assert "Commencer avec AGRO-AI" in rendered.html
    assert "votre équipe opère sur plusieurs sites de production" in rendered.html


def test_non_english_render_reports_not_ready_when_dynamic_copy_is_missing(monkeypatch):
    from app.outreach.config import OutreachSettings
    from app.outreach.schemas import OutreachProspect, VerificationStatus
    from app.outreach.templates import render_email

    prospect = OutreachProspect(
        prospect_id="es-001",
        email="buyer@example.es",
        email_verification_status=VerificationStatus.verified_public_direct,
        first_name="Lucia",
        person_name="Lucia Perez",
        title="Directora de operaciones",
        account="Agro Ejemplo",
        country="Spain",
        segment="Enterprise Grower / Operator",
        observation="your team operates across several production sites",
        pilot_wedge="unify operating evidence across sites",
    )
    rendered = render_email(prospect, OutreachSettings.from_env(), unsubscribe_url="https://example.test/u")

    assert rendered.language == "es"
    assert rendered.localization_ready is False


def test_arabic_explicit_override_renders_rtl(monkeypatch):
    from app.outreach.config import OutreachSettings
    from app.outreach.schemas import OutreachLanguage, OutreachProspect, VerificationStatus
    from app.outreach.templates import render_email

    prospect = OutreachProspect(
        prospect_id="ar-001",
        email="ops@example.com",
        email_verification_status=VerificationStatus.verified_public_direct,
        first_name="عمر",
        person_name="عمر أحمد",
        title="مدير العمليات",
        account="شركة زراعية",
        country="Global",
        segment="Enterprise Grower / Operator",
        preferred_language=OutreachLanguage.ar,
        observation="your team operates across several production sites",
        pilot_wedge="unify operating evidence across sites",
        localized_observation="فريقكم يعمل عبر عدة مواقع إنتاج",
        localized_pilot_wedge="توحيد الأدلة التشغيلية عبر المواقع",
    )
    rendered = render_email(prospect, OutreachSettings.from_env(), unsubscribe_url="https://example.test/u")

    assert rendered.language == "ar"
    assert rendered.language_source == "explicit_preference"
    assert rendered.localization_ready is True
    assert 'dir="rtl"' in rendered.html
