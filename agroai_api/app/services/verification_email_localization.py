from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import User, UserPreference
from app.services.language_registry import enabled_ui_locales, family_name, locale_specs, normalize_bcp47
from app.services.model_router import ModelRouter

logger = logging.getLogger(__name__)

_COPY_CACHE: dict[tuple[str, str, bool], dict[str, str]] = {}


def normalize_verification_locale(value: str | None) -> str:
    requested = normalize_bcp47(value)
    enabled = tuple(code for code in enabled_ui_locales() if code != "auto")
    enabled_lower = {code.lower(): code for code in enabled}
    exact = enabled_lower.get(requested.lower())
    if exact:
        return exact

    spec = locale_specs().get(requested.lower())
    if spec:
        for fallback in spec.fallback_chain:
            resolved = enabled_lower.get(str(fallback).lower())
            if resolved:
                return resolved

    root = requested.split("-", 1)[0].lower()
    for code in enabled:
        candidate = locale_specs().get(code.lower())
        if candidate and candidate.language_code == root:
            return code
    return "en"


def preferred_verification_locale(db: Session, user: User, requested: str | None = None) -> str:
    if requested:
        return normalize_verification_locale(requested)
    try:
        preference = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
        if preference and preference.locale:
            return normalize_verification_locale(preference.locale)
    except Exception:
        logger.exception("Could not load verification locale preference for user_id=%s", getattr(user, "id", None))
    return "en"


def _email_chrome(copy: dict[str, str]) -> dict[str, str]:
    return {
        **copy,
        "verify_button": "Verify email",
        "fallback_instruction": "If the button does not work, copy and paste this link into your browser:",
        "expiry_notice": "This verification link expires in 24 hours. If you did not create this account, you can safely ignore this email.",
        "received_because": "You received this email because a {product} account flow was started with this address.",
        "open_link": "Open this link:",
        "expires_short": "This link expires in 24 hours.",
    }


def _portuguese_copy(product_surface: str) -> dict[str, str]:
    if product_surface == "platform_api":
        public_self_service = bool(getattr(settings, "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", False))
        body = (
            "Após a verificação, entre na sua conta para revisar os acordos atuais de desenvolvedor e ativar o acesso TESTE limitado. Projetos LIVE, provedores de produção, faturamento, webhooks de produção e ações físicas continuam controlados separadamente."
            if public_self_service
            else "Após a verificação, volte ao aplicativo da API da Plataforma. Inscrição na API, projetos de teste, chaves, acesso ao ambiente LIVE, faturamento, provedores e ações físicas continuam controlados separadamente."
        )
        return {
            "product": "API da Plataforma AGRO-AI",
            "headline": "Confirme sua conta de desenvolvedor",
            "intro": "Confirme seu e-mail para ativar a conta verificada da organização AGRO-AI usada pela API da Plataforma.",
            "body": body,
            "footer": "Conta verificada · acesso controlado à API",
            "subject": "Confirme sua conta da API da Plataforma AGRO-AI",
            "verify_button": "Verificar e-mail",
            "fallback_instruction": "Se o botão não funcionar, copie e cole este link no seu navegador:",
            "expiry_notice": "Este link de verificação expira em 24 horas. Se você não criou esta conta, pode ignorar este e-mail com segurança.",
            "received_because": "Você recebeu este e-mail porque um fluxo de conta do {product} foi iniciado com este endereço.",
            "open_link": "Abra este link:",
            "expires_short": "Este link expira em 24 horas.",
        }

    return {
        "product": "Portal Empresarial AGRO-AI",
        "headline": "Confirme seu endereço de e-mail",
        "intro": "Ative o acesso seguro ao seu espaço de trabalho no Portal Empresarial AGRO-AI.",
        "body": "Obrigado por criar uma conta AGRO-AI. Para ativar seu espaço de trabalho, confirme seu endereço de e-mail.",
        "footer": "AGRO-AI · Espaço seguro de inteligência agrícola",
        "subject": "Confirme seu endereço de e-mail da AGRO-AI",
        "verify_button": "Verificar e-mail",
        "fallback_instruction": "Se o botão não funcionar, copie e cole este link no seu navegador:",
        "expiry_notice": "Este link de verificação expira em 24 horas. Se você não criou esta conta, pode ignorar este e-mail com segurança.",
        "received_because": "Você recebeu este e-mail porque um fluxo de conta do {product} foi iniciado com este endereço.",
        "open_link": "Abra este link:",
        "expires_short": "Este link expira em 24 horas.",
    }


def localized_verification_copy(product_surface: str, base_copy: dict[str, str], locale: str) -> dict[str, str]:
    canonical = normalize_verification_locale(locale)
    base = _email_chrome(base_copy)
    if canonical == "en":
        return base
    if canonical == "pt":
        return _portuguese_copy(product_surface)

    cache_key = (
        canonical,
        product_surface,
        bool(getattr(settings, "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", False)),
    )
    cached = _COPY_CACHE.get(cache_key)
    if cached:
        return dict(cached)

    language = family_name(canonical)
    messages = [
        {
            "role": "system",
            "content": (
                f"Translate every JSON string value into {language} ({canonical}) for a professional AGRO-AI account-verification email. "
                "Return one JSON object only. Preserve every key exactly. Preserve AGRO-AI, TEST, LIVE, URLs, and the {product} placeholder exactly. "
                "Do not add claims or explanations."
            ),
        },
        {"role": "user", "content": json.dumps(base, ensure_ascii=False, separators=(",", ":"))},
    ]

    try:
        async def run_translation():
            router = ModelRouter()
            return await router.run(
                task="ui_translation",
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=1800,
                timeout_seconds=6,
                max_model_attempts=1,
            )

        result, _selection = asyncio.run(run_translation())
        if result.status != "ok" or not result.content.strip():
            raise ValueError(result.error or "translation unavailable")
        payload = json.loads(result.content)
        if set(payload) != set(base):
            raise ValueError("translated verification email keys do not match source")
        translated: dict[str, str] = {}
        for key in base:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"invalid translated verification value for {key}")
            translated[key] = value.strip()
        if "{product}" not in translated["received_because"]:
            raise ValueError("translated verification email lost product placeholder")
        _COPY_CACHE[cache_key] = translated
        return dict(translated)
    except Exception as exc:
        logger.warning("Verification email translation unavailable locale=%s: %s", canonical, exc)
        return base
