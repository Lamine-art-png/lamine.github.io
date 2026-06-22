"""Generic Assurance rule packs and validation helpers."""
from __future__ import annotations

from typing import Any


ASSURANCE_DISCLAIMER = (
    "This package reflects audit readiness decision support only. AGRO-AI prepares an evidence package "
    "for reviewer evaluation and does not claim live-source completeness unless a configured live source supplied the record."
)


DEFAULT_RULE_PACKS: dict[str, dict[str, Any]] = {
    "waterops_generic_v0_1": {
        "id": "waterops_generic_v0_1",
        "scope": "standard",
        "version": "0.1.0",
        "status": "active",
        "required_evidence_types": ["water_budget", "water_measurement"],
        "checklist": [
            {"key": "water_budget_available", "section": "water_proof", "evidence_types": ["water_budget"], "severity": "required"},
            {"key": "water_measurement_available", "section": "water_proof", "evidence_types": ["water_measurement"], "severity": "required"},
        ],
        "validation_rules": {"minimum_truth_labels": ["measured", "reported", "calculated", "estimated"], "no_certification_claims": True},
        "scoring_weights": {"water_proof": 0.35, "risk": 0.15},
        "disclaimer_text": ASSURANCE_DISCLAIMER,
    },
    "eudr_supplier_readiness_v0_1": {
        "id": "eudr_supplier_readiness_v0_1",
        "scope": "standard",
        "version": "0.1.0",
        "status": "active",
        "required_evidence_types": ["farm_boundary", "traceability_record"],
        "checklist": [
            {"key": "farm_boundary_reference", "section": "farm_summary", "evidence_types": ["farm_boundary"], "severity": "required"},
            {"key": "lot_traceability_events", "section": "traceability_proof", "evidence_types": ["traceability_record"], "severity": "required"},
        ],
        "validation_rules": {"geolocation_required_when_available": True, "no_deforestation_claim_without_standard": True},
        "scoring_weights": {"farm_summary": 0.15, "traceability_proof": 0.25, "risk": 0.10},
        "disclaimer_text": ASSURANCE_DISCLAIMER,
    },
    "buyer_input_records_v0_1": {
        "id": "buyer_input_records_v0_1",
        "scope": "buyer",
        "version": "0.1.0",
        "status": "active",
        "required_evidence_types": ["input_application_record"],
        "checklist": [
            {"key": "input_application_records", "section": "input_proof", "evidence_types": ["input_application_record"], "severity": "required"},
            {"key": "input_product_identity", "section": "input_proof", "record_type": "input_application", "field": "product_name", "severity": "required"},
        ],
        "validation_rules": {"pesticide_and_fertilizer_records_supported": True},
        "scoring_weights": {"input_proof": 0.30, "risk": 0.10},
        "disclaimer_text": ASSURANCE_DISCLAIMER,
    },
    "farm_finance_risk_pack_v0_1": {
        "id": "farm_finance_risk_pack_v0_1",
        "scope": "standard",
        "version": "0.1.0",
        "status": "active",
        "required_evidence_types": ["risk_context"],
        "checklist": [
            {"key": "risk_context_available", "section": "risk_score", "evidence_types": ["risk_context"], "severity": "recommended"},
        ],
        "validation_rules": {"risk_language_only": True, "no_credit_decision": True},
        "scoring_weights": {"risk": 0.20},
        "disclaimer_text": ASSURANCE_DISCLAIMER,
    },
}


def get_rule_pack(pack_id: str) -> dict[str, Any]:
    try:
        return DEFAULT_RULE_PACKS[pack_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported assurance rule pack: {pack_id}") from exc


def validate_rule_pack_ids(pack_ids: list[str] | None) -> list[str]:
    selected = pack_ids or list(DEFAULT_RULE_PACKS)
    unknown = [pack_id for pack_id in selected if pack_id not in DEFAULT_RULE_PACKS]
    if unknown:
        raise ValueError(f"Unsupported assurance rule pack(s): {', '.join(unknown)}")
    return selected


def checklist_for(pack_ids: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for pack_id in pack_ids:
        for item in DEFAULT_RULE_PACKS[pack_id]["checklist"]:
            items.append({"rule_pack_id": pack_id, **item})
    return items
