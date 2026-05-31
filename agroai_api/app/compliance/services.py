"""Compliance kernel services for readiness, validation, and exports."""
from __future__ import annotations

import csv
import io
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any

from app.compliance.constants import DISCLAIMER, TRUTH_LABELS
from app.compliance.fixtures import ORG_ID, VINEYARD_FIXTURE

EXPORTS: dict[str, dict[str, Any]] = {}
CUSTOM_MEASUREMENTS: list[dict[str, Any]] = []
CUSTOM_EVIDENCE: list[dict[str, Any]] = []


def _tenant_id(organization_id: str | None = None) -> str:
    return organization_id or ORG_ID


def _scoped(items: list[dict[str, Any]], organization_id: str | None) -> list[dict[str, Any]]:
    tenant = _tenant_id(organization_id)
    return [deepcopy(item) for item in items if item.get("organization_id") == tenant]


def truth_label_valid(label: str) -> bool:
    return label in TRUTH_LABELS


def add_measurement(payload: dict[str, Any], organization_id: str | None = None) -> dict[str, Any]:
    tenant = _tenant_id(organization_id or payload.get("organization_id"))
    label = payload.get("truth_label")
    if not truth_label_valid(label):
        raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
    record = {
        "id": payload.get("id") or f"meas-{uuid.uuid4().hex[:12]}",
        "organization_id": tenant,
        "asset_type": payload["asset_type"],
        "asset_id": payload["asset_id"],
        "measurement_type": payload["measurement_type"],
        "value": float(payload["value"]),
        "unit": payload["unit"],
        "method": payload["method"],
        "truth_label": label,
        "source_system": payload["source_system"],
        "source_timestamp": payload["source_timestamp"],
        "ingestion_timestamp": datetime.now(timezone.utc).isoformat(),
        "quality_status": payload.get("quality_status", "pending_review"),
        "reporting_period": str(payload["reporting_period"]),
        "confidence": payload.get("confidence"),
        "correction_lineage": payload.get("correction_lineage", []),
    }
    CUSTOM_MEASUREMENTS.append(record)
    return deepcopy(record)


def list_measurements(organization_id: str | None = None) -> list[dict[str, Any]]:
    return _scoped(VINEYARD_FIXTURE["measurements"] + CUSTOM_MEASUREMENTS, organization_id)


def list_assets(kind: str, organization_id: str | None = None) -> list[dict[str, Any]]:
    return _scoped(VINEYARD_FIXTURE[kind], organization_id)


def list_jurisdictions(organization_id: str | None = None) -> list[dict[str, Any]]:
    return _scoped(VINEYARD_FIXTURE["jurisdictions"], organization_id)


def list_evidence(organization_id: str | None = None) -> list[dict[str, Any]]:
    return _scoped(VINEYARD_FIXTURE["evidence"] + CUSTOM_EVIDENCE, organization_id)


def add_evidence(payload: dict[str, Any], organization_id: str | None = None) -> dict[str, Any]:
    label = payload.get("truth_label", "reported")
    if not truth_label_valid(label):
        raise ValueError("invalid truth_label")
    record = {
        "id": payload.get("id") or f"ev-{uuid.uuid4().hex[:12]}",
        "organization_id": _tenant_id(organization_id or payload.get("organization_id")),
        "artifact_type": payload["artifact_type"],
        "file_ref": payload["file_ref"],
        "truth_label": label,
        "review_status": payload.get("review_status", "pending_review"),
        "notes": payload.get("notes"),
    }
    CUSTOM_EVIDENCE.append(record)
    return deepcopy(record)


def validate_required_fields(workflow_type: str, organization_id: str | None = None) -> list[str]:
    missing: list[str] = []
    org = VINEYARD_FIXTURE["organization"] if _tenant_id(organization_id) == ORG_ID else {}
    wells = list_assets("wells", organization_id)
    meters = list_assets("meters", organization_id)
    measurements = list_measurements(organization_id)
    evidence = list_evidence(organization_id)
    if not org.get("owner"):
        missing.append("owner_details")
    if not wells:
        missing.append("well_identifier")
    if any(well.get("latitude") is None or well.get("longitude") is None for well in wells):
        missing.append("well_location")
    if not measurements:
        missing.append("monthly_groundwater_extraction_volumes")
    if any(not meter.get("measurement_method") for meter in meters):
        missing.append("measurement_method")
    if workflow_type == "gears_groundwater_extractor_readiness" and org.get("reporting_agent"):
        if not any(ev.get("artifact_type") == "agent_authorization" for ev in evidence):
            missing.append("agent_authorization_evidence")
    return missing


def water_budget_status(organization_id: str | None = None) -> list[dict[str, Any]]:
    budgets = _scoped(VINEYARD_FIXTURE["water_budgets"], organization_id)
    for budget in budgets:
        budget["remaining_balance_af"] = round(budget["allocation_af"] - budget["extraction_af"], 2)
        remaining_pct = budget["remaining_balance_af"] / budget["allocation_af"] * 100 if budget["allocation_af"] else 0
        budget["remaining_pct"] = round(remaining_pct, 1)
        budget["threshold_status"] = "alert" if remaining_pct < 15 or budget["projected_balance_af"] < 0 else "ok"
        budget["truth_labels"] = {"remaining_balance_af": "calculated", "projected_balance_af": "calculated", "extraction_af": "measured"}
    return budgets


