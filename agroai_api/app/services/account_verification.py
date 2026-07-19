from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import settings

VERIFICATION_ENGINE_VERSION = "2026-07-20-v1"

ALLOWED_ORGANIZATION_TYPES = {
    "farm_or_grower",
    "agribusiness",
    "agricultural_landowner",
    "investment_manager",
    "irrigation_dealer_or_contractor",
    "irrigation_technology_provider",
    "oem_or_equipment_manufacturer",
    "agricultural_consultant",
    "research_institution",
    "water_agency_or_district",
    "food_or_supply_chain_company",
    "other_agricultural_organization",
}

CONSUMER_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "ymail.com", "icloud.com", "me.com", "mac.com", "aol.com",
    "proton.me", "protonmail.com", "gmx.com", "mail.com", "zoho.com",
}

# Deliberately conservative local denylist. It blocks well-known temporary inboxes
# without making a third-party reputation API a registration availability dependency.
DISPOSABLE_EMAIL_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "dispostable.com", "fakeinbox.com",
    "guerrillamail.com", "guerrillamail.net", "maildrop.cc", "mailinator.com",
    "mohmal.com", "sharklasers.com", "tempmail.com", "temp-mail.org", "throwawaymail.com",
    "trashmail.com", "yopmail.com", "yopmail.fr",
}

AGRICULTURE_TERMS = {
    "acre", "agric", "agron", "almond", "avocado", "berry", "cattle", "crop", "dairy",
    "farm", "field", "food", "forestry", "grower", "harvest", "hectare", "irrigation",
    "livestock", "orchard", "pistachio", "produce", "ranch", "soil", "vineyard", "water",
    "well", "yield",
}

PLACEHOLDER_TERMS = {
    "abc", "asdf", "demo", "fake", "fun", "hello", "idk", "n/a", "na", "none", "non",
    "nothing", "qwerty", "random", "sample", "test", "testing", "xxx",
}


@dataclass(frozen=True)
class VerificationInput:
    email: str
    name: str | None
    organization_name: str
    organization_type: str | None
    professional_role: str | None
    phone_number: str | None
    website_url: str | None
    professional_profile_url: str | None
    country: str | None
    operating_region: str | None
    acres_or_sites: str | None
    primary_crops: str | None
    intended_use: str | None
    planned_data_sources: str | None


@dataclass(frozen=True)
class VerificationDecision:
    approved: bool
    status: str
    score: int
    reason_codes: tuple[str, ...]
    email_domain: str
    domain_classification: str
    website_domain: str | None
    evidence_digest: str
    engine_version: str = VERIFICATION_ENGINE_VERSION


def verification_enforcement_enabled() -> bool:
    mode = str(getattr(settings, "ACCOUNT_VERIFICATION_MODE", "auto") or "auto").strip().lower()
    if mode in {"disabled", "off", "false", "0"}:
        return False
    if mode in {"enforce", "required", "on", "true", "1"}:
        return True
    return str(getattr(settings, "APP_ENV", "development") or "development").strip().lower() in {
        "production", "prod"
    }


def _normalized_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower().rstrip(".")


def classify_email_domain(domain: str) -> str:
    normalized = domain.strip().lower().rstrip(".")
    if normalized in DISPOSABLE_EMAIL_DOMAINS:
        return "disposable"
    if normalized in CONSUMER_EMAIL_DOMAINS:
        return "consumer"
    return "organization"


def _safe_web_domain(value: str | None) -> str | None:
    raw = _normalized_text(value)
    if not raw:
        return None
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        return None
    if "." not in hostname:
        return None
    return hostname[4:] if hostname.startswith("www.") else hostname


def _is_domain_match(email_domain: str, website_domain: str | None) -> bool:
    if not website_domain:
        return False
    return (
        email_domain == website_domain
        or email_domain.endswith(f".{website_domain}")
        or website_domain.endswith(f".{email_domain}")
    )


def _phone_is_plausible(value: str | None) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    return 8 <= len(digits) <= 15


def _is_placeholder(value: str | None) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", _normalized_text(value).casefold()).strip()
    if not normalized:
        return True
    tokens = set(normalized.split())
    return len(normalized) < 3 or bool(tokens.intersection(PLACEHOLDER_TERMS))


def _contains_agricultural_context(*values: str | None) -> bool:
    combined = " ".join(_normalized_text(value).casefold() for value in values)
    return any(term in combined for term in AGRICULTURE_TERMS)


