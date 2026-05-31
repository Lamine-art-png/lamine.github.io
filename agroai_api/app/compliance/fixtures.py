"""Representative California vineyard fixture used by tests and demo endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from app.compliance.constants import DISCLAIMER

ORG_ID = "org-ca-vineyard-001"
TENANT_B = "org-ca-vineyard-002"
REPORTING_PERIOD = "2026"

VINEYARD_FIXTURE = {
    "organization": {
        "id": ORG_ID,
        "name": "Sierra Verde Vineyard LLC",
        "owner": "Marisol Reyes",
        "operator": "AGRO-AI Operations",
        "reporting_agent": "North Valley Water Reporting Services",
        "authorization_artifact_id": "ev-agent-auth-2026",
        "consent_scope": "GEARS and SGMA evidence package preparation for reporting year 2026",
        "reviewer_role": "water_compliance_reviewer",
    },
    "jurisdictions": [
        {
            "id": "jur-ca-sv-2026-gears",
            "organization_id": ORG_ID,
            "state": "CA",
            "county": "Sonoma",
            "basin": "Santa Rosa Plain",
            "subbasin": "Santa Rosa Plain Subbasin",
            "gsa": "Santa Rosa Plain GSA",
            "district": "Sierra Verde Irrigation District",
            "jurisdiction_pack": "california_compliance_pack",
            "pack_version": "0.1.0",
            "reporting_year": 2026,
            "reporting_deadline": "2027-02-01",
            "workflow_type": "gears_groundwater_extractor_readiness",
        },
        {
            "id": "jur-ca-sv-2026-sgma",
            "organization_id": ORG_ID,
            "state": "CA",
            "county": "Sonoma",
            "basin": "Santa Rosa Plain",
            "subbasin": "Santa Rosa Plain Subbasin",
            "gsa": "Santa Rosa Plain GSA",
            "district": "Sierra Verde Irrigation District",
            "jurisdiction_pack": "california_compliance_pack",
            "pack_version": "0.1.0",
            "reporting_year": 2026,
            "reporting_deadline": "2027-04-01",
            "workflow_type": "sgma_gsa_annual_report_readiness",
        },
    ],
    "parcels": [
        {"id": "parcel-sv-101", "organization_id": ORG_ID, "apn": "123-456-010", "geometry_ref": "s3://agroai-evidence/sv/parcel-101.geojson", "county": "Sonoma", "place_of_use": "Block A North vineyard"},
        {"id": "parcel-sv-102", "organization_id": ORG_ID, "apn": "123-456-011", "geometry_ref": "s3://agroai-evidence/sv/parcel-102.geojson", "county": "Sonoma", "place_of_use": "Block B South vineyard"},
    ],
    "wells": [
        {"id": "well-sv-01", "organization_id": ORG_ID, "parcel_id": "parcel-sv-101", "well_identifier": "SV-WELL-01", "latitude": 38.4389, "longitude": -122.7167, "well_capacity_gpm": 420, "purpose_of_use": "irrigation"},
        {"id": "well-sv-02", "organization_id": ORG_ID, "parcel_id": "parcel-sv-102", "well_identifier": "SV-WELL-02", "latitude": 38.4314, "longitude": -122.7211, "well_capacity_gpm": 360, "purpose_of_use": "irrigation"},
    ],
    "meters": [
        {"id": "meter-sv-01", "organization_id": ORG_ID, "well_id": "well-sv-01", "meter_identifier": "MTR-SV-01", "manufacturer": "McCrometer", "serial_number": "MC-CA-10001", "measurement_method": "propeller flow meter", "calibration_date": "2026-01-15", "calibration_document_ref": "ev-cal-mtr-01"},
        {"id": "meter-sv-02", "organization_id": ORG_ID, "well_id": "well-sv-02", "meter_identifier": "MTR-SV-02", "manufacturer": "Seametrics", "serial_number": "SM-CA-20002", "measurement_method": "magnetic flow meter", "calibration_date": "2024-11-01", "calibration_document_ref": "ev-cal-mtr-02"},
    ],
    "measurements": [],
    "reconciliation": [
        {
            "id": "recon-sv-2026-05-14",
            "organization_id": ORG_ID,
            "recommendation_id": "rec-sv-0514",
            "approved_recommendation_id": "approval-sv-0514",
            "scheduled_event_id": "schedule-sv-0514",
            "controller_command_id": "cmd-wiseconn-0514",
            "applied_event_id": "applied-sv-0514",
            "measured_extraction_id": "meas-sv-w1-2026-05",
            "recommended_volume_af": 3.10,
            "applied_volume_af": 3.42,
            "measured_extraction_af": 3.50,
            "variance_af": 0.32,
            "variance_pct": 10.32,
            "truth_labels": {"recommended_volume_af": "AI-inferred", "applied_volume_af": "reported", "measured_extraction_af": "measured", "variance_af": "calculated"},
            "operator_note": "Controller ran 18 minutes longer due to valve pressure stabilization.",
        }
    ],
    "water_budgets": [
        {"id": "budget-sv-2026", "organization_id": ORG_ID, "reporting_period": REPORTING_PERIOD, "water_source": "groundwater", "allocation_af": 42.0, "extraction_af": 31.1, "irrigation_application_af": 29.8, "remaining_balance_af": 10.9, "projected_balance_af": -2.4, "threshold_status": "alert"}
    ],
    "evidence": [
        {"id": "ev-agent-auth-2026", "organization_id": ORG_ID, "artifact_type": "agent_authorization", "file_ref": "s3://agroai-evidence/sv/agent-auth-2026.pdf", "truth_label": "reported", "review_status": "accepted"},
        {"id": "ev-cal-mtr-01", "organization_id": ORG_ID, "artifact_type": "calibration_certificate", "file_ref": "s3://agroai-evidence/sv/mtr-01-cal.pdf", "truth_label": "reported", "review_status": "accepted"},
        {"id": "ev-gap-note-june", "organization_id": ORG_ID, "artifact_type": "methodology_note", "file_ref": "s3://agroai-evidence/sv/june-telemetry-gap.md", "truth_label": "reported", "review_status": "needs_review"},
    ],
    "audit_log": [
        {"id": "audit-001", "organization_id": ORG_ID, "event": "fixture_loaded", "actor": "system", "timestamp": "2026-07-01T00:00:00Z"},
        {"id": "audit-002", "organization_id": ORG_ID, "event": "readiness_checked", "actor": "water_compliance_reviewer", "timestamp": "2026-07-15T16:30:00Z"},
    ],
    "rule_pack": {
        "pack_id": "california_compliance_pack",
        "version": "0.1.0",
        "effective_date": "2026-01-01",
        "workflow_types": ["gears_groundwater_extractor_readiness", "sgma_gsa_annual_report_readiness"],
        "required_fields": ["reporting_year", "owner_details", "well_identifier", "well_location", "monthly_groundwater_extraction_volumes", "measurement_method"],
        "conditional_fields": [{"field": "agent_authorization_evidence", "required_when": "reporting_agent_details present"}],
        "validation_rules": ["truth_label_required", "tenant_scoped_queries", "estimated_values_must_not_be_certified"],
        "deadlines": {"gears_groundwater_extractor_readiness": "2027-02-01", "sgma_gsa_annual_report_readiness": "2027-04-01"},
        "warning_thresholds": {"stale_calibration_days": 365, "telemetry_gap_days": 14, "water_budget_remaining_pct": 15},
        "export_schema": ["json", "csv", "xlsx", "pdf"],
        "disclaimer_text": DISCLAIMER,
    },
}

for month, w1, w2 in [(1, 4.1, 3.6), (2, 4.4, 3.8), (3, 5.0, 4.2), (4, 5.7, 4.9), (5, 6.2, 5.4), (6, 5.9, None)]:
    VINEYARD_FIXTURE["measurements"].append({
        "id": f"meas-sv-w1-2026-{month:02d}", "organization_id": ORG_ID, "asset_type": "well", "asset_id": "well-sv-01", "measurement_type": "groundwater_extraction", "value": w1, "unit": "acre_feet", "method": "flow_meter_totalizer", "truth_label": "measured", "source_system": "WiseConn", "source_timestamp": f"2026-{month:02d}-28T23:59:00Z", "ingestion_timestamp": "2026-07-01T00:00:00Z", "quality_status": "accepted", "reporting_period": REPORTING_PERIOD, "correction_lineage": []})
    if w2 is not None:
        VINEYARD_FIXTURE["measurements"].append({
            "id": f"meas-sv-w2-2026-{month:02d}", "organization_id": ORG_ID, "asset_type": "well", "asset_id": "well-sv-02", "measurement_type": "groundwater_extraction", "value": w2, "unit": "acre_feet", "method": "flow_meter_totalizer", "truth_label": "measured", "source_system": "Talgil", "source_timestamp": f"2026-{month:02d}-28T23:59:00Z", "ingestion_timestamp": "2026-07-01T00:00:00Z", "quality_status": "accepted", "reporting_period": REPORTING_PERIOD, "correction_lineage": []})
    else:
        VINEYARD_FIXTURE["measurements"].append({
            "id": "meas-sv-w2-2026-06-est", "organization_id": ORG_ID, "asset_type": "well", "asset_id": "well-sv-02", "measurement_type": "groundwater_extraction", "value": 5.1, "unit": "acre_feet", "method": "telemetry_gap_interpolation", "truth_label": "estimated", "source_system": "AGRO-AI", "source_timestamp": "2026-06-28T23:59:00Z", "ingestion_timestamp": "2026-07-01T00:00:00Z", "quality_status": "gap_estimate", "reporting_period": REPORTING_PERIOD, "correction_lineage": [{"reason": "missing telemetry gap", "missing_window": "2026-06-12/2026-06-20"}]})
