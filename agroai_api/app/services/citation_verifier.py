"""Citation verification for tenant-scoped AGRO-AI intelligence outputs."""
from __future__ import annotations

from typing import Any

from app.schemas.ai import ToolCitation, VerificationResult


def normalize_confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low"}:
        return text
    return "low"


def downgrade_confidence(value: Any) -> str:
    current = normalize_confidence(value)
    if current == "high":
        return "medium"
    return "low"


def verify_citations(
    *,
    citations: list[ToolCitation],
    tenant_id: str,
    workspace_id: str | None,
    result: dict[str, Any],
) -> tuple[VerificationResult, dict[str, Any]]:
    warnings: list[str] = []
    valid: list[ToolCitation] = []

    for citation in citations:
        if citation.tenant_id and citation.tenant_id != tenant_id:
            warnings.append(f"Citation {citation.source_id} does not belong to this tenant.")
            continue
        if workspace_id and citation.workspace_id and citation.workspace_id != workspace_id:
            warnings.append(f"Citation {citation.source_id} does not belong to this workspace.")
            continue
        valid.append(citation)

    if not valid:
        warnings.append("No verified citations support this result.")

    if warnings:
        result = {**result, "confidence": downgrade_confidence(result.get("confidence"))}

    verification = VerificationResult(
        status="verified" if valid and not warnings else "partial" if valid or warnings else "unavailable",
        missing_data=result.get("missing_data") or [],
        risk_flags=warnings,
        citations=valid,
    )
    return verification, result
