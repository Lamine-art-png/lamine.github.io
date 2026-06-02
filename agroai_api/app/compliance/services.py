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


def water_budget_status(organization_id: str | None = None, remaining_threshold_pct: float = 15) -> list[dict[str, Any]]:
    budgets = _scoped(VINEYARD_FIXTURE["water_budgets"], organization_id)
    for budget in budgets:
        budget["remaining_balance_af"] = round(budget["allocation_af"] - budget["extraction_af"], 2)
        remaining_pct = budget["remaining_balance_af"] / budget["allocation_af"] * 100 if budget["allocation_af"] else 0
        budget["remaining_pct"] = round(remaining_pct, 1)
        budget["threshold_status"] = "alert" if remaining_pct < remaining_threshold_pct or budget["projected_balance_af"] < 0 else "ok"
        budget["threshold_remaining_pct"] = remaining_threshold_pct
        budget["truth_labels"] = {"remaining_balance_af": "calculated", "projected_balance_af": "calculated", "extraction_af": "measured"}
    return budgets


def reconciliation(organization_id: str | None = None) -> list[dict[str, Any]]:
    return _scoped(VINEYARD_FIXTURE["reconciliation"], organization_id)


def readiness(workflow_type: str = "gears_groundwater_extractor_readiness", organization_id: str | None = None) -> dict[str, Any]:
    pack = validate_customer_workflow(workflow_type)
    remaining_threshold_pct = float(pack.get("warning_thresholds", {}).get("water_budget_remaining_pct", 15))
    missing_fields = validate_required_fields(workflow_type, organization_id)
    measurements = list_measurements(organization_id)
    meters = list_assets("meters", organization_id)
    missing_evidence = []
    warnings = []
    stale_telemetry = []
    anomalies = []
    now = datetime.now(timezone.utc).date()
    for measurement in measurements:
        correction_lineage = measurement.get("correction_lineage") or []
        gap_lineage = next((item for item in correction_lineage if item.get("missing_window") or "gap" in str(item.get("reason", "")).lower()), None)
        if measurement.get("quality_status") == "gap_estimate" or gap_lineage:
            asset_id = measurement.get("asset_id") or measurement.get("related_asset_id")
            window = (gap_lineage or {}).get("missing_window") or measurement.get("source_timestamp")
            stale_telemetry.append({"asset_id": asset_id, "window": window, "severity": "blocking", "truth_label": measurement.get("truth_label", "estimated")})
            missing_evidence.append(f"manual_reading_evidence_for_{asset_id or 'asset'}_{measurement.get('reporting_period', 'period')}")
    for meter in meters:
        cal = date.fromisoformat(meter["calibration_date"])
        age_days = (now - cal).days
        if age_days > 365:
            warnings.append({"code": "stale_calibration", "meter_id": meter["id"], "calibration_date": meter["calibration_date"], "age_days": age_days})
    for budget in water_budget_status(organization_id, remaining_threshold_pct=remaining_threshold_pct):
        if budget["threshold_status"] == "alert":
            warnings.append({"code": "water_budget_threshold_alert", "budget_id": budget["id"], "projected_balance_af": budget["projected_balance_af"], "threshold_remaining_pct": remaining_threshold_pct})
    for row in reconciliation(organization_id):
        if abs(row["variance_pct"]) > 10:
            anomalies.append({"code": "application_variance", "reconciliation_id": row["id"], "variance_pct": row["variance_pct"]})
    blocking = missing_fields + ["stale_telemetry" for _ in stale_telemetry]
    deductions = len(blocking) * 18 + len(warnings) * 6 + len(anomalies) * 5
    next_action = f"Attach missing evidence: {missing_evidence[0]}." if missing_evidence else "Reviewer can approve the package for export."
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
        "next_required_action": next_action,
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
        "assumptions": ["Estimated values are labeled as estimates and are not certified measurements."],
        "missing_data_flags": [item["window"] for item in readiness(workflow_type, organization_id).get("stale_telemetry", [])],
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

# ---------------------------------------------------------------------------
# Database-backed service entry points (v2 global kernel)
# ---------------------------------------------------------------------------
from app.compliance.exporters import render_export_content  # noqa: E402
from app.compliance.storage import prepare_export_storage  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.compliance.rulepacks import validate_customer_workflow  # noqa: E402


