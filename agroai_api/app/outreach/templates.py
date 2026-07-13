"""Professional personalized multilingual AGRO-AI outreach rendering."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

from .config import OutreachSettings
from .localization import LanguageResolution, OutreachLanguage, locale_for, resolve_language, segment_copy
from .schemas import OutreachMessageType, OutreachProspect, VerificationStatus


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    html: str
    text: str
    unsubscribe_url: str
    language: str
    language_source: str
    language_confidence: str
    localization_ready: bool


def _sentence(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    if clean.endswith((".", "!", "?", "؟", "。")):
        return clean
    return clean + "."


def localization_ready(prospect: OutreachProspect, language: OutreachLanguage) -> bool:
    """Require fully localized dynamic personalization for non-English live sends."""
    if prospect.message_type in {
        OutreachMessageType.post_signup_founder_followup,
        OutreachMessageType.warm_buyer_reengagement,
    }:
        # These relationship-aware templates currently ship as English founder
        # emails. Non-English delivery remains blocked until dedicated localized
        # versions exist, preventing mixed-language customer communications.
        return language == OutreachLanguage.en
    if language == OutreachLanguage.en:
        return True
    if not prospect.localized_observation or not prospect.localized_pilot_wedge:
        return False
    if prospect.role_relevance and not prospect.localized_role_relevance:
        return False
    if prospect.why_now and not prospect.localized_why_now:
        return False
    if prospect.subject and not prospect.localized_subject:
        return False
    return True


def _dynamic_copy(prospect: OutreachProspect, language: OutreachLanguage) -> tuple[str, str, str, str]:
    if language == OutreachLanguage.en:
        return prospect.observation, prospect.role_relevance, prospect.pilot_wedge, prospect.why_now
    return (
        prospect.localized_observation or prospect.observation,
        prospect.localized_role_relevance or prospect.role_relevance,
        prospect.localized_pilot_wedge or prospect.pilot_wedge,
        prospect.localized_why_now or prospect.why_now,
    )


def _default_subject(prospect: OutreachProspect, language: OutreachLanguage) -> str:
    locale = locale_for(language)
    lower = prospect.segment.lower()
    if "water" in lower or "district" in lower or "agency" in lower:
        return locale.subject_water.format(account=prospect.account)
    if "institutional" in lower or "asset manager" in lower or "farmland" in lower:
        return locale.subject_assets.format(account=prospect.account)
    return locale.subject_operations.format(account=prospect.account)


def _subject(prospect: OutreachProspect, language: OutreachLanguage) -> str:
    if language == OutreachLanguage.en:
        return (prospect.subject or _default_subject(prospect, language)).strip()
    return (prospect.localized_subject or _default_subject(prospect, language)).strip()


def _greeting(prospect: OutreachProspect, language: OutreachLanguage) -> str:
    locale = locale_for(language)
    if prospect.email_verification_status == VerificationStatus.verified_public_role:
        return locale.team_greeting.format(account=prospect.account)
    return locale.individual_greeting.format(first_name=prospect.first_name)


def _render_post_signup_founder_followup(
    prospect: OutreachProspect,
    settings: OutreachSettings,
    *,
    unsubscribe_url: str,
    resolution: LanguageResolution,
) -> RenderedEmail:
    language = resolution.language
    locale = locale_for(language)
    subject = (prospect.subject or f"Thanks for signing up, {prospect.first_name}").strip()
    greeting = locale.individual_greeting.format(first_name=prospect.first_name)
    ready = localization_ready(prospect, language)
    context = prospect.signup_interest_context.strip()

    thanks = f"Thanks for creating an AGRO-AI workspace for {prospect.account}. I noticed the signup and wanted to reach out personally."
    dive_in = (
        "You are welcome to dive straight in and test the platform on your own. "
        "If useful, I would also be happy to spend 30 minutes with you, hear what caught your attention, "
        "and walk through a concrete workflow together — no generic sales deck."
    )
    closing = (
        "Either way, I would genuinely value hearing what made you sign up. "
        "That context would help me point you toward the most relevant part of the platform."
    )

    text = "\n".join(
        [
            greeting,
            "",
            thanks,
            "",
            context,
            "",
            dive_in,
            "",
            "Open your AGRO-AI workspace:",
            settings.enterprise_portal_url,
            "",
            "Prefer to talk first? Book 30 minutes with me:",
            settings.calendly_url,
            "",
            closing,
            "",
            locale.launch_video_label,
            settings.launch_video_url,
            "",
            locale.signoff,
            "Lamine Dabo",
            locale.founder_title,
            "San Francisco, California",
            settings.website_url,
            "",
            f"AGRO-AI Inc. · {settings.company_address.replace('AGRO-AI Inc., ', '')}",
            f"{locale.footer_unsubscribe}: {unsubscribe_url}",
        ]
    )

    html = f"""<!doctype html>
