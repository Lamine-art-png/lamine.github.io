from __future__ import annotations

from pathlib import Path

ROOT = Path("agroai_api")
CONFIG = ROOT / "app/outreach/config.py"
ROUTER = ROOT / "app/outreach/router.py"
TEMPLATES = ROOT / "app/outreach/templates.py"
TEST = ROOT / "tests/unit/test_outreach_live_demo_email.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected exactly one match, found {count}: {old[:140]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Runtime configuration: preserve the launch video and add a distinct live demo.
replace_once(
    CONFIG,
    """    launch_video_url: str
    launch_video_thumbnail_url: str
    company_address: str
""",
    """    launch_video_url: str
    launch_video_thumbnail_url: str
    live_demo_url: str
    live_demo_thumbnail_url: str
    company_address: str
""",
)
replace_once(
    CONFIG,
    """            launch_video_thumbnail_url=os.getenv(
                "OUTREACH_LAUNCH_VIDEO_THUMBNAIL_URL",
                "https://i.ytimg.com/vi/NKVhX8imyT4/maxresdefault.jpg",
            ).strip(),
            company_address=os.getenv(
""",
    """            launch_video_thumbnail_url=os.getenv(
                "OUTREACH_LAUNCH_VIDEO_THUMBNAIL_URL",
                "https://i.ytimg.com/vi/NKVhX8imyT4/maxresdefault.jpg",
            ).strip(),
            live_demo_url=os.getenv(
                "OUTREACH_LIVE_DEMO_URL",
                "https://youtu.be/4KgH4R57tco",
            ).strip(),
            live_demo_thumbnail_url=os.getenv(
                "OUTREACH_LIVE_DEMO_THUMBNAIL_URL",
                "https://i.ytimg.com/vi/4KgH4R57tco/maxresdefault.jpg",
            ).strip(),
            company_address=os.getenv(
""",
)

# First-party click tracking and deploy-verifiable status metadata.
replace_once(
    ROUTER,
    '_TRACKED_LINK_KEYS = ("portal", "meeting", "video")',
    '_TRACKED_LINK_KEYS = ("portal", "meeting", "video", "live_demo")',
)
replace_once(
    ROUTER,
    """        "video": settings.launch_video_url,
    }
""",
    """        "video": settings.launch_video_url,
        "live_demo": settings.live_demo_url,
    }
""",
)
replace_once(
    ROUTER,
    """        "launch_video_thumbnail_url": settings.launch_video_thumbnail_url,
        "thumbnail_profile": "hd_16_9",
""",
    """        "launch_video_thumbnail_url": settings.launch_video_thumbnail_url,
        "thumbnail_profile": "hd_16_9",
        "live_demo_url": settings.live_demo_url,
        "live_demo_thumbnail_url": settings.live_demo_thumbnail_url,
        "live_demo_thumbnail_profile": "hd_16_9_maxres",
""",
)
replace_once(
    ROUTER,
    '"outreach_release": "production-i18n-hd-thumbnail-signup-followup-engagement-v1"',
    '"outreach_release": "production-live-demo-hd-cta-engagement-v2"',
)