def water_budget_status_from_records(budgets: list[dict[str, Any]], remaining_threshold_pct: float = 15) -> list[dict[str, Any]]:
    result = deepcopy(budgets)
    for budget in result:
        budget["remaining_balance_af"] = round(float(budget["allocation_af"]) - float(budget["extraction_af"]), 2)
        remaining_pct = budget["remaining_balance_af"] / float(budget["allocation_af"]) * 100 if budget["allocation_af"] else 0
        budget["remaining_pct"] = round(remaining_pct, 1)
        budget["threshold_status"] = "alert" if remaining_pct < remaining_threshold_pct or float(budget.get("projected_balance_af") or 0) < 0 else "ok"
        budget["threshold_remaining_pct"] = remaining_threshold_pct
        budget["truth_labels"] = {"remaining_balance_af": "calculated", "projected_balance_af": "calculated", "extraction_af": "measured"}
    return result


def readiness_from_repository(repo, workflow_type: str = "gears_groundwater_extractor_readiness") -> dict[str, Any]:
    pack = validate_customer_workflow(workflow_type)
    thresholds = pack.get("warning_thresholds", {})
    telemetry_gap_days = int(thresholds.get("telemetry_gap_days", 14))
    stale_calibration_days = int(thresholds.get("stale_calibration_days", 365))
    org = repo.organization()
    wells = repo.wells()
    meters = repo.meters()
    measurements = repo.measurements()
    evidence_rows = repo.evidence()
    remaining_threshold_pct = float(thresholds.get("water_budget_remaining_pct", 15))
    budgets = water_budget_status_from_records(repo.water_budgets(), remaining_threshold_pct=remaining_threshold_pct)
    recons = repo.reconciliation()
    now = datetime.now(timezone.utc).date()
    missing_fields: list[str] = []
    if not org.get("owner"):
        missing_fields.append("owner_details")
    if not wells:
        missing_fields.append("well_identifier")
    if any(well.get("latitude") is None or well.get("longitude") is None for well in wells):
        missing_fields.append("well_location")
    if not measurements:
        missing_fields.append("monthly_groundwater_extraction_volumes")
    if any(not meter.get("measurement_method") for meter in meters):
        missing_fields.append("measurement_method")
    if workflow_type == "gears_groundwater_extractor_readiness" and org.get("reporting_agent"):
        if not any(ev.get("artifact_type") == "agent_authorization" for ev in evidence_rows):
            missing_fields.append("agent_authorization_evidence")

    stale_telemetry = []
    missing_evidence = []
    for measurement in measurements:
        correction_lineage = measurement.get("correction_lineage") or []
        gap_lineage = next((item for item in correction_lineage if item.get("missing_window") or "gap" in str(item.get("reason", "")).lower()), None)
        if measurement.get("quality_status") == "gap_estimate" or gap_lineage:
            window = (gap_lineage or {}).get("missing_window") or measurement.get("source_timestamp")
            asset_id = measurement.get("asset_id") or measurement.get("related_asset_id")
            stale_telemetry.append({"asset_id": asset_id, "window": window, "severity": "blocking", "truth_label": measurement.get("truth_label", "estimated"), "threshold_days": telemetry_gap_days})
            missing_evidence.append(f"manual_reading_evidence_for_{asset_id or 'asset'}_{measurement.get('reporting_period', 'period')}")
    warnings = []
    for meter in meters:
        if meter.get("calibration_date"):
            cal = date.fromisoformat(meter["calibration_date"])
            age_days = (now - cal).days
            if age_days > stale_calibration_days:
                warnings.append({"code": "stale_calibration", "meter_id": meter["id"], "calibration_date": meter["calibration_date"], "age_days": age_days, "threshold_days": stale_calibration_days})
    for budget in budgets:
        if budget["threshold_status"] == "alert":
            warnings.append({"code": "water_budget_threshold_alert", "budget_id": budget["id"], "projected_balance_af": budget["projected_balance_af"], "threshold_remaining_pct": remaining_threshold_pct})
    anomalies = []
    for row in recons:
        variance_pct = row.get("variance_pct")
        if variance_pct is None and row.get("recommended_volume_af"):
            variance_pct = row.get("variance_af", 0) / row["recommended_volume_af"] * 100
        if variance_pct is not None and abs(variance_pct) > 10:
            anomalies.append({"code": "application_variance", "reconciliation_id": row["id"], "variance_pct": round(variance_pct, 2)})
    blocking = missing_fields + ["stale_telemetry" for _ in stale_telemetry]
    deductions = len(blocking) * 18 + len(warnings) * 6 + len(anomalies) * 5
    if missing_evidence:
        next_action = f"Attach missing evidence: {missing_evidence[0]}."
    elif anomalies:
        next_action = "Review unresolved reconciliation anomalies before export review."
    elif warnings:
        next_action = "Review compliance warnings before export review."
    else:
        next_action = "Reviewer can approve the package for export."
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
        "upcoming_deadlines": [j for j in repo.jurisdictions() if j["workflow_type"] == workflow_type],
        "water_budgets": budgets,
        "active_rule_pack": {k: pack[k] for k in ("pack_id", "version", "country_code", "region", "authority", "workflow_types", "legal_review_status", "enabled", "warning_thresholds", "disclaimer") if k in pack},
        "disclaimer": DISCLAIMER,
        "next_required_action": next_action,
    }

