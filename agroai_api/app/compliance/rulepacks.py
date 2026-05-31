"""Jurisdiction pack catalog for the global water compliance kernel."""
from __future__ import annotations

from app.compliance.constants import DISCLAIMER

CALIFORNIA_PACK = {
    "pack_id": "us_ca_sgma_gears",
    "version": "0.2.0",
    "country_code": "US",
    "region": "California",
    "authority": "California SGMA / GEARS reporting authorities",
    "authority_name": "California SGMA / GEARS reporting authorities",
    "effective_date": "2026-01-01",
    "workflow_types": ["gears_groundwater_extractor_readiness", "sgma_gsa_annual_report_readiness"],
    "legal_review_status": "approved",
    "enabled": True,
    "required_fields": ["reporting_year", "owner_details", "well_identifier", "well_location", "monthly_groundwater_extraction_volumes", "measurement_method"],
    "conditional_fields": [{"field": "agent_authorization_evidence", "required_when": "reporting_agent_details present"}],
    "validation_rules": ["truth_label_required", "tenant_scope_required", "estimated_values_not_certified", "agent_authorization_when_agent_present"],
    "deadlines": {"gears_groundwater_extractor_readiness": "jurisdiction_configured", "sgma_gsa_annual_report_readiness": "jurisdiction_configured"},
    "warning_thresholds": {"stale_calibration_days": 365, "telemetry_gap_days": 14, "water_budget_remaining_pct": 15},
    "export_schema": ["json", "csv", "xlsx", "pdf"],
    "disclaimer": DISCLAIMER,
    "source_references": ["AGRO-AI_SGMA_GEARS_Data_Dictionary.xlsx pending workspace availability", "California SGMA / GEARS prompt fields from PR 52"],
    "last_reviewed_date": "2026-05-31",
}

ARIZONA_ALPHA_PACK = {
    "pack_id": "us_az_groundwater_alpha",
    "version": "0.1.0-alpha",
    "country_code": "US",
    "region": "Arizona",
    "authority": "Arizona Department of Water Resources",
    "authority_name": "Arizona Department of Water Resources",
    "effective_date": "2026-01-01",
    "workflow_types": ["az_groundwater_withdrawal_readiness", "az_active_management_area_readiness"],
    "legal_review_status": "alpha_internal_review",
    "enabled": False,
    "required_fields": ["reporting_year", "owner_details", "well_identifier", "well_location", "withdrawal_volumes", "water_use_category", "measurement_method"],
    "conditional_fields": [{"field": "ama_or_ina_area", "required_when": "asset located in Arizona regulated groundwater area"}],
    "validation_rules": ["truth_label_required", "tenant_scope_required", "legal_review_required_before_enablement"],
    "deadlines": {"az_groundwater_withdrawal_readiness": "research_only_pending_legal_review"},
    "warning_thresholds": {"stale_calibration_days": 365, "telemetry_gap_days": 14},
    "export_schema": ["json", "csv", "xlsx", "pdf"],
    "disclaimer": DISCLAIMER,
    "source_references": ["AGRO-AI_Global_Water_Compliance_Atlas.xlsx pending workspace availability"],
    "last_reviewed_date": "2026-05-31",
}


def research_pack(pack_id: str, country_code: str, region: str, authority: str) -> dict:
    return {
        "pack_id": pack_id,
        "version": "0.0.1-research",
        "country_code": country_code,
        "region": region,
        "authority": authority,
        "authority_name": authority,
        "effective_date": None,
        "workflow_types": [],
        "legal_review_status": "research_only_legal_review_required",
        "enabled": False,
        "required_fields": [],
        "conditional_fields": [],
        "validation_rules": ["disabled_until_legal_review", "no_customer_claims", "no_direct_filing"],
        "deadlines": {},
        "warning_thresholds": {},
        "export_schema": ["json"],
        "disclaimer": DISCLAIMER,
        "source_references": ["AGRO-AI_Global_Water_Compliance_Atlas.xlsx pending workspace availability"],
        "last_reviewed_date": "2026-05-31",
    }


RESEARCH_ONLY_PACKS = [
    research_pack("us_co_water_rights_research", "US", "Colorado", "Colorado water administration"),
    research_pack("us_tx_groundwater_district_research", "US", "Texas", "Texas groundwater conservation districts"),
    research_pack("us_wa_water_resources_research", "US", "Washington", "Washington water resources"),
    research_pack("au_mdb_water_accounting_research", "AU", "Murray-Darling Basin", "Murray-Darling Basin water accounting"),
    research_pack("es_river_basin_authority_research", "ES", "Spain", "Spain river basin authorities"),
    research_pack("cl_dga_water_rights_research", "CL", "Chile", "Chile DGA water rights"),
]

GLOBAL_PACK_CATALOG = [CALIFORNIA_PACK, ARIZONA_ALPHA_PACK, *RESEARCH_ONLY_PACKS]