def reconciliation(organization_id: str | None = None) -> list[dict[str, Any]]:
    return _scoped(VINEYARD_FIXTURE["reconciliation"], organization_id)


def readiness(workflow_type: str = "gears_groundwater_extractor_readiness", organization_id: str | None = None) -> dict[str, Any]:
    missing_fields = validate_required_fields(workflow_type, organization_id)
    measurements = list_measurements(organization_id)
    meters = list_assets("meters", organization_id)
    missing_evidence = []
    warnings = []
    stale_telemetry = []
    anomalies = []
    if any(m.get("quality_status") == "gap_estimate" for m in measurements):
        stale_telemetry.append({"asset_id": "well-sv-02", "window": "2026-06-12/2026-06-20", "severity": "blocking", "truth_label": "estimated"})
        missing_evidence.append("manual_reading_evidence_for_june_gap")
    for meter in meters:
        cal = date.fromisoformat(meter["calibration_date"])
        if (date(2026, 7, 1) - cal).days > 365:
            warnings.append({"code": "stale_calibration", "meter_id": meter["id"], "calibration_date": meter["calibration_date"]})
    for budget in water_budget_status(organization_id):
        if budget["threshold_status"] == "alert":
            warnings.append({"code": "water_budget_threshold_alert", "budget_id": budget["id"], "projected_balance_af": budget["projected_balance_af"]})
    for row in reconciliation(organization_id):
        if abs(row["variance_pct"]) > 10:
            anomalies.append({"code": "application_variance", "reconciliation_id": row["id"], "variance_pct": row["variance_pct"]})
    blocking = missing_fields + [item["code"] if "code" in item else "stale_telemetry" for item in stale_telemetry]
    deductions = len(blocking) * 18 + len(warnings) * 6 + len(anomalies) * 5
    return {
        "workflow_type": workflow_type,
        "readiness_percentage": max(0, 100 - deductions),
        "readiness_status": "blocked" if blocking else ("warning" if warnings else "ready"),
        "blocking_defects": blocking,
        "warnings": warnings,
        "missing_evidence": missing_evidence,
        "stale_telemetry": stale_telemetry,
        "missing_required_fields": missing_fields,
        "unresolved_anomalies": anomalies,
        "upcoming_deadlines": [j for j in list_jurisdictions(organization_id) if j["workflow_type"] == workflow_type],
        "disclaimer": DISCLAIMER,
        "next_required_action": "Attach manual reading evidence for June telemetry gap before export review." if stale_telemetry else "Reviewer can approve the package for export.",
    }


def status(organization_id: str | None = None) -> dict[str, Any]:
    return {
        "enabled": True,
        "feature_flag": "CALIFORNIA_COMPLIANCE_PACK_ENABLED",
        "organization": deepcopy(VINEYARD_FIXTURE["organization"]) if _tenant_id(organization_id) == ORG_ID else {"id": _tenant_id(organization_id)},
        "rule_pack": deepcopy(VINEYARD_FIXTURE["rule_pack"]),
        "readiness": readiness(organization_id=organization_id),
    }


def _csv_export(package: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["section", "id", "field", "value", "truth_label"])
    for measurement in package["measurements"]:
        writer.writerow(["measurement", measurement["id"], "value", measurement["value"], measurement["truth_label"]])
    for budget in package["water_budgets"]:
        writer.writerow(["water_budget", budget["id"], "remaining_balance_af", budget["remaining_balance_af"], "calculated"])
    return out.getvalue()


def compose_export(export_type: str, workflow_type: str, organization_id: str | None = None) -> dict[str, Any]:
    package = {
        "id": f"export-{uuid.uuid4().hex[:10]}",
        "format": export_type,
        "workflow_type": workflow_type,
        "organization_id": _tenant_id(organization_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "jurisdictions": list_jurisdictions(organization_id),
        "assets": {"parcels": list_assets("parcels", organization_id), "wells": list_assets("wells", organization_id), "meters": list_assets("meters", organization_id)},
        "measurements": list_measurements(organization_id),
        "water_budgets": water_budget_status(organization_id),
        "reconciliation": reconciliation(organization_id),
        "readiness": readiness(workflow_type, organization_id),
        "provenance": {"source": "AGRO-AI compliance kernel", "truth_labels_required": sorted(TRUTH_LABELS), "direct_filing": False},
        "assumptions": ["Missing June telemetry for SV-WELL-02 is estimated and flagged; not a certified measurement."],
        "missing_data_flags": ["SV-WELL-02 June telemetry gap"],
        "methodology": "Values are reported, measured, estimated, calculated, or AI-inferred according to record-level truth labels. Estimates remain explicitly labeled.",
        "disclaimer": DISCLAIMER,
    }
    if export_type == "csv":
        package["content"] = _csv_export(package)
    elif export_type == "xlsx":
        package["content"] = {"workbook_sheets": ["cover", "gears", "sgma", "measurements", "evidence", "methodology"]}
    elif export_type == "pdf":
        package["content"] = "Human-readable PDF package placeholder with cover, readiness summary, evidence table, and methodology."
    else:
        package["content"] = deepcopy(package)
    EXPORTS[package["id"]] = package
    return deepcopy(package)


def get_export(export_id: str, organization_id: str | None = None) -> dict[str, Any] | None:
    package = EXPORTS.get(export_id)
    if not package or package.get("organization_id") != _tenant_id(organization_id):
        return None
    return deepcopy(package)
