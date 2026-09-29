import json
from pathlib import Path

from app.api.v1.billing import _STRIPE_SUPPORTED_LOCALES, stripe_checkout_locale

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = json.loads((ROOT / "shared" / "supported-locales.json").read_text(encoding="utf-8"))


def test_every_target_locale_resolves_to_a_valid_stripe_locale():
    for code in MANIFEST["targetUiLocales"]:
        resolved = stripe_checkout_locale(code)
        assert resolved == "auto" or resolved in _STRIPE_SUPPORTED_LOCALES, (code, resolved)


def test_regional_and_alias_mappings():
    assert stripe_checkout_locale("pt-BR") == "pt-BR"
    assert stripe_checkout_locale("pt") == "pt-BR"
    assert stripe_checkout_locale("fr-FR") == "fr"
    assert stripe_checkout_locale("tl") == "fil"
    assert stripe_checkout_locale("no") == "nb"
    assert stripe_checkout_locale("ja") == "ja"
    assert stripe_checkout_locale("zh") == "zh"
    assert stripe_checkout_locale("es") == "es"


def test_locales_stripe_does_not_offer_use_browser_resolution():
    for code in ("ar", "fa", "ur", "hi", "sw", "my", "am", "uk"):
        assert stripe_checkout_locale(code) == "auto"
    assert stripe_checkout_locale(None) == "auto"


def test_locale_event_endpoint_accepts_only_known_pii_free_events():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.api.v1.i18n import router

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    client = TestClient(app)
    ok = client.post("/v1/i18n/events", json={"event": "locale_switch_completed", "selectedLocale": "pt-BR", "effectiveLocale": "pt-BR", "latencyMs": 12})
    assert ok.status_code == 202
    assert client.post("/v1/i18n/events", json={"event": "user_email", "selectedLocale": "pt-BR", "effectiveLocale": "pt-BR"}).status_code == 422
    assert client.post("/v1/i18n/events", json={"event": "locale_fallback_triggered", "selectedLocale": "a@b.com", "effectiveLocale": "pt-BR"}).status_code == 422