<html lang="{escape(locale.html_lang, quote=True)}" dir="{escape(locale.direction, quote=True)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f5f7f6;color:#17211c;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f7f6;"><tr><td align="center" style="padding:28px 14px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:660px;background:#fff;border:1px solid #e7ebe8;border-radius:12px;overflow:hidden;">
<tr><td style="height:5px;background:#176b45;font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td style="padding:34px 38px 30px;font-size:16px;line-height:1.62;color:#202a24;text-align:left;">
<p style="margin:0 0 18px;">{escape(greeting)}</p>
<p style="margin:0 0 18px;">{escape(thanks)}</p>
<p style="margin:0 0 18px;">{escape(context)}</p>
<p style="margin:0 0 18px;">{escape(dive_in)}</p>
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 18px;"><tr><td style="border-radius:7px;background:#176b45;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="display:inline-block;padding:13px 19px;color:#fff;text-decoration:none;font-size:14px;font-weight:700;">Open your AGRO-AI workspace</a></td></tr></table>
<p style="margin:0 0 18px;color:#5f6b63;font-size:14px;">Prefer to talk first? <a href="{escape(settings.calendly_url, quote=True)}" style="color:#176b45;text-decoration:underline;">Book 30 minutes with me</a>.</p>
<p style="margin:0 0 22px;">{escape(closing)}</p>
<a href="{escape(settings.launch_video_url, quote=True)}" style="display:block;text-decoration:none;margin:0 0 24px;"><img src="{escape(settings.launch_video_thumbnail_url, quote=True)}" width="584" height="329" alt="{escape(locale.launch_alt, quote=True)}" style="display:block;width:100%;max-width:584px;height:auto;aspect-ratio:16/9;object-fit:cover;border:0;border-radius:9px;"></a>
<p style="margin:0;">{escape(locale.signoff)}</p><p style="margin:4px 0 0;font-weight:700;color:#111814;">Lamine Dabo</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">{escape(locale.founder_title)}</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">San Francisco, California</p>
<p style="margin:6px 0 0;font-size:14px;"><a href="{escape(settings.website_url, quote=True)}" style="color:#176b45;text-decoration:none;">{escape(settings.website_url.replace('https://', ''))}</a></p>
</td></tr>
<tr><td style="padding:24px 38px 26px;background:#f3f5f4;border-top:1px solid #e2e7e4;text-align:center;color:#7a857e;font-size:12px;line-height:1.55;">
<div style="font-weight:700;color:#566159;margin-bottom:5px;">AGRO-AI Inc.</div><div>{escape(settings.company_address.replace('AGRO-AI Inc., ', ''))}</div>
<div style="margin-top:8px;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">{escape(locale.footer_portal)}</a><span style="padding:0 7px;color:#b0b7b2;">·</span><a href="{escape(settings.launch_video_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">{escape(locale.footer_video)}</a><span style="padding:0 7px;color:#b0b7b2;">·</span><a href="{escape(unsubscribe_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">{escape(locale.footer_unsubscribe)}</a></div>
<div style="margin-top:10px;color:#98a19b;">{escape(locale.footer_reason)}</div>
</td></tr></table></td></tr></table></body></html>"""

    return RenderedEmail(
        subject=subject,
        html=html,
        text=text,
        unsubscribe_url=unsubscribe_url,
        language=language.value,
        language_source=resolution.source,
        language_confidence=resolution.confidence,
        localization_ready=ready,
    )


def _render_warm_buyer_reengagement(
    prospect: OutreachProspect,
    settings: OutreachSettings,
    *,
    unsubscribe_url: str,
    resolution: LanguageResolution,
) -> RenderedEmail:
    language = resolution.language
    locale = locale_for(language)
    subject = (
        prospect.subject
        or f"A meaningful AGRO-AI update since we last spoke — {prospect.account}"
    ).strip()
    greeting = _greeting(prospect, language)
    ready = localization_ready(prospect, language)
    prior_context = prospect.prior_relationship_context.strip()
    progress = prospect.progress_since_last_contact.strip()
    value = prospect.current_value_hypothesis.strip()
    ask = prospect.reengagement_ask.strip()

    reconnect = (
        "I wanted to reconnect personally—not as a cold introduction, but because our earlier conversation "
        "helped clarify what AGRO-AI needed to become before it would be genuinely useful in your environment."
    )
    launch_bridge = (
        "We have now launched the AGRO-AI Enterprise Portal: a live operating workspace for connecting "
        "field and water evidence, surfacing priority exceptions, assigning follow-up, and keeping decisions "
        "and verified outcomes in one reviewable workflow. It is designed to sit alongside existing systems, not replace them."
    )
    closing = (
        "There is no need to restart an old sales process. The simplest next step is to review the portal directly, "
        "then decide whether a focused working session around your real workflow is worth reopening."
    )

    text = "\n".join(
        [
            greeting,
            "",
            reconnect,
            "",
            prior_context,
            "",
            f"Since we last spoke, {progress}",
            "",
            launch_bridge,
            "",
            value,
            "",
            ask,
            "",
            "Review the AGRO-AI Enterprise Portal:",
            settings.enterprise_portal_url,
            "",
            "Book a focused working session:",
            settings.calendly_url,
            "",
            closing,
            "",
            "Watch the Enterprise Portal launch video:",
            settings.launch_video_url,
            "",
            locale.signoff,
            "Lamine Dabo",
            locale.founder_title,
            "San Francisco, California",
            settings.website_url,
            "",
            f"AGRO-AI Inc. · {settings.company_address.replace('AGRO-AI Inc., ', '')}",
            f"{locale.footer_unsubscribe}: {unsubscribe_url}",
        ]
    )

    html = f"""<!doctype html>
