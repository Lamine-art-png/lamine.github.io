"""Tenant-safe validation for evidence references used by decision lifecycle transitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.execution_verification import ExecutionVerification
from app.models.field_intelligence import FieldObservation
from app.models.operational_records import EvidenceRecord


MAX_EVIDENCE_REFERENCES = 50
EVIDENCE_REFERENCE_TYPES = {"evidence_record", "field_observation", "execution_verification"}
_ACCEPTED_RECORD_QUALITY = {"verified", "accepted", "validated", "complete", "good", "ok", "usable", "live"}
_ACCEPTED_OBSERVATION_STATUS = {"completed"}
_ACCEPTED_VERIFICATION_STATUS = {"complete", "verified"}


class EvidenceReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedEvidenceReference:
    evidence_id: str
    evidence_type: str


def _token(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def validate_evidence_references(
    db: Session,
    *,
    tenant_id: str,
    evidence_ids: list[str],
    allowed_types: Iterable[str] | None = None,
) -> list[ValidatedEvidenceReference]:
    """Resolve every supplied ID inside the active tenant or fail without leakage.

    Existence is not enough for lifecycle proof. Evidence records must carry an
    accepted/verified quality state, Field Intelligence observations must be
    completed, and legacy execution-verification rows must be complete/verified.
    A missing, foreign, unfinished, or rejected record intentionally produces
    the same customer-visible error so the validator does not leak record state.
    """
    normalized = list(dict.fromkeys(str(value or "").strip() for value in evidence_ids if str(value or "").strip()))
    if not normalized:
        raise EvidenceReferenceError("At least one evidence reference is required")
    if len(normalized) > MAX_EVIDENCE_REFERENCES:
        raise EvidenceReferenceError(f"At most {MAX_EVIDENCE_REFERENCES} evidence references are allowed")

    selected_types = set(allowed_types or EVIDENCE_REFERENCE_TYPES)
    invalid_types = selected_types - EVIDENCE_REFERENCE_TYPES
    if invalid_types:
        raise ValueError(f"Unsupported evidence reference types: {sorted(invalid_types)}")

    resolved: dict[str, str] = {}
    if "evidence_record" in selected_types:
        for row in db.query(EvidenceRecord.id, EvidenceRecord.quality_status).filter(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.id.in_(normalized),
        ).all():
            if _token(row[1]) in _ACCEPTED_RECORD_QUALITY:
                resolved[str(row[0])] = "evidence_record"
    if "field_observation" in selected_types:
        for row in db.query(FieldObservation.id, FieldObservation.status).filter(
            FieldObservation.tenant_id == tenant_id,
            FieldObservation.id.in_(normalized),
        ).all():
            if _token(row[1]) in _ACCEPTED_OBSERVATION_STATUS:
                resolved[str(row[0])] = "field_observation"
    if "execution_verification" in selected_types:
        for row in db.query(ExecutionVerification.id, ExecutionVerification.verification_status).filter(
            ExecutionVerification.tenant_id == tenant_id,
            ExecutionVerification.id.in_(normalized),
        ).all():
            if _token(row[1]) in _ACCEPTED_VERIFICATION_STATUS:
                resolved[str(row[0])] = "execution_verification"

    unresolved = [value for value in normalized if value not in resolved]
    if unresolved:
        raise EvidenceReferenceError("One or more evidence references are unavailable in the active organization")
    return [ValidatedEvidenceReference(evidence_id=value, evidence_type=resolved[value]) for value in normalized]