helper = r'''

_LIVE_DEMO_COPY: dict[OutreachLanguage, tuple[str, str, str]] = {
    OutreachLanguage.en: (
        "Watch a live demo",
        "See the AGRO-AI Enterprise Portal working with real operational workflows",
        "AGRO-AI Enterprise Portal live demo — from raw field data to operational decisions",
    ),
    OutreachLanguage.fr: (
        "Voir la démo en direct",
        "Découvrez le portail d’entreprise AGRO-AI en action sur des flux opérationnels réels",
        "Démo en direct du portail d’entreprise AGRO-AI — des données terrain brutes aux décisions opérationnelles",
    ),
    OutreachLanguage.es: (
        "Ver una demostración en vivo",
        "Vea el Portal Empresarial de AGRO-AI funcionando con flujos operativos reales",
        "Demostración en vivo del Portal Empresarial de AGRO-AI — de los datos de campo a las decisiones operativas",
    ),
    OutreachLanguage.pt: (
        "Assistir a uma demonstração ao vivo",
        "Veja o Portal Empresarial da AGRO-AI funcionando com fluxos operacionais reais",
        "Demonstração ao vivo do Portal Empresarial da AGRO-AI — dos dados de campo às decisões operacionais",
    ),
    OutreachLanguage.ar: (
        "شاهد العرض التوضيحي المباشر",
        "شاهد بوابة AGRO-AI للمؤسسات وهي تعمل على تدفقات تشغيلية واقعية",
        "عرض توضيحي مباشر لبوابة AGRO-AI للمؤسسات — من بيانات الحقول الخام إلى القرارات التشغيلية",
    ),
}


def _live_demo_copy(language: OutreachLanguage) -> tuple[str, str, str]:
    return _LIVE_DEMO_COPY.get(language, _LIVE_DEMO_COPY[OutreachLanguage.en])


def _render_live_demo_html(settings: OutreachSettings, language: OutreachLanguage) -> str:
    cta, heading, alt = _live_demo_copy(language)
    return (
        f'<p style="margin:0 0 12px;color:#202a24;font-size:15px;"><strong>{escape(heading)}</strong></p>'
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 14px;">'
        '<tr><td style="border-radius:7px;background:#111814;">'
        f'<a href="{escape(settings.live_demo_url, quote=True)}" '
        'style="display:inline-block;padding:13px 19px;color:#fff;text-decoration:none;font-size:14px;font-weight:700;letter-spacing:.1px;">'
        f'{escape(cta)}</a></td></tr></table>'
        f'<a href="{escape(settings.live_demo_url, quote=True)}" style="display:block;text-decoration:none;margin:0 0 24px;">'
        f'<img src="{escape(settings.live_demo_thumbnail_url, quote=True)}" width="584" height="329" '
        f'alt="{escape(alt, quote=True)}" '
        'style="display:block;width:100%;max-width:584px;height:auto;aspect-ratio:16/9;object-fit:cover;border:0;border-radius:9px;image-rendering:auto;">'
        '</a>'
    )
'''
replace_once(
    TEMPLATES,
    "\n\ndef _render_post_signup_founder_followup(\n",
    helper + "\n\ndef _render_post_signup_founder_followup(\n",
)

# Plain-text equivalents for all three live message types.
replace_once(
    TEMPLATES,
    """            closing,
            "",
            locale.launch_video_label,
            settings.launch_video_url,
""",
    """            closing,
            "",
            _live_demo_copy(language)[1] + ":",
            settings.live_demo_url,
            "",
            locale.launch_video_label,
            settings.launch_video_url,
""",
)
replace_once(
    TEMPLATES,
    """            closing,
            "",
            "Watch the Enterprise Portal launch video:",
            settings.launch_video_url,
""",
    """            closing,
            "",
            _live_demo_copy(language)[1] + ":",
            settings.live_demo_url,
            "",
            "Watch the Enterprise Portal launch video:",
            settings.launch_video_url,
""",
)
replace_once(
    TEMPLATES,
    """        locale.launch_message,
        settings.enterprise_portal_url,
        "",
        locale.launch_video_label,
        settings.launch_video_url,
""",
    """        locale.launch_message,
        settings.enterprise_portal_url,
        "",
        _live_demo_copy(language)[1] + ":",
        settings.live_demo_url,
        "",
        locale.launch_video_label,
        settings.launch_video_url,
""",
)

# HTML: add live-demo button and max-resolution thumbnail, then keep launch video.
launch_locale_anchor = '<a href="{escape(settings.launch_video_url, quote=True)}" style="display:block;text-decoration:none;margin:0 0 24px;"><img src="{escape(settings.launch_video_thumbnail_url, quote=True)}" width="584" height="329" alt="{escape(locale.launch_alt, quote=True)}" style="display:block;width:100%;max-width:584px;height:auto;aspect-ratio:16/9;object-fit:cover;border:0;border-radius:9px;"></a>'

post_signup_context = (
    '<p style="margin:0 0 22px;">{escape(closing)}</p>\n'
    + launch_locale_anchor
)
replace_once(
    TEMPLATES,
    post_signup_context,
    '<p style="margin:0 0 22px;">{escape(closing)}</p>\n'
    '{_render_live_demo_html(settings, language)}\n'
    '<p style="margin:0 0 12px;color:#5f6b63;font-size:14px;"><strong>{escape(locale.launch_video_label.rstrip(\":\").rstrip(\"：\"))}</strong></p>\n'
    + launch_locale_anchor,
)