<html lang="en" dir="ltr">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f5f7f6;color:#17211c;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f7f6;"><tr><td align="center" style="padding:28px 14px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:660px;background:#fff;border:1px solid #e7ebe8;border-radius:12px;overflow:hidden;">
<tr><td style="height:5px;background:#176b45;font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td style="padding:34px 38px 30px;font-size:16px;line-height:1.62;color:#202a24;text-align:left;">
<p style="margin:0 0 18px;">{escape(greeting)}</p>
<p style="margin:0 0 18px;">{escape(reconnect)}</p>
<p style="margin:0 0 18px;">{escape(prior_context)}</p>
<p style="margin:0 0 18px;"><strong>Since we last spoke,</strong> {escape(progress)}</p>
<p style="margin:0 0 18px;">{escape(launch_bridge)}</p>
<p style="margin:0 0 18px;">{escape(value)}</p>
<p style="margin:0 0 20px;">{escape(ask)}</p>
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 16px;"><tr><td style="border-radius:7px;background:#176b45;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="display:inline-block;padding:13px 19px;color:#fff;text-decoration:none;font-size:14px;font-weight:700;">Review the AGRO-AI Enterprise Portal</a></td></tr></table>
<p style="margin:0 0 20px;color:#5f6b63;font-size:14px;">Prefer to map it to your operation first? <a href="{escape(settings.calendly_url, quote=True)}" style="color:#176b45;text-decoration:underline;">Book a focused working session with me</a>.</p>
<p style="margin:0 0 22px;">{escape(closing)}</p>
<a href="{escape(settings.launch_video_url, quote=True)}" style="display:block;text-decoration:none;margin:0 0 24px;"><img src="{escape(settings.launch_video_thumbnail_url, quote=True)}" width="584" height="329" alt="AGRO-AI Enterprise Portal launch video" style="display:block;width:100%;max-width:584px;height:auto;aspect-ratio:16/9;object-fit:cover;border:0;border-radius:9px;"></a>
<p style="margin:0;">{escape(locale.signoff)}</p><p style="margin:4px 0 0;font-weight:700;color:#111814;">Lamine Dabo</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">{escape(locale.founder_title)}</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">San Francisco, California</p>
<p style="margin:6px 0 0;font-size:14px;"><a href="{escape(settings.website_url, quote=True)}" style="color:#176b45;text-decoration:none;">{escape(settings.website_url.replace('https://', ''))}</a></p>
</td></tr>
<tr><td style="padding:24px 38px 26px;background:#f3f5f4;border-top:1px solid #e2e7e4;text-align:center;color:#7a857e;font-size:12px;line-height:1.55;">
<div style="font-weight:700;color:#566159;margin-bottom:5px;">AGRO-AI Inc.</div><div>{escape(settings.company_address.replace('AGRO-AI Inc., ', ''))}</div>
<div style="margin-top:8px;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">Enterprise Portal</a><span style="padding:0 7px;color:#b0b7b2;">·</span><a href="{escape(settings.launch_video_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">Launch video</a><span style="padding:0 7px;color:#b0b7b2;">·</span><a href="{escape(unsubscribe_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">Unsubscribe</a></div>
<div style="margin-top:10px;color:#98a19b;">You are receiving this because we previously discussed AGRO-AI or a potential operational fit.</div>
</td></tr></table></td></tr></table></body></html>"""

    return RenderedEmail(
        subject=subject,
        html=html,
        text=text,
        unsubscribe_url=unsubscribe_url,
        language=language.value,
        language_source=resolution.source,
        language_confidence=resolution.confidence,
        localization_ready=ready,
    )


def render_email(prospect: OutreachProspect, settings: OutreachSettings, *, unsubscribe_url: str) -> RenderedEmail:
    resolution: LanguageResolution = resolve_language(prospect.preferred_language, prospect.country)
    if prospect.message_type == OutreachMessageType.post_signup_founder_followup:
        return _render_post_signup_founder_followup(
            prospect,
            settings,
            unsubscribe_url=unsubscribe_url,
            resolution=resolution,
        )
    if prospect.message_type == OutreachMessageType.warm_buyer_reengagement:
        return _render_warm_buyer_reengagement(
            prospect,
            settings,
            unsubscribe_url=unsubscribe_url,
            resolution=resolution,
        )

    language = resolution.language
    locale = locale_for(language)
    paragraph_one, paragraph_two = segment_copy(language, prospect.segment)
    subject = _subject(prospect, language)
    greeting = _greeting(prospect, language)
    ready = localization_ready(prospect, language)

    observation_raw, relevance_raw, wedge_raw, why_now_raw = _dynamic_copy(prospect, language)
    observation = _sentence(observation_raw)
    relevance = _sentence(relevance_raw)
    wedge = _sentence(wedge_raw)
    why_now = why_now_raw.strip()
    relevance_sentence = f" {relevance}" if relevance else ""
    reaching_out = locale.reaching_out.format(observation=observation, relevance=relevance_sentence)
    workflow_prefix = locale.workflow_prefix.format(account=prospect.account)

    text_parts = [greeting, "", locale.intro, "", reaching_out, ""]
    if why_now:
        text_parts.extend([why_now, ""])
    text_parts.extend([
        paragraph_one,
        "",
        paragraph_two,
        "",
        f"{workflow_prefix} {wedge}",
        "",
        locale.launch_message,
        settings.enterprise_portal_url,
        "",
        locale.launch_video_label,
        settings.launch_video_url,
        "",
        f"{locale.secondary_prefix} {locale.secondary_cta}:",
        settings.calendly_url,
        "",
        locale.signoff,
        "Lamine Dabo",
        locale.founder_title,
        "San Francisco, California",
        settings.website_url,
        "",
        f"AGRO-AI Inc. · {settings.company_address.replace('AGRO-AI Inc., ', '')}",
        f"{locale.footer_unsubscribe}: {unsubscribe_url}",
    ])
    text = "\n".join(text_parts)

    why_now_html = f'<p style="margin:0 0 18px 0;">{escape(why_now)}</p>' if why_now else ""
    text_align = "right" if locale.direction == "rtl" else "left"

    html = f"""<!doctype html>
