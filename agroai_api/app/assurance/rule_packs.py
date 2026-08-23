"""Generic Assurance rule packs and validation helpers."""
from __future__ import annotations

from typing import Any


ASSURANCE_DISCLAIMER = (
    "This audit readiness evidence package reflects evidence readiness decision support only. AGRO-AI organizes supporting records "
    "for reviewer evaluation; it is not a certification, legal compliance determination, regulatory approval, "
    "or filing, and it does not claim live-source completeness unless a configured live source supplied the record."
)


DEFAULT_RULE_PACKS: dict[str, dict[str, Any]] = {
    "water_assurance_generic_v1": {
        "id": "water_assurance_generic_v1",
        "title": "Water assurance",
        "customer_description": "Organize water source, measurement, execution, and verification records.",
        "domain": "water",
        "scope": "standard",
        "version": "1.0.0",
        "status": "active",
        "source_reference": "AGRO-AI generic water evidence readiness model",
        "effective_date": "2026-08-16",
        "aliases": ["waterops_generic_v0_1"],
        "required_evidence_types": ["water_source", "water_measurement", "irrigation_event", "verification"],
        "checklist": [
            {"key": "water_source_scope", "title": "Water source and field scope", "domain": "water", "section": "water_proof", "evidence_types": ["water_source", "farm_boundary"], "optional_evidence_types": ["well", "meter"], "severity": "required", "blocking": True, "review_required": True, "explanation": "Identifies where the water evidence applies."},
            {"key": "water_measurement", "title": "Applied-water measurement", "domain": "water", "section": "water_proof", "evidence_types": ["water_measurement", "flow_measurement", "controller_event"], "optional_evidence_types": ["runtime", "flow"], "severity": "required", "blocking": True, "review_required": True, "explanation": "Provides a traceable measured or reported water record for the selected period."},
            {"key": "irrigation_execution", "title": "Irrigation execution record", "domain": "operational_execution", "section": "water_proof", "evidence_types": ["irrigation_event", "operational_execution"], "optional_evidence_types": ["recommendation", "approval", "task"], "severity": "required", "blocking": True, "review_required": True, "explanation": "Connects planned or approved irrigation to observed execution."},
            {"key": "water_verification", "title": "Water activity verification", "domain": "verification", "section": "water_proof", "evidence_types": ["verification", "field_verification", "field_observation"], "optional_evidence_types": ["photo", "variance"], "severity": "required", "blocking": True, "review_required": True, "explanation": "Shows how execution was checked after the activity."},
        ],
        "validation_rules": {"deterministic": True, "stale_after_days": 365, "no_certification_claims": True},
        "scoring_weights": {"water_proof": 1.0},
        "disclaimer_text": ASSURANCE_DISCLAIMER,
    },
    "buyer_input_records_v1": {
        "id": "buyer_input_records_v1",
        "title": "Buyer input records",
        "customer_description": "Organize application records and their supporting product documents for buyer review.",
        "domain": "inputs",
        "scope": "buyer",
        "version": "1.0.0",
        "status": "active",
        "source_reference": "Customer-selected buyer record requirements",
        "effective_date": "2026-08-16",
        "aliases": ["buyer_input_records_v0_1"],
        "required_evidence_types": ["input_application_record", "input_supporting_document"],
        "checklist": [
            {"key": "input_application_record", "title": "Input application record", "domain": "inputs", "section": "input_proof", "evidence_types": ["input_application_record"], "optional_evidence_types": ["pesticide_application", "fertilizer_application"], "severity": "required", "blocking": True, "review_required": True, "explanation": "Records what was applied, where, and when."},
            {"key": "input_supporting_record", "title": "Supporting input documentation", "domain": "inputs", "section": "input_proof", "evidence_types": ["input_supporting_document", "product_document"], "optional_evidence_types": ["label_reference", "invoice"], "severity": "required", "blocking": True, "review_required": True, "explanation": "Links the application record to its supporting source document."},
        ],
        "validation_rules": {"deterministic": True, "required_application_fields": ["product_name", "applied_at"], "no_chemical_recommendations": True},
        "scoring_weights": {"input_proof": 1.0},
        "disclaimer_text": ASSURANCE_DISCLAIMER,
    },
    "operational_execution_proof_v1": {
        "id": "operational_execution_proof_v1",
        "title": "Operational execution proof",
        "customer_description": "Connect recommendations, human approvals, work orders, field execution, and verification.",
        "domain": "operational_execution",
        "scope": "standard",
        "version": "1.0.0",
        "status": "active",
        "source_reference": "AGRO-AI operational execution provenance model",
        "effective_date": "2026-08-16",
        "aliases": [],
        "required_evidence_types": ["recommendation", "approval", "task", "operational_execution", "verification"],
        "checklist": [
            {"key": "recommendation", "title": "Grounded recommendation", "domain": "operational_execution", "section": "operational_proof", "evidence_types": ["recommendation"], "optional_evidence_types": [], "severity": "required", "blocking": True, "review_required": True, "explanation": "Preserves the recommendation that initiated the work."},
            {"key": "human_approval", "title": "Human approval", "domain": "operational_execution", "section": "operational_proof", "evidence_types": ["approval"], "optional_evidence_types": [], "severity": "required", "blocking": True, "review_required": True, "explanation": "Shows the accountable human decision before consequential work."},
            {"key": "scheduled_task", "title": "Scheduled task or work order", "domain": "operational_execution", "section": "operational_proof", "evidence_types": ["task", "work_order"], "optional_evidence_types": [], "severity": "required", "blocking": True, "review_required": True, "explanation": "Links approval to the assigned field work."},
            {"key": "field_execution", "title": "Field execution record", "domain": "operational_execution", "section": "operational_proof", "evidence_types": ["operational_execution", "field_observation", "controller_event"], "optional_evidence_types": ["photo", "machine_signal"], "severity": "required", "blocking": True, "review_required": True, "explanation": "Shows what happened in the field or controller system."},
            {"key": "execution_verification", "title": "Execution verification", "domain": "verification", "section": "operational_proof", "evidence_types": ["verification", "field_verification"], "optional_evidence_types": ["variance"], "severity": "required", "blocking": True, "review_required": True, "explanation": "Closes the loop with a verified outcome."},
        ],
        "validation_rules": {"deterministic": True, "ordered_provenance": ["recommendation", "approval", "task", "operational_execution", "verification"]},
        "scoring_weights": {"operational_proof": 1.0},
        "disclaimer_text": ASSURANCE_DISCLAIMER,
    },
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


CUSTOMER_RULE_PACK_IDS = [
    "water_assurance_generic_v1",
    "buyer_input_records_v1",
    "operational_execution_proof_v1",
]


def get_rule_pack(pack_id: str) -> dict[str, Any]:
    try:
        return DEFAULT_RULE_PACKS[pack_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported assurance rule pack: {pack_id}") from exc


def validate_rule_pack_ids(pack_ids: list[str] | None) -> list[str]:
    selected = list(DEFAULT_RULE_PACKS) if pack_ids is None else list(pack_ids)
    if not selected:
        raise ValueError("Select at least one supported assurance rule pack")
    if len(selected) != len(set(selected)):
        raise ValueError("Assurance rule packs must not be selected more than once")
    unknown = [pack_id for pack_id in selected if pack_id not in DEFAULT_RULE_PACKS]
    if unknown:
        raise ValueError(f"Unsupported assurance rule pack(s): {', '.join(unknown)}")
    return selected


def checklist_for(pack_ids: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for pack_id in pack_ids:
        pack = DEFAULT_RULE_PACKS[pack_id]
        for item in pack["checklist"]:
            items.append({
                "rule_pack_id": pack_id,
                "rule_pack_version": pack["version"],
                "title": item.get("title") or item["key"].replace("_", " ").title(),
                "domain": item.get("domain") or item.get("section", "assurance").replace("_proof", ""),
                "optional_evidence_types": item.get("optional_evidence_types", []),
                "blocking": item.get("blocking", item.get("severity", "required") == "required"),
                "explanation": item.get("explanation") or "Supporting evidence is required for reviewer evaluation.",
                "review_required": item.get("review_required", True),
                **item,
            })
    return items


def rule_pack_versions(pack_ids: list[str]) -> dict[str, str]:
    return {pack_id: get_rule_pack(pack_id)["version"] for pack_id in pack_ids}
