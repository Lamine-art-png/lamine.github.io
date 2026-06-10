"""Compliance kernel services for readiness, validation, and exports."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.compliance.constants import DISCLAIMER, RULE_PACKS, TRUTH_LABELS
from app.compliance.repository import ComplianceRepository

CUSTOMER_ALLOWED_STATUSES = {"internal_alpha_pending_external_validation"}


def truth_label_valid(label: str) -> bool:
    return label in TRUTH_LABELS


def resolve_workflow_pack(workflow_type: str) -> dict[str, Any]:
    matches = [pack for pack in RULE_PACKS.values() if pack.get("workflow_type") == workflow_type]
    if not matches:
        raise ValueError("Unsupported compliance workflow")
    enabled_matches = [pack for pack in matches if pack.get("enabled")]
    if not enabled_matches:
        raise ValueError("Compliance workflow is disabled")
    pack = enabled_matches[0]
    if pack.get("status") not in CUSTOMER_ALLOWED_STATUSES:
        raise ValueError("Compliance workflow is not customer-facing")
    return dict(pack)


def pack_metadata(pack: dict[str, Any]) -> dict[str, Any]:
    return {key: pack[key] for key in ("pack_id", "jurisdiction", "status", "version", "workflow_type", "external_validation")}


def active_pack_metadata() -> dict[str, Any]:
    return pack_metadata(resolve_workflow_pack("gears_groundwater_extractor_readiness"))


def add_measurement(repo: ComplianceRepository, payload: dict[str, Any]) -> dict[str, Any]:
    label = payload.get("truth_label")
    if not truth_label_valid(label):
        raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
    return repo.add_measurement(payload)


def list_measurements(repo: ComplianceRepository) -> list[dict[str, Any]]:
    return repo.list_measurements()


def list_assets(repo: ComplianceRepository, kind: str) -> list[dict[str, Any]]:
    return repo.list_assets(kind)


def list_jurisdictions(repo: ComplianceRepository) -> list[dict[str, Any]]:
    return repo.list_jurisdictions()


def list_evidence(repo: ComplianceRepository) -> list[dict[str, Any]]:
    return repo.list_evidence()


def add_evidence(repo: ComplianceRepository, payload: dict[str, Any]) -> dict[str, Any]:
    label = payload.get("truth_label", "reported")
    if not truth_label_valid(label):
        raise ValueError("invalid truth_label")
    return repo.add_evidence(payload)


def _reporting_year(repo: ComplianceRepository, workflow_type: str) -> str:
    for jurisdiction in repo.list_jurisdictions():
        if jurisdiction.get("workflow_type") == workflow_type and jurisdiction.get("reporting_year"):
            return str(jurisdiction["reporting_year"])
    return str(date.today().year)


def _groundwater_measurements(repo: ComplianceRepository, reporting_year: str) -> list[dict[str, Any]]:
    return [
        measurement for measurement in repo.list_measurements()
        if measurement.get("measurement_type") == "groundwater_extraction"
        and str(measurement.get("reporting_period")) == str(reporting_year)
    ]


def _months_covered(measurements: list[dict[str, Any]]) -> set[int]:
    months: set[int] = set()
    for measurement in measurements:
        timestamp = str(measurement.get("source_timestamp") or "")
        try:
            months.add(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).month)
        except ValueError:
            continue
    return months


def _months_by_well(measurements: list[dict[str, Any]]) -> dict[str, set[int]]:
    coverage: dict[str, set[int]] = {}
    for measurement in measurements:
        if measurement.get("asset_type") not in (None, "well"):
            continue
        asset_id = measurement.get("asset_id")
        if not asset_id:
            continue
        coverage.setdefault(str(asset_id), set()).update(_months_covered([measurement]))
    return coverage


def validate_required_fields(repo: ComplianceRepository, workflow_type: str, pack: dict[str, Any] | None = None) -> list[str]:
    pack = pack or resolve_workflow_pack(workflow_type)
    reporting_year = _reporting_year(repo, workflow_type)
    missing: list[str] = []
    org = repo.organization()
    wells = repo.list_wells()
    meters = repo.list_meters()
    groundwater = _groundwater_measurements(repo, reporting_year)
    evidence = repo.list_evidence()
    required = set(pack.get("required_fields", []))
    if "owner_details" in required and not org.get("owner"):
        missing.append("owner_details")
    if "well_identifier" in required:
        if not wells:
            missing.append("well_identifier")
        elif any(not well.get("well_identifier") for well in wells):
            missing.append("well_identifier")
    if wells and any(well.get("latitude") is None or well.get("longitude") is None for well in wells):
        missing.append("well_location")
    if "measurement_method" in required:
        if not meters:
            missing.append("measurement_method")
        elif any(not meter.get("measurement_method") for meter in meters):
            missing.append("measurement_method")
    if "monthly_groundwater_extraction_volumes" in required:
        if not groundwater:
            missing.append("monthly_groundwater_extraction_volumes")
        else:
            required_months = int(pack.get("thresholds", {}).get("required_groundwater_months", 12))
            months_by_well = _months_by_well(groundwater)
            incomplete_wells = [
                well.get("id") for well in wells
                if well.get("id") and len(months_by_well.get(str(well.get("id")), set())) < required_months
            ]
            if len(_months_covered(groundwater)) < required_months or incomplete_wells:
                missing.append("monthly_groundwater_extraction_coverage")
    if workflow_type == "gears_groundwater_extractor_readiness" and org.get("reporting_agent"):
        if not any(ev.get("artifact_type") == "agent_authorization" for ev in evidence):
            missing.append("agent_authorization_evidence")
    return missing


def water_budget_status(repo: ComplianceRepository, pack: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    pack = pack or resolve_workflow_pack("gears_groundwater_extractor_readiness")
    threshold = pack.get("thresholds", {}).get("water_budget_remaining_pct_alert", 15)
    budgets = repo.list_budgets()
    for budget in budgets:
        allocation = float(budget.get("allocation_af") or 0)
        extraction = float(budget.get("extraction_af") or 0)
        remaining = round(allocation - extraction, 2)
        remaining_pct = remaining / allocation * 100 if allocation else 0
        budget["remaining_balance_af"] = remaining
        budget["remaining_pct"] = round(remaining_pct, 1)
        budget["threshold_status"] = "alert" if remaining_pct < threshold or float(budget.get("projected_balance_af") or 0) < 0 else "ok"
        budget["truth_labels"] = {"remaining_balance_af": "calculated", "projected_balance_af": "calculated", "extraction_af": "measured"}
    return budgets


def reconciliation(repo: ComplianceRepository) -> list[dict[str, Any]]:
    return repo.list_execution_ledger()


def _telemetry_gaps(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for measurement in measurements:
        lineage = measurement.get("correction_lineage") or []
        if measurement.get("quality_status") == "gap_estimate" or lineage:
            windows = [entry.get("missing_window") for entry in lineage if isinstance(entry, dict) and entry.get("missing_window")]
            gaps.append({
                "asset_id": measurement.get("asset_id"),
                "reporting_period": measurement.get("reporting_period"),
                "windows": windows,
                "truth_label": measurement.get("truth_label"),
                "measurement_id": measurement.get("id"),
            })
    return gaps


def readiness(repo: ComplianceRepository, workflow_type: str = "gears_groundwater_extractor_readiness", *, persist: bool = False) -> dict[str, Any]:
    pack = resolve_workflow_pack(workflow_type)
    reporting_year = _reporting_year(repo, workflow_type)
    missing_fields = validate_required_fields(repo, workflow_type, pack)
    measurements = repo.list_measurements()
    meters = repo.list_meters()
    missing_evidence = []
    warnings = []
    stale_telemetry = _telemetry_gaps(_groundwater_measurements(repo, reporting_year))
    anomalies = []
    for gap in stale_telemetry:
        missing_evidence.append(f"manual_reading_evidence:{gap['asset_id']}:{gap['reporting_period']}")
    today = date.today()
    calibration_limit = pack.get("thresholds", {}).get("stale_calibration_days", 365)
    for meter in meters:
        cal_value = meter.get("calibration_date")
        if not cal_value:
            warnings.append({"code": "missing_calibration", "meter_id": meter.get("id")})
            continue
        cal = date.fromisoformat(cal_value)
        age_days = (today - cal).days
        if age_days > calibration_limit:
            warnings.append({"code": "stale_calibration", "meter_id": meter.get("id"), "calibration_date": cal_value, "age_days": age_days, "threshold_days": calibration_limit})
    for budget in water_budget_status(repo, pack):
        if budget["threshold_status"] == "alert":
            warnings.append({"code": "water_budget_threshold_alert", "budget_id": budget["id"], "projected_balance_af": budget["projected_balance_af"], "remaining_pct": budget.get("remaining_pct")})
    for row in reconciliation(repo):
        variance_pct = row.get("variance_pct")
        if variance_pct is not None and abs(float(variance_pct)) > 10:
            anomalies.append({"code": "application_variance", "reconciliation_id": row["id"], "variance_pct": variance_pct})
    blocking = missing_fields + ["stale_telemetry" for _ in stale_telemetry]
    deductions = len(blocking) * 18 + len(warnings) * 6 + len(anomalies) * 5
    next_action = "Reviewer can approve the package for export."
    if missing_evidence:
        next_action = f"Attach missing evidence for {len(missing_evidence)} telemetry gap(s) before export review."
    payload = {
        "workflow_type": workflow_type,
        "reporting_year": reporting_year,
        "readiness_percentage": max(0, 100 - deductions),
        "readiness_status": "blocked" if blocking else ("warning" if warnings else "ready"),
        "blocking_defects": blocking,
        "warnings": warnings,
        "missing_evidence": missing_evidence,
        "stale_telemetry": stale_telemetry,
        "missing_required_fields": missing_fields,
        "unresolved_anomalies": anomalies,
        "rule_pack": pack_metadata(pack),
        "upcoming_deadlines": [j for j in repo.list_jurisdictions() if j["workflow_type"] == workflow_type],
        "disclaimer": DISCLAIMER,
        "next_required_action": next_action,
    }
    if persist:
        repo.persist_readiness_snapshot(payload, reporting_year)
    return payload


def status(repo: ComplianceRepository, workflow_type: str = "gears_groundwater_extractor_readiness", *, demo_mode: bool = False) -> dict[str, Any]:
    pack = resolve_workflow_pack(workflow_type)
    readiness_payload = readiness(repo, workflow_type, persist=True)
    budgets = water_budget_status(repo, pack)
    reconciliation_rows = reconciliation(repo)
    return {
        "enabled": True,
        "feature_flag": "CALIFORNIA_COMPLIANCE_PACK_ENABLED",
        "demo_mode": demo_mode,
        "organization": repo.organization(),
        "rule_pack": pack_metadata(pack),
        "readiness": readiness_payload,
        "water_budgets": budgets,
        "reconciliation_summary": reconciliation_rows,
        "upcoming_deadlines": readiness_payload["upcoming_deadlines"],
        "missing_evidence_count": len(readiness_payload["missing_evidence"]),
        "unresolved_anomaly_count": len(readiness_payload["unresolved_anomalies"]),
    }


def compose_export(repo: ComplianceRepository, export_type: str, workflow_type: str, *, storage_backend: str) -> dict[str, Any]:
    pack = resolve_workflow_pack(workflow_type)
    reporting_year = _reporting_year(repo, workflow_type)
    if storage_backend != "disabled":
        raise ValueError("Compliance object storage backend is not implemented")
    if export_type != "json":
        raise ValueError("Only JSON metadata package preparation is available while object storage is disabled")
    export_id = f"export-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    gaps = _telemetry_gaps(_groundwater_measurements(repo, reporting_year))
    assumptions = [f"Telemetry gap for {gap['asset_id']} in {gap['reporting_period']} remains labeled {gap['truth_label']}." for gap in gaps]
    package = {
        "id": export_id,
        "format": export_type,
        "workflow_type": workflow_type,
        "reporting_year": reporting_year,
        "organization_id": repo.tenant_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "jurisdictions": repo.list_jurisdictions(),
        "assets": {"parcels": repo.list_parcels(), "wells": repo.list_wells(), "meters": repo.list_meters()},
        "measurements": repo.list_measurements(),
        "water_budgets": water_budget_status(repo, pack),
        "reconciliation": reconciliation(repo),
        "readiness": readiness(repo, workflow_type, persist=True),
        "provenance": {"source": "AGRO-AI compliance kernel", "truth_labels_required": sorted(TRUTH_LABELS), "direct_filing": False, "object_storage": storage_backend, "secure_download_available": False},
        "assumptions": assumptions,
        "missing_data_flags": [f"{gap['asset_id']}:{gap['reporting_period']}" for gap in gaps],
        "methodology": "Values are reported, measured, estimated, calculated, or AI-inferred according to record-level truth labels. Estimates remain explicitly labeled.",
        "disclaimer": DISCLAIMER,
        "storage_status": "metadata_persisted_object_storage_disabled",
    }
    return repo.persist_export_metadata(package, export_type, workflow_type, storage_backend)


def get_export(repo: ComplianceRepository, export_id: str) -> dict[str, Any] | None:
    return repo.get_export(export_id)
