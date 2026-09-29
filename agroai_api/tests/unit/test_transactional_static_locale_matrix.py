"""Every advertised locale must render customer emails from its deterministic
catalog. A None from the static path would mean live model generation (or an
English fallback) on a security-critical email."""
from app.services.credential_recovery import _english_copy as recovery_english
from app.services.email_verification import _english_product_copy, verification_url
from app.services.language_registry import enabled_ui_locales
from app.services.static_transactional_i18n import localize_static_transactional_strings


def _advertised():
    return [code for code in enabled_ui_locales() if code not in ("auto", "en")]


def test_advertised_locales_render_verification_and_recovery_statically():
    locales = _advertised()
    assert "pt-BR" in locales
    for locale in locales:
        for surface in ("enterprise_portal", "platform_api"):
            english = _english_product_copy(surface)
            localized = localize_static_transactional_strings(locale, english)
            assert localized is not None, (locale, surface)
            assert localized.keys() == english.keys()
            changed = sum(1 for key in english if localized[key] != english[key])
            assert changed >= len(english) // 2, (locale, surface, changed)
        recovery = localize_static_transactional_strings(locale, recovery_english())
        assert recovery is not None, (locale, "recovery")


def test_verification_link_carries_the_advertised_locale():
    for locale in _advertised():
        assert f"lang={locale}" in verification_url("t", locale=locale)