warm_anchor = '<a href="{escape(settings.launch_video_url, quote=True)}" style="display:block;text-decoration:none;margin:0 0 24px;"><img src="{escape(settings.launch_video_thumbnail_url, quote=True)}" width="584" height="329" alt="AGRO-AI Enterprise Portal launch video" style="display:block;width:100%;max-width:584px;height:auto;aspect-ratio:16/9;object-fit:cover;border:0;border-radius:9px;"></a>'
warm_context = '<p style="margin:0 0 22px;">{escape(closing)}</p>\n' + warm_anchor
replace_once(
    TEMPLATES,
    warm_context,
    '<p style="margin:0 0 22px;">{escape(closing)}</p>\n'
    '{_render_live_demo_html(settings, language)}\n'
    '<p style="margin:0 0 12px;color:#5f6b63;font-size:14px;"><strong>Enterprise Portal launch video</strong></p>\n'
    + warm_anchor,
)

cold_secondary = '<p style="margin:0 0 22px;color:#5f6b63;font-size:14px;">{escape(locale.secondary_prefix)} <a href="{escape(settings.calendly_url, quote=True)}" style="color:#176b45;text-decoration:underline;">{escape(locale.secondary_cta)}</a>.</p>'
cold_context = cold_secondary + "\n" + launch_locale_anchor
replace_once(
    TEMPLATES,
    cold_context,
    cold_secondary
    + "\n{_render_live_demo_html(settings, language)}\n"
    + '<p style="margin:0 0 12px;color:#5f6b63;font-size:14px;"><strong>{escape(locale.launch_video_label.rstrip(\":\").rstrip(\"：\"))}</strong></p>\n'
    + launch_locale_anchor,
)

TEST.write_text(
    r'''from __future__ import annotations


def _cold_prospect():
    from app.outreach.schemas import OutreachLanguage, OutreachProspect, VerificationStatus

    return OutreachProspect(
        prospect_id="live-demo-cold-001",
        email="operator@example.com",
        email_verification_status=VerificationStatus.verified_public_direct,
        first_name="Jordan",
        person_name="Jordan Example",
        title="Operations Director",
        account="Example Agricultural Operations",
        country="United States",
        segment="Enterprise Grower / Operator",
        preferred_language=OutreachLanguage.en,
        observation="the operating team coordinates field evidence across multiple systems",
        role_relevance="the role connects field execution and management review",
        pilot_wedge="connect field evidence, assigned actions and verified outcomes",
    )


def test_live_demo_defaults_are_hd_and_distinct_from_launch_video(monkeypatch):
    monkeypatch.delenv("OUTREACH_LIVE_DEMO_URL", raising=False)
    monkeypatch.delenv("OUTREACH_LIVE_DEMO_THUMBNAIL_URL", raising=False)

    from app.outreach.config import OutreachSettings

    settings = OutreachSettings.from_env()
    assert settings.launch_video_url == "https://youtu.be/NKVhX8imyT4"
    assert settings.live_demo_url == "https://youtu.be/4KgH4R57tco"
    assert settings.live_demo_thumbnail_url == "https://i.ytimg.com/vi/4KgH4R57tco/maxresdefault.jpg"
    assert settings.live_demo_url != settings.launch_video_url


def test_cold_outreach_keeps_portal_and_launch_video_and_adds_live_demo():
    from app.outreach.config import OutreachSettings
    from app.outreach.templates import render_email

    settings = OutreachSettings.from_env()
    rendered = render_email(_cold_prospect(), settings, unsubscribe_url="https://api.example.test/u")

    assert "Get started with AGRO-AI" in rendered.html
    assert "Watch a live demo" in rendered.html
    assert settings.live_demo_url in rendered.html
    assert settings.live_demo_thumbnail_url in rendered.html
    assert 'width="584" height="329"' in rendered.html
    assert "aspect-ratio:16/9" in rendered.html
    assert settings.launch_video_url in rendered.html
    assert settings.launch_video_thumbnail_url in rendered.html
    assert settings.live_demo_url in rendered.text
    assert settings.launch_video_url in rendered.text


def test_live_demo_is_a_first_party_tracked_destination():
    from app.outreach import router

    assert "live_demo" in router._TRACKED_LINK_KEYS
    assert router._tracking_destinations()["live_demo"] == router.settings.live_demo_url
''',
    encoding="utf-8",
)

for path in (CONFIG, ROUTER, TEMPLATES, TEST):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")

print("PATCH VERIFIED — live demo CTA, HD thumbnail, launch video preservation, and tracking are present")
