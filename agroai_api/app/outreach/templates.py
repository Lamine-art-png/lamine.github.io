"""Professional personalized AGRO-AI outreach email rendering."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from .config import OutreachSettings
from .schemas import OutreachProspect, VerificationStatus


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    html: str
    text: str
    unsubscribe_url: str


def _segment_copy(segment: str) -> tuple[str, str]:
    lower = segment.lower()
    if "water" in lower or "district" in lower or "agency" in lower:
        return (
            "We built AGRO-AI for agricultural and water-related workflows where evidence is often spread across field systems, irrigation data, ET and weather sources, reports, uploaded documents, email, and internal operating records.",
            "The portal brings that evidence into one working environment so teams can investigate exceptions, organize supporting sources, assign follow-up actions, and preserve a traceable decision record.",
        )
    if "institutional" in lower or "asset manager" in lower or "farmland" in lower:
        return (
            "We built AGRO-AI for agricultural portfolios where operating evidence remains fragmented across farms, managers, irrigation platforms, equipment systems, weather and ET sources, spreadsheets, files, and local workflows.",
            "The portal gives teams a common operating layer for material exceptions, water and field-risk evidence, planned-versus-completed activity, unresolved actions, and portfolio-level patterns without removing local operating autonomy.",
        )
    if "channel" in lower or "ecosystem" in lower:
        return (
            "We built AGRO-AI as an intelligence and workflow layer above the agricultural systems organizations already use, rather than another rip-and-replace platform.",
            "That creates a practical route to extend existing technology and member relationships into connected evidence, operational exceptions, assigned work, and traceable decisions.",
        )
    return (
        "We built AGRO-AI for agricultural teams that already operate across multiple systems—field and machine platforms, irrigation infrastructure, ET and weather data, cloud files, reports, email, and internal operating records.",
        "The portal creates one intelligence and workflow layer across those sources so teams can see exceptions earlier, turn decisions into assigned work, compare planned versus completed activity, and preserve a traceable record of what happened and what was verified.",
    )


def _default_subject(prospect: OutreachProspect) -> str:
    lower = prospect.segment.lower()
    if "water" in lower or "district" in lower or "agency" in lower:
        return f"A practical workflow idea for {prospect.account}"
    if "institutional" in lower or "asset manager" in lower or "farmland" in lower:
        return f"Operating intelligence across {prospect.account}'s agricultural assets"
    return f"A working idea for {prospect.account}'s agricultural operations"


def _greeting(prospect: OutreachProspect) -> str:
    if prospect.email_verification_status == VerificationStatus.verified_public_role:
        return f"Hello {prospect.account} team,"
    return f"Hi {prospect.first_name},"


def render_email(prospect: OutreachProspect, settings: OutreachSettings, *, unsubscribe_url: str) -> RenderedEmail:
    paragraph_one, paragraph_two = _segment_copy(prospect.segment)
    subject = (prospect.subject or _default_subject(prospect)).strip()
    greeting = _greeting(prospect)
    observation = prospect.observation.strip().rstrip(".") + "."
    relevance = prospect.role_relevance.strip()
    why_now = prospect.why_now.strip()
    wedge = prospect.pilot_wedge.strip().rstrip(".") + "."
    relevance_sentence = f" {relevance.rstrip('.')}." if relevance else ""

    text_parts = [
        greeting,
        "",
        "I’m Lamine Dabo, Founder & CEO of AGRO-AI.",
        "",
        f"I’m reaching out because {observation}{relevance_sentence}",
        "",
    ]
    if why_now:
        text_parts.extend([why_now, ""])
    text_parts.extend([
        paragraph_one,
        "",
        paragraph_two,
        "",
        f"For {prospect.account}, the first workflow I would examine is: {wedge}",
        "",
        "We launched the AGRO-AI Enterprise Portal globally this week. You can explore it directly here:",
        settings.enterprise_portal_url,
        "",
        "Launch video:",
        settings.launch_video_url,
        "",
        "If it is useful, I would be glad to walk through the platform around a scenario close to your actual operating environment:",
        settings.calendly_url,
        "",
        "Best,",
        "Lamine Dabo",
        "Founder & CEO, AGRO-AI",
        "San Francisco, California",
        settings.website_url,
        "",
        f"AGRO-AI Inc. · {settings.company_address.replace('AGRO-AI Inc., ', '')}",
        f"Unsubscribe: {unsubscribe_url}",
    ])
    text = "\n".join(text_parts)

    why_now_html = f'<p style="margin:0 0 18px 0;">{escape(why_now)}</p>' if why_now else ""
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f5f7f6;color:#17211c;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f7f6;"><tr><td align="center" style="padding:28px 14px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:660px;background:#fff;border:1px solid #e7ebe8;border-radius:12px;overflow:hidden;">
<tr><td style="height:5px;background:#176b45;font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td style="padding:34px 38px 30px;font-size:16px;line-height:1.62;color:#202a24;">
<p style="margin:0 0 18px;">{escape(greeting)}</p>
<p style="margin:0 0 18px;">I’m Lamine Dabo, Founder &amp; CEO of AGRO-AI.</p>
<p style="margin:0 0 18px;">I’m reaching out because {escape(observation)}{escape(relevance_sentence)}</p>
{why_now_html}
<p style="margin:0 0 18px;">{escape(paragraph_one)}</p>
<p style="margin:0 0 18px;">{escape(paragraph_two)}</p>
<p style="margin:0 0 18px;"><strong>For {escape(prospect.account)}, the first workflow I would examine is:</strong> {escape(wedge)}</p>
<p style="margin:0 0 16px;">We launched the AGRO-AI Enterprise Portal globally this week. You can explore it directly—no sales call required.</p>
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 18px;"><tr><td style="border-radius:7px;background:#176b45;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="display:inline-block;padding:13px 19px;color:#fff;text-decoration:none;font-size:14px;font-weight:700;">Open the AGRO-AI Enterprise Portal</a></td></tr></table>
<p style="margin:0 0 22px;color:#5f6b63;font-size:14px;">Prefer to talk first? <a href="{escape(settings.calendly_url, quote=True)}" style="color:#176b45;text-decoration:underline;">Book 30 minutes with me</a>.</p>
<a href="{escape(settings.launch_video_url, quote=True)}" style="display:block;text-decoration:none;margin:0 0 24px;"><img src="{escape(settings.launch_video_thumbnail_url, quote=True)}" width="584" alt="AGRO-AI Enterprise Portal global launch" style="display:block;width:100%;max-width:584px;height:auto;border:0;border-radius:9px;"></a>
<p style="margin:0;">Best,</p><p style="margin:4px 0 0;font-weight:700;color:#111814;">Lamine Dabo</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">Founder &amp; CEO · AGRO-AI</p>
<p style="margin:2px 0 0;color:#526158;font-size:14px;">San Francisco, California</p>
<p style="margin:6px 0 0;font-size:14px;"><a href="{escape(settings.website_url, quote=True)}" style="color:#176b45;text-decoration:none;">{escape(settings.website_url.replace('https://', ''))}</a></p>
</td></tr>
<tr><td style="padding:24px 38px 26px;background:#f3f5f4;border-top:1px solid #e2e7e4;text-align:center;color:#7a857e;font-size:12px;line-height:1.55;">
<div style="font-weight:700;color:#566159;margin-bottom:5px;">AGRO-AI Inc.</div><div>{escape(settings.company_address.replace('AGRO-AI Inc., ', ''))}</div>
<div style="margin-top:8px;"><a href="{escape(settings.enterprise_portal_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">Enterprise Portal</a><span style="padding:0 7px;color:#b0b7b2;">·</span><a href="{escape(settings.launch_video_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">Launch video</a><span style="padding:0 7px;color:#b0b7b2;">·</span><a href="{escape(unsubscribe_url, quote=True)}" style="color:#5f6b63;text-decoration:underline;">Unsubscribe</a></div>
<div style="margin-top:10px;color:#98a19b;">You received this message because this organization or professional role appears relevant to the operational problem described above.</div>
</td></tr></table></td></tr></table></body></html>"""
    return RenderedEmail(subject=subject, html=html, text=text, unsubscribe_url=unsubscribe_url)


__all__ = ["RenderedEmail", "render_email"]