def _evidence_digest(payload: VerificationInput) -> str:
    canonical = "|".join(
        _normalized_text(value).casefold()
        for value in (
            payload.email,
            payload.name,
            payload.organization_name,
            payload.organization_type,
            payload.professional_role,
            payload.website_url,
            payload.professional_profile_url,
            payload.country,
            payload.operating_region,
            payload.acres_or_sites,
            payload.primary_crops,
            payload.intended_use,
            payload.planned_data_sources,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_organization(payload: VerificationInput) -> VerificationDecision:
    email_domain = _email_domain(payload.email)
    domain_classification = classify_email_domain(email_domain)
    website_domain = _safe_web_domain(payload.website_url)
    profile_domain = _safe_web_domain(payload.professional_profile_url)
    reason_codes: list[str] = []
    score = 0

    if domain_classification == "disposable":
        reason_codes.append("disposable_email_domain")
    elif domain_classification == "organization":
        score += 30
    else:
        score += 14

    if _is_placeholder(payload.name):
        reason_codes.append("invalid_name")
    else:
        score += 5

    if _is_placeholder(payload.organization_name):
        reason_codes.append("unverifiable_organization_name")
    else:
        score += 8

    organization_type = _normalized_text(payload.organization_type).casefold().replace(" ", "_")
    if organization_type not in ALLOWED_ORGANIZATION_TYPES:
        reason_codes.append("unsupported_organization_type")
    else:
        score += 8

    if len(_normalized_text(payload.professional_role)) < 3 or _is_placeholder(payload.professional_role):
        reason_codes.append("professional_role_required")
    else:
        score += 7

    if not _phone_is_plausible(payload.phone_number):
        reason_codes.append("valid_phone_required")
    else:
        score += 12

    if len(_normalized_text(payload.country)) < 2:
        reason_codes.append("country_required")
    else:
        score += 4

    if len(_normalized_text(payload.operating_region)) < 2:
        reason_codes.append("operating_region_required")
    else:
        score += 4

    acres = _normalized_text(payload.acres_or_sites)
    if len(acres) < 1 or _is_placeholder(acres):
        reason_codes.append("operational_scale_required")
    else:
        score += 9

    primary_crops = _normalized_text(payload.primary_crops)
    if len(primary_crops) < 3 or _is_placeholder(primary_crops):
        reason_codes.append("agricultural_segment_required")
    else:
        score += 8

    intended_use = _normalized_text(payload.intended_use)
    if len(intended_use) < 50:
        reason_codes.append("detailed_use_case_required")
    elif not _contains_agricultural_context(intended_use, primary_crops, payload.organization_type):
        reason_codes.append("agricultural_use_case_not_detected")
    else:
        score += 16

    planned_sources = _normalized_text(payload.planned_data_sources)
    if len(planned_sources) < 8 or _is_placeholder(planned_sources):
        reason_codes.append("data_sources_required")
    else:
        score += 7

    evidence_domain = website_domain or profile_domain
    if not evidence_domain:
        reason_codes.append("organization_evidence_required")
    else:
        score += 8

    if _is_domain_match(email_domain, website_domain):
        score += 12
    elif domain_classification == "organization" and website_domain:
        reason_codes.append("email_website_domain_mismatch")

    # Consumer inboxes are permitted, but only when the operational evidence is
    # materially stronger than the evidence needed for a matching organization domain.
    if domain_classification == "consumer":
        if not (website_domain or profile_domain):
            reason_codes.append("consumer_email_requires_public_profile")
        if not _phone_is_plausible(payload.phone_number):
            reason_codes.append("consumer_email_requires_phone")
        if len(acres) < 1:
            reason_codes.append("consumer_email_requires_operational_scale")

    hard_failure_codes = {
        "disposable_email_domain",
        "invalid_name",
        "unverifiable_organization_name",
        "unsupported_organization_type",
        "professional_role_required",
        "valid_phone_required",
        "country_required",
        "operating_region_required",
        "operational_scale_required",
        "agricultural_segment_required",
        "detailed_use_case_required",
        "agricultural_use_case_not_detected",
        "data_sources_required",
        "organization_evidence_required",
        "consumer_email_requires_public_profile",
        "consumer_email_requires_phone",
        "consumer_email_requires_operational_scale",
    }
    threshold = 82 if domain_classification == "consumer" else 72
    approved = score >= threshold and not any(code in hard_failure_codes for code in reason_codes)
    status = "preapproved_pending_email" if approved else "rejected"

    return VerificationDecision(
        approved=approved,
        status=status,
        score=min(score, 100),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        email_domain=email_domain,
        domain_classification=domain_classification,
        website_domain=website_domain,
        evidence_digest=_evidence_digest(payload),
    )