<html lang="{escape(locale.html_lang, quote=True)}" dir="{escape(locale.direction, quote=True)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f5f7f6;color:#17211c;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f7f6;"><tr><td align="center" style="padding:28px 14px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:660px;background:#fff;border:1px solid #e7ebe8;border-radius:12px;overflow:hidden;">
<tr><td style="height:5px;background:#176b45;font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td dir="{escape(locale.direction, quote=True)}" style="padding:34px 38px 30px;font-size:16px;line-height:1.62;color:#202a24;text-align:{text_align};">
<p style="margin:0 0 18px;">{escape(greeting)}</p>
<p style="margin:0 0 18px;">{escape(locale.intro)}</p>
<p style="margin:0 0 18px;">{escape(reaching_out)}</p>
{why_now_html}
<p style="margin:0 0 18px;">{escape(paragraph_one)}</p>
<p style="margin:0 0 18px;">{escape(paragraph_two)}</p>
<p style="margin:0 0 18px;"><strong>{escape(workflow_prefix)}</strong> {escape(wedge)}</p>
<p style="margin:0 0 16px;">{escape(locale.launch_message)}</p>
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 18px;"><tr><td style="border-radius:7px;background:#176b45;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="display:inline-block;padding:13px 19px;color:#fff;text-decoration:none;font-size:14px;font-weight:700;">{escape(locale.primary_cta)}</a></td></tr></table>
<p style="margin:0 0 22px;color:#5f6b63;font-size:14px;">{escape(locale.secondary_prefix)} <a href="{escape(settings.calendly_url, quote=True)}" style="color:#176b45;text-decoration:underline;">{escape(locale.secondary_cta)}</a>.</p>
<a href="{escape(settings.launch_video_url, quote=True)}" style="display:block;text-decoration:none;margin:0 0 24px;"><img src="{escape(settings.launch_video_thumbnail_url, quote=True)}" width="584" height="329" alt="{escape(locale.launch_alt, quote=True)}" style="display:block;width:100%;max-width:584px;height:auto;aspect-ratio:16/9;object-fit:cover;border:0;border-radius:9px;"></a>
<p style="margin:0;">{escape(locale.signoff)}</p><p style="margin:4px 0 0;font-weight:700;color:#111814;">Lamine Dabo</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">{escape(locale.founder_title)}</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">San Francisco, California</p>
<p style="margin:6px 0 0;font-size:14px;"><a href="{escape(settings.website_url, quote=True)}" style="color:#176b45;text-decoration:none;">{escape(settings.website_url.replace('https://', ''))}</a></p>
</td></tr>
<tr><td style="padding:24px 38px 26px;background:#f3f5f4;border-top:1px solid #e2e7e4;text-align:center;color:#7a857e;font-size:12px;line-height:1.55;">
<div style="font-weight:700;color:#566159;margin-bottom:5px;">AGRO-AI Inc.</div><div>{escape(settings.company_address.replace('AGRO-AI Inc., ', ''))}</div>
<div style="margin-top:8px;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">{escape(locale.footer_portal)}</a><span style="padding:0 7px;color:#b0b7b2;">·</span><a href="{escape(settings.launch_video_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">{escape(locale.footer_video)}</a><span style="padding:0 7px;color:#b0b7b2;">·</span><a href="{escape(unsubscribe_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">{escape(locale.footer_unsubscribe)}</a></div>
<div style="margin-top:10px;color:#98a19b;">{escape(locale.footer_reason)}</div>
</td></tr></table></td></tr></table></body></html>"""

    return RenderedEmail(
        subject=subject,
        html=html,
        text=text,
        unsubscribe_url=unsubscribe_url,
        language=language.value,
        language_source=resolution.source,
        language_confidence=resolution.confidence,
        localization_ready=ready,
    )


__all__ = ["RenderedEmail", "localization_ready", "render_email"]
