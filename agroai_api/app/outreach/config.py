"""Environment-driven configuration for AGRO-AI founder outreach.

The outreach sender intentionally uses its own Resend credential so customer
outreach cannot accidentally share or rotate the transactional auth/careers
key. Safe defaults keep delivery in preview-only mode.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 10_000) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class OutreachSettings:
    resend_api_key: str
    admin_token: str
    unsubscribe_secret: str
    sender: str
    reply_to: str
    public_api_base_url: str
    website_url: str
    enterprise_portal_url: str
    calendly_url: str
    launch_video_url: str
    launch_video_thumbnail_url: str
    company_address: str
    dry_run: bool
    daily_send_limit: int
    max_batch_size: int
    resend_api_url: str

    @classmethod
    def from_env(cls) -> "OutreachSettings":
        return cls(
            resend_api_key=os.getenv("OUTREACH_RESEND_API_KEY", "").strip(),
            admin_token=os.getenv("OUTREACH_ADMIN_TOKEN", "").strip(),
            unsubscribe_secret=os.getenv("OUTREACH_UNSUBSCRIBE_SECRET", "").strip(),
            sender=os.getenv(
                "OUTREACH_FROM_EMAIL",
                "Lamine Dabo <lamine@mail.agroai-pilot.com>",
            ).strip(),
            reply_to=os.getenv(
                "OUTREACH_REPLY_TO",
                "agroaicontact@gmail.com",
            ).strip(),
            public_api_base_url=os.getenv(
                "OUTREACH_PUBLIC_API_BASE_URL",
                "https://api.agroai-pilot.com",
            ).rstrip("/"),
            website_url=os.getenv(
                "OUTREACH_WEBSITE_URL",
                "https://agroai-pilot.com",
            ).rstrip("/"),
            enterprise_portal_url=os.getenv(
                "OUTREACH_ENTERPRISE_PORTAL_URL",
                "https://app.agroai-pilot.com",
            ).rstrip("/"),
            calendly_url=os.getenv(
                "OUTREACH_CALENDLY_URL",
                "https://calendly.com/agroaicontact/30min?month=2026-07",
            ).strip(),
            launch_video_url=os.getenv(
                "OUTREACH_LAUNCH_VIDEO_URL",
                "https://youtu.be/NKVhX8imyT4",
            ).strip(),
            launch_video_thumbnail_url=os.getenv(
                "OUTREACH_LAUNCH_VIDEO_THUMBNAIL_URL",
                "https://i.ytimg.com/vi/NKVhX8imyT4/maxresdefault.jpg",
            ).strip(),
            company_address=os.getenv(
                "OUTREACH_COMPANY_ADDRESS",
                "AGRO-AI Inc., 524 Columbus Avenue, San Francisco, CA 94133, USA",
            ).strip(),
            dry_run=_env_bool("OUTREACH_DRY_RUN", True),
            daily_send_limit=_env_int("OUTREACH_DAILY_SEND_LIMIT", 10, maximum=500),
            max_batch_size=_env_int("OUTREACH_MAX_BATCH_SIZE", 25, maximum=100),
            resend_api_url=os.getenv(
                "OUTREACH_RESEND_API_URL",
                "https://api.resend.com/emails",
            ).strip(),
        )

    @property
    def preview_ready(self) -> bool:
        return bool(self.admin_token and self.unsubscribe_secret)

    @property
    def send_ready(self) -> bool:
        return bool(self.resend_api_key and self.admin_token and self.unsubscribe_secret)


__all__ = ["OutreachSettings"]
