from urllib.parse import parse_qs, urlsplit

from app.services.email_verification import _product_copy, verification_url
from app.services.verification_email_localization import localized_verification_copy, normalize_verification_locale


def test_brazilian_portuguese_resolves_to_enabled_portuguese_locale():
    assert normalize_verification_locale("pt-BR") == "pt"
    assert normalize_verification_locale("pt") == "pt"


def test_verification_link_carries_locale_across_browsers():
    parsed = urlsplit(verification_url("single-use-token", product_surface="enterprise_portal", locale="pt-BR"))
    query = parse_qs(parsed.query)
    assert query["token"] == ["single-use-token"]
    assert query["product"] == ["enterprise_portal"]
    assert query["locale"] == ["pt"]


def test_enterprise_verification_email_has_deterministic_brazilian_portuguese_copy():
    copy = localized_verification_copy("enterprise_portal", _product_copy("enterprise_portal"), "pt")
    assert copy["subject"] == "Confirme seu endereço de e-mail da AGRO-AI"
    assert copy["verify_button"] == "Verificar e-mail"
    assert "24 horas" in copy["expiry_notice"]
    assert "{product}" in copy["received_because"]
