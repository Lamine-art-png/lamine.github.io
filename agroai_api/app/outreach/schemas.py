"""Strict request models for personalized founder-led outreach."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .localization import OutreachLanguage


class VerificationStatus(str, Enum):
    verified_public_direct = "verified_public_direct"
    verified_public_role = "verified_public_role"
    verified_vendor = "verified_vendor"
    unverified = "unverified"


class OutreachProspect(BaseModel):
    prospect_id: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=320)
    email_verification_status: VerificationStatus = VerificationStatus.unverified
    first_name: str = Field(min_length=1, max_length=100)
    person_name: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=250)
    account: str = Field(min_length=1, max_length=250)
    country: str = Field(default="", max_length=120)
    segment: str = Field(min_length=1, max_length=180)

    # Source-language personalization fields.
    observation: str = Field(min_length=12, max_length=1200)
    role_relevance: str = Field(default="", max_length=800)
    pilot_wedge: str = Field(min_length=8, max_length=1000)
    why_now: str = Field(default="", max_length=1000)
    subject: str | None = Field(default=None, max_length=180)

    # Conservative language routing. Explicit preference wins; otherwise a
    # single-country market hint is used and ambiguous/global records fall back
    # to English.
    preferred_language: OutreachLanguage = OutreachLanguage.auto

    # For non-English live delivery, every populated dynamic field must have a
    # localized peer. Preview remains available so operators can inspect copy.
    localized_observation: str = Field(default="", max_length=1200)
    localized_role_relevance: str = Field(default="", max_length=800)
    localized_pilot_wedge: str = Field(default="", max_length=1000)
    localized_why_now: str = Field(default="", max_length=1000)
    localized_subject: str | None = Field(default=None, max_length=180)

    linkedin_url: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000)

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1:
            raise ValueError("email must contain exactly one @")
        local, domain = normalized.split("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("email shape is invalid")
        if any(ch.isspace() for ch in normalized):
            raise ValueError("email cannot contain whitespace")
        return normalized

    @field_validator(
        "first_name",
        "person_name",
        "title",
        "account",
        "segment",
        "observation",
        "role_relevance",
        "pilot_wedge",
        "why_now",
        "localized_observation",
        "localized_role_relevance",
        "localized_pilot_wedge",
        "localized_why_now",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class PreviewRequest(BaseModel):
    prospect: OutreachProspect


class SendRequest(BaseModel):
    prospect: OutreachProspect
    send_now: bool = False


class BatchSendRequest(BaseModel):
    prospects: list[OutreachProspect] = Field(min_length=1, max_length=100)
    send_now: bool = False
    on_error: Literal["continue", "stop"] = "continue"


class SuppressionRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    reason: str = Field(default="manual", max_length=240)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


__all__ = [
    "BatchSendRequest",
    "OutreachLanguage",
    "OutreachProspect",
    "PreviewRequest",
    "SendRequest",
    "SuppressionRequest",
    "VerificationStatus",
]
