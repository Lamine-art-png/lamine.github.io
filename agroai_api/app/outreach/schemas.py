"""Strict request models for personalized founder-led outreach."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    observation: str = Field(min_length=12, max_length=1200)
    role_relevance: str = Field(default="", max_length=800)
    pilot_wedge: str = Field(min_length=8, max_length=1000)
    why_now: str = Field(default="", max_length=1000)
    subject: str | None = Field(default=None, max_length=180)
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
    "OutreachProspect",
    "PreviewRequest",
    "SendRequest",
    "SuppressionRequest",
    "VerificationStatus",
]