def status_from_repository(repo) -> dict[str, Any]:
    readiness = readiness_from_repository(repo)
    return {
        "enabled": True,
        "feature_flag": "CALIFORNIA_COMPLIANCE_PACK_ENABLED",
        "organization": repo.organization() or {"id": repo.tenant_id},
        "jurisdictions": [j for j in repo.jurisdictions() if j["workflow_type"] == readiness["workflow_type"]],
        "active_workflow": readiness["workflow_type"],
        "active_rule_pack": readiness["active_rule_pack"],
        "readiness": readiness,
        "disclaimer": DISCLAIMER,
    }


def compose_export_from_repository(repo, export_type: str, workflow_type: str) -> dict[str, Any]:
    validate_customer_workflow(workflow_type)
    package = {
        "id": f"export-{uuid.uuid4().hex[:10]}",
        "format": export_type,
        "workflow_type": workflow_type,
        "organization_id": repo.tenant_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "jurisdictions": repo.jurisdictions(),
        "assets": {"parcels": repo.parcels(), "wells": repo.wells(), "meters": repo.meters()},
        "measurements": repo.measurements(),
        "water_budgets": readiness_from_repository(repo, workflow_type).get("water_budgets", []),
        "reconciliation": repo.reconciliation(),
        "readiness": readiness_from_repository(repo, workflow_type),
        "provenance": {"source": "AGRO-AI global compliance kernel", "truth_labels_required": sorted(TRUTH_LABELS), "direct_filing": False},
        "assumptions": ["Estimated values are labeled as estimates and are not certified measurements."],
        "missing_data_flags": [item["window"] for item in readiness_from_repository(repo, workflow_type).get("stale_telemetry", [])],
        "methodology": "Values are reported, measured, estimated, calculated, or AI-inferred according to record-level truth labels. Estimates remain explicitly labeled.",
        "disclaimer": DISCLAIMER,
    }
    content, mime_type, file_name = render_export_content(package, export_type)
    if settings.COMPLIANCE_EXPORT_STORAGE_BACKEND == "database_dev_fallback" and not settings.COMPLIANCE_ALLOW_DATABASE_DEV_FALLBACK:
        raise RuntimeError("COMPLIANCE_ALLOW_DATABASE_DEV_FALLBACK must be true to store export binaries in the database")
    stored = prepare_export_storage(package["id"], content, settings.COMPLIANCE_EXPORT_STORAGE_BACKEND)
    package["mime_type"] = mime_type
    package["file_name"] = file_name
    package["storage_backend"] = stored.storage_backend
    package["storage_ref"] = stored.storage_ref
    package["checksum_sha256"] = stored.checksum_sha256
    package["content_base64"] = stored.content_base64
    package["content_bytes"] = stored.content_bytes
    package["download_available"] = stored.content_base64 is not None
    return repo.save_export(package)
