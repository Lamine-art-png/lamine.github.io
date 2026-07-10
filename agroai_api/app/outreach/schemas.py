"""Strict request models for personalized founder-led outreach."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .localization import OutreachLanguage


class VerificationStatus(str, Enum):
    verified_public_direct = "verified_public_direct"
    verified_public_role = "verified_public_role"
    verified_vendor = "verified_vendor"
    unverified = "unverified"


class OutreachMessageType(str, Enum):
    cold_outreach = "cold_outreach"
    post_signup_founder_followup = "post_signup_founder_followup"


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
    message_type: OutreachMessageType = OutreachMessageType.cold_outreach

    # Cold-outreach personalization fields. They are conditionally required for
    # cold outreach but intentionally optional for lifecycle follow-up emails.
    observation: str = Field(default="", max_length=1200)
    role_relevance: str = Field(default="", max_length=800)
    pilot_wedge: str = Field(default="", max_length=1000)
    why_now: str = Field(default="", max_length=1000)
    subject: str | None = Field(default=None, max_length=180)

    # Post-signup lifecycle personalization. This is the executive-specific
    # paragraph that explains why the signup is interesting without pretending
    # the recipient is a cold lead.
    signup_interest_context: str = Field(default="", max_length=1200)

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
        "signup_interest_context",
        "localized_observation",
        "localized_role_relevance",
        "localized_pilot_wedge",
        "localized_why_now",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_message_specific_copy(self):
        if self.message_type == OutreachMessageType.cold_outreach:
            if len(self.observation) < 12:
                raise ValueError("cold outreach requires observation with at least 12 characters")
            if len(self.pilot_wedge) < 8:
                raise ValueError("cold outreach requires pilot_wedge with at least 8 characters")
        elif self.message_type == OutreachMessageType.post_signup_founder_followup:
            if len(self.signup_interest_context) < 12:
                raise ValueError("post-signup founder follow-up requires signup_interest_context")
        return self


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
    "OutreachMessageType",
    "OutreachProspect",
    "PreviewRequest",
    "SendRequest",
    "SuppressionRequest",
    "VerificationStatus",
]
