"""Shared constants and rule-pack metadata for the compliance kernel."""

FEATURE_FLAG = "CALIFORNIA_COMPLIANCE_PACK_ENABLED"
TRUTH_LABELS = {"measured", "reported", "estimated", "calculated", "AI-inferred"}
DISCLAIMER = (
    "Compliance readiness is decision support only. Direct regulatory filing is out of scope; "
    "all submissions require customer review and authorized filing outside AGRO-AI."
)
APPROVED_FIXTURE_TENANT_ID = "org-ca-vineyard-001"

RULE_PACKS = {
    "california_sgma_v0_1": {
        "pack_id": "california_sgma_v0_1",
        "jurisdiction": "California",
        "status": "internal_alpha_pending_external_validation",
        "enabled": True,
        "workflow_type": "gears_groundwater_extractor_readiness",
        "version": "0.1.0",
        "required_fields": ["owner_details", "well_identifier", "monthly_groundwater_extraction_volumes", "measurement_method"],
        "thresholds": {"water_budget_remaining_pct_alert": 15, "stale_calibration_days": 365, "required_groundwater_months": 12},
        "external_validation": False,
    },
    "california_sgma_gsa_v0_1": {
        "pack_id": "california_sgma_gsa_v0_1",
        "jurisdiction": "California",
        "status": "internal_alpha_pending_external_validation",
        "enabled": True,
        "workflow_type": "sgma_gsa_annual_report_readiness",
        "version": "0.1.0",
        "required_fields": ["owner_details", "well_identifier", "monthly_groundwater_extraction_volumes", "measurement_method"],
        "thresholds": {"water_budget_remaining_pct_alert": 15, "stale_calibration_days": 365, "required_groundwater_months": 12},
        "external_validation": False,
    },
    "arizona_groundwater_alpha": {
        "pack_id": "arizona_groundwater_alpha",
        "jurisdiction": "Arizona",
        "status": "disabled_alpha",
        "enabled": False,
        "workflow_type": "research_readiness",
        "version": "0.0.1-alpha",
        "required_fields": [],
        "thresholds": {},
        "external_validation": False,
    },
    "global_research_template": {
        "pack_id": "global_research_template",
        "jurisdiction": "Global",
        "status": "disabled_research_only",
        "enabled": False,
        "workflow_type": "research_readiness",
        "version": "0.0.1-research",
        "required_fields": [],
        "thresholds": {},
        "external_validation": False,
    },
}

ACTIVE_PACK_ID = "california_sgma_v0_1"
