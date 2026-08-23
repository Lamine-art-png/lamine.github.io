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


class EvidenceReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedEvidenceReference:
    evidence_id: str
    evidence_type: str


def validate_evidence_references(
    db: Session,
    *,
    tenant_id: str,
    evidence_ids: list[str],
    allowed_types: Iterable[str] | None = None,
) -> list[ValidatedEvidenceReference]:
    """Resolve every supplied ID inside the active tenant or fail without leakage.

    ``allowed_types`` constrains which durable record classes may prove the
    requested transition. A missing record and a record owned by another tenant
    intentionally produce the same customer-visible error.
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
        for row in db.query(EvidenceRecord.id).filter(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.id.in_(normalized),
        ).all():
            resolved[str(row[0])] = "evidence_record"
    if "field_observation" in selected_types:
        for row in db.query(FieldObservation.id).filter(
            FieldObservation.tenant_id == tenant_id,
            FieldObservation.id.in_(normalized),
        ).all():
            resolved[str(row[0])] = "field_observation"
    if "execution_verification" in selected_types:
        for row in db.query(ExecutionVerification.id).filter(
            ExecutionVerification.tenant_id == tenant_id,
            ExecutionVerification.id.in_(normalized),
        ).all():
            resolved[str(row[0])] = "execution_verification"

    unresolved = [value for value in normalized if value not in resolved]
    if unresolved:
        raise EvidenceReferenceError("One or more evidence references are unavailable in the active organization")
    return [ValidatedEvidenceReference(evidence_id=value, evidence_type=resolved[value]) for value in normalized]
