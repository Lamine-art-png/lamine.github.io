"""Portal-first cold outreach renderer for the production AGRO-AI sender.

Lifecycle and warm re-engagement messages remain owned by the legacy renderer.
This module only replaces cold outreach with a concise Enterprise Portal case,
one supporting Field Intelligence sentence, and a compact button-only action card.
"""
from __future__ import annotations

from html import escape

from . import templates as legacy
from .config import OutreachSettings
from .localization import OutreachLanguage, locale_for, resolve_language, segment_copy
from .schemas import OutreachMessageType, OutreachProspect


_FIELD_INTELLIGENCE: dict[OutreachLanguage, str] = {
    OutreachLanguage.en: (
        "Field Intelligence makes capture immediate: a team member can speak an update from the field, "
        "attach photographs and location, and the Portal turns it into structured records, owned work, and follow-through."
    ),
    OutreachLanguage.fr: (
        "Field Intelligence rend la collecte immédiate : un membre de l’équipe peut dicter une mise à jour depuis le terrain, "
        "joindre des photos et la localisation, puis le Portail la transforme en dossiers structurés, actions attribuées et suivi."
    ),
    OutreachLanguage.es: (
        "Field Intelligence hace que la captura sea inmediata: un miembro del equipo puede dictar una actualización desde el campo, "
        "adjuntar fotografías y ubicación, y el Portal la convierte en registros estructurados, trabajo asignado y seguimiento."
    ),
    OutreachLanguage.pt: (
        "O Field Intelligence torna o registro imediato: um membro da equipe pode ditar uma atualização no campo, "
        "anexar fotografias e localização, e o Portal a transforma em registros estruturados, trabalho atribuído e acompanhamento."
    ),
    OutreachLanguage.ar: (
        "تجعل ميزة Field Intelligence توثيق العمل فوريًا: يمكن لأحد أعضاء الفريق إملاء تحديث من الميدان وإرفاق الصور والموقع، "
        "ثم تحوّله البوابة إلى سجلات منظمة وأعمال مسندة ومتابعة واضحة."
    ),
}

_DIRECT_REVIEW: dict[OutreachLanguage, str] = {
    OutreachLanguage.en: "I would like to show you how that workflow would run inside the AGRO-AI Enterprise Portal.",
    OutreachLanguage.fr: "Je souhaite vous montrer comment ce flux fonctionnerait dans le Portail d’entreprise AGRO-AI.",
    OutreachLanguage.es: "Quiero mostrarle cómo funcionaría ese flujo dentro del Portal Empresarial de AGRO-AI.",
    OutreachLanguage.pt: "Quero mostrar como esse fluxo funcionaria dentro do Portal Empresarial da AGRO-AI.",
    OutreachLanguage.ar: "أود أن أعرض عليكم كيف سيعمل هذا المسار داخل بوابة AGRO-AI للمؤسسات.",
}

_ACTION_COPY: dict[OutreachLanguage, tuple[str, str, str, str]] = {
    OutreachLanguage.en: (
        "Review the AGRO-AI Enterprise Portal",
        "Open the Enterprise Portal",
        "View the Portal demo",
        "Book a workflow review",
    ),
    OutreachLanguage.fr: (
        "Découvrir le Portail d’entreprise AGRO-AI",
        "Ouvrir le Portail d’entreprise",
        "Voir la démonstration du Portail",
        "Réserver une revue du flux",
    ),
    OutreachLanguage.es: (
        "Revisar el Portal Empresarial de AGRO-AI",
        "Abrir el Portal Empresarial",
        "Ver la demostración del Portal",
        "Reservar una revisión del flujo",
    ),
    OutreachLanguage.pt: (
        "Conhecer o Portal Empresarial da AGRO-AI",
        "Abrir o Portal Empresarial",
        "Ver a demonstração do Portal",
        "Agendar uma revisão do fluxo",
    ),
    OutreachLanguage.ar: (
        "استعراض بوابة AGRO-AI للمؤسسات",
        "فتح بوابة المؤسسات",
        "عرض توضيحي للبوابة",
        "حجز مراجعة لسير العمل",
    ),
}


def _language_copy(mapping: dict[OutreachLanguage, object], language: OutreachLanguage):
    return mapping.get(language, mapping[OutreachLanguage.en])


def _cold_outreach(
    prospect: OutreachProspect,
    settings: OutreachSettings,
    *,
    unsubscribe_url: str,
) -> legacy.RenderedEmail:
    resolution = resolve_language(prospect.preferred_language, prospect.country)
    language = resolution.language
    locale = locale_for(language)
    _, portal_paragraph = segment_copy(language, prospect.segment)
    subject = legacy._subject(prospect, language)
    greeting = legacy._greeting(prospect, language)
    ready = legacy.localization_ready(prospect, language)

    observation_raw, relevance_raw, wedge_raw, why_now_raw = legacy._dynamic_copy(prospect, language)
    observation = legacy._sentence(observation_raw)
    relevance = legacy._sentence(relevance_raw)
    wedge = legacy._sentence(wedge_raw)
    why_now = legacy._sentence(why_now_raw)
    relevance_sentence = f" {relevance}" if relevance else ""
    reaching_out = locale.reaching_out.format(observation=observation, relevance=relevance_sentence)
    workflow_prefix = locale.workflow_prefix.format(account=prospect.account)
    field_intelligence = str(_language_copy(_FIELD_INTELLIGENCE, language))
    direct_review = str(_language_copy(_DIRECT_REVIEW, language))
    action_heading, portal_cta, demo_cta, meeting_cta = _language_copy(_ACTION_COPY, language)

    text_parts = [
        greeting,
        "",
        locale.intro,
        "",
        reaching_out,
        "",
    ]
    if why_now:
        text_parts.extend([why_now, ""])
    text_parts.extend(
        [
            portal_paragraph,
            "",
            field_intelligence,
            "",
            f"{workflow_prefix} {wedge}",
            "",
            direct_review,
            "",
            action_heading,
            f"{portal_cta}: {settings.enterprise_portal_url}",
            f"{demo_cta}: {settings.live_demo_url}",
            f"{meeting_cta}: {settings.calendly_url}",
            "",
            locale.signoff,
            "Lamine Dabo",
            locale.founder_title,
            "San Francisco, California",
            "",
            f"AGRO-AI Inc. · {settings.company_address.replace('AGRO-AI Inc., ', '')}",
            f"{locale.footer_unsubscribe}: {unsubscribe_url}",
        ]
    )
    text = "\n".join(text_parts)

    why_now_html = f'<p style="margin:0 0 16px 0;">{escape(why_now)}</p>' if why_now else ""
    text_align = "right" if locale.direction == "rtl" else "left"

    html = f"""<!doctype html>
<html lang="{escape(locale.html_lang, quote=True)}" dir="{escape(locale.direction, quote=True)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f5f7f6;color:#17211c;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f7f6;"><tr><td align="center" style="padding:28px 14px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:660px;background:#ffffff;border:1px solid #e7ebe8;border-radius:12px;overflow:hidden;">
<tr><td style="height:5px;background:#176b45;font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td dir="{escape(locale.direction, quote=True)}" style="padding:32px 38px 28px;font-size:16px;line-height:1.58;color:#202a24;text-align:{text_align};">
<p style="margin:0 0 16px 0;">{escape(greeting)}</p>
<p style="margin:0 0 16px 0;">{escape(locale.intro)}</p>
<p style="margin:0 0 16px 0;">{escape(reaching_out)}</p>
{why_now_html}
<p style="margin:0 0 16px 0;">{escape(portal_paragraph)}</p>
<p style="margin:0 0 16px 0;">{escape(field_intelligence)}</p>
<p style="margin:0 0 16px 0;"><strong>{escape(workflow_prefix)}</strong> {escape(wedge)}</p>
<p style="margin:0 0 22px 0;">{escape(direct_review)}</p>

<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;margin:0 0 24px 0;background:#f3f7f4;border:1px solid #dce6df;border-radius:10px;">
<tr><td style="padding:20px;">
<p style="margin:0 0 14px 0;font-size:14px;line-height:1.4;font-weight:700;color:#1b3024;">{escape(str(action_heading))}</p>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
<tr><td style="padding:0 0 10px 0;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="display:block;padding:13px 18px;border-radius:7px;background:#176b45;color:#ffffff;text-align:center;text-decoration:none;font-size:14px;font-weight:700;">{escape(str(portal_cta))}</a></td></tr>
<tr><td style="padding:0 0 10px 0;"><a href="{escape(settings.live_demo_url, quote=True)}" style="display:block;padding:12px 18px;border-radius:7px;background:#111814;color:#ffffff;text-align:center;text-decoration:none;font-size:14px;font-weight:700;">{escape(str(demo_cta))}</a></td></tr>
<tr><td><a href="{escape(settings.calendly_url, quote=True)}" style="display:block;padding:12px 18px;border-radius:7px;background:#ffffff;border:1px solid #176b45;color:#176b45;text-align:center;text-decoration:none;font-size:14px;font-weight:700;">{escape(str(meeting_cta))}</a></td></tr>
</table>
</td></tr></table>

<p style="margin:0;">{escape(locale.signoff)}</p>
<p style="margin:4px 0 0;font-weight:700;color:#111814;">Lamine Dabo</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">{escape(locale.founder_title)}</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">San Francisco, California</p>
</td></tr>
<tr><td style="padding:22px 38px 24px;background:#f3f5f4;border-top:1px solid #e2e7e4;text-align:center;color:#7a857e;font-size:12px;line-height:1.55;">
<div style="font-weight:700;color:#566159;margin-bottom:6px;">AGRO-AI Inc.</div>
<div>{escape(settings.company_address.replace('AGRO-AI Inc., ', ''))}</div>
<div style="margin-top:9px;"><a href="{escape(unsubscribe_url, quote=True)}" style="color:#6e7a72;text-decoration:underline;">{escape(locale.footer_unsubscribe)}</a></div>
<div style="margin-top:9px;color:#98a19b;">{escape(locale.footer_reason)}</div>
</td></tr></table></td></tr></table>
</body></html>"""

    return legacy.RenderedEmail(
        subject=subject,
        html=html,
        text=text,
        unsubscribe_url=unsubscribe_url,
        language=language.value,
        language_source=resolution.source,
        language_confidence=resolution.confidence,
        localization_ready=ready,
    )


def render_email(
    prospect: OutreachProspect,
    settings: OutreachSettings,
    *,
    unsubscribe_url: str,
) -> legacy.RenderedEmail:
    if prospect.message_type != OutreachMessageType.cold_outreach:
        return legacy.render_email(prospect, settings, unsubscribe_url=unsubscribe_url)
    return _cold_outreach(prospect, settings, unsubscribe_url=unsubscribe_url)


__all__ = ["render_email"]
