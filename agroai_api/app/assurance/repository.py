"""Tenant-scoped persistence for Assurance Passports."""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.assurance.models import (
    AssuranceChecklistItem,
    AssuranceEvidenceArtifact,
    AssuranceExport,
    AssurancePassport,
    AssurancePassportSection,
    AssuranceRiskScore,
    FertilizerApplication,
    HarvestLot,
    InputApplication,
    PesticideApplication,
    RulePack,
    TraceabilityEvent,
)
from app.assurance.rule_packs import ASSURANCE_DISCLAIMER, DEFAULT_RULE_PACKS, checklist_for, validate_rule_pack_ids
from app.models.compliance import (
    ComplianceEvidence,
    ComplianceJurisdiction,
    ComplianceMeasurement,
    ComplianceMeter,
    ComplianceParcel,
    ComplianceWaterBudget,
    ComplianceWell,
)


TRUTH_LABELS = {"measured", "reported", "estimated", "calculated", "AI-inferred"}
SECTION_TYPES = ["farm_summary", "water_proof", "input_proof", "traceability_proof", "readiness_score", "risk_score"]


def _dt(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _checksum(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _as_dict(row: Any) -> dict[str, Any]:
    data = {column.name: _iso(getattr(row, column.name)) for column in row.__table__.columns}
    if "metadata_json" in data:
        data["metadata"] = data.pop("metadata_json") or {}
    return data


class AssuranceRepository:
    def __init__(self, db: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.db = db
        self.tenant_id = tenant_id

    def ensure_rule_packs(self) -> None:
        for pack_id, pack in DEFAULT_RULE_PACKS.items():
            if self.db.query(RulePack).filter_by(id=pack_id).first():
                continue
            self.db.add(RulePack(
                id=pack_id,
                scope=pack["scope"],
                version=pack["version"],
                status=pack["status"],
                required_evidence_types=pack["required_evidence_types"],
                checklist=pack["checklist"],
                validation_rules=pack["validation_rules"],
                scoring_weights=pack["scoring_weights"],
                disclaimer_text=pack["disclaimer_text"],
            ))
        self.db.commit()

    def _passport(self, passport_id: str) -> AssurancePassport:
        row = self.db.query(AssurancePassport).filter_by(id=passport_id, tenant_id=self.tenant_id).first()
        if not row:
            raise KeyError("Passport not found")
        return row

    def create_passport(self, payload: dict[str, Any]) -> dict[str, Any]:
        pack_ids = validate_rule_pack_ids(payload.get("rule_pack_ids"))
        passport = AssurancePassport(
            id=payload.get("id") or f"ap-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            farm_name=payload["farm_name"],
            farm_location=payload.get("farm_location"),
            crop=payload.get("crop"),
            season=payload.get("season"),
            reporting_period=str(payload.get("reporting_period") or datetime.utcnow().year),
            status="draft",
            rule_pack_ids=pack_ids,
            jurisdiction_id=payload.get("jurisdiction_id"),
            parcel_ids=payload.get("parcel_ids") or [],
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(passport)
        self.db.flush()
        for section_type in SECTION_TYPES:
            self.db.add(AssurancePassportSection(
                id=f"aps-{uuid.uuid4().hex[:12]}",
                tenant_id=self.tenant_id,
                passport_id=passport.id,
                section_type=section_type,
                status="pending",
                readiness_score=0.0,
                payload={},
            ))
        for item in checklist_for(pack_ids):
            self.db.add(AssuranceChecklistItem(
                id=f"aci-{uuid.uuid4().hex[:12]}",
                tenant_id=self.tenant_id,
                passport_id=passport.id,
                rule_pack_id=item["rule_pack_id"],
                requirement_key=item["key"],
                section_type=item["section"],
                status="missing",
                severity=item.get("severity", "required"),
                evidence_artifact_ids=[],
                notes="Evidence not attached yet.",
            ))
        self.db.commit()
        return self.get_passport(passport.id)

    def get_passport(self, passport_id: str) -> dict[str, Any]:
        passport = self._passport(passport_id)
        return {
            "passport": _as_dict(passport),
            "sections": [_as_dict(row) for row in self.db.query(AssurancePassportSection).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
            "evidence": [_as_dict(row) for row in self.db.query(AssuranceEvidenceArtifact).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
            "input_applications": [_as_dict(row) for row in self.db.query(InputApplication).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
            "harvest_lots": [_as_dict(row) for row in self.db.query(HarvestLot).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
            "traceability_events": [_as_dict(row) for row in self.db.query(TraceabilityEvent).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
            "latest_readiness": self.readiness(passport_id, persist=False),
            "disclaimer": ASSURANCE_DISCLAIMER,
        }

    def add_evidence(self, passport_id: str, payload: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        self._passport(passport_id)
        truth_label = payload.get("truth_label", "reported")
        if truth_label not in TRUTH_LABELS:
            raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
        compliance_evidence_id = payload.get("compliance_evidence_id")
        if compliance_evidence_id:
            exists = self.db.query(ComplianceEvidence).filter_by(id=compliance_evidence_id, tenant_id=self.tenant_id).first()
            if not exists:
                raise ValueError("compliance_evidence_id does not belong to authenticated tenant")
        row = AssuranceEvidenceArtifact(
            id=payload.get("id") or f"aev-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            passport_id=passport_id,
            compliance_evidence_id=compliance_evidence_id,
            workbench_artifact_id=payload.get("workbench_artifact_id"),
            evidence_type=payload["evidence_type"],
            proof_domain=payload.get("proof_domain") or payload["evidence_type"],
            file_ref=payload["file_ref"],
            filename=payload.get("filename"),
            content_type=payload.get("content_type"),
            checksum=payload.get("checksum"),
            truth_label=truth_label,
            review_status=payload.get("review_status", "pending_review"),
            source_system=payload.get("source_system", "uploaded"),
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(row)
        self._sync_checklist_for_evidence(passport_id, row)
        if commit:
            self.db.commit()
        return _as_dict(row)

    def _sync_checklist_for_evidence(self, passport_id: str, evidence: AssuranceEvidenceArtifact) -> None:
        items = self.db.query(AssuranceChecklistItem).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()
        for item in items:
            for spec in checklist_for(self._passport(passport_id).rule_pack_ids):
                if spec["rule_pack_id"] != item.rule_pack_id or spec["key"] != item.requirement_key:
                    continue
                if evidence.evidence_type in spec.get("evidence_types", []):
                    ids = list(item.evidence_artifact_ids or [])
                    if evidence.id not in ids:
                        ids.append(evidence.id)
                    item.evidence_artifact_ids = ids
                    item.status = "satisfied"
                    item.notes = "Evidence attached for audit readiness review."
                    item.updated_at = datetime.utcnow()

    def add_input_application(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._passport(passport_id)
        app_type = payload.get("application_type", "input")
        row = InputApplication(
            id=payload.get("id") or f"inp-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            passport_id=passport_id,
            application_type=app_type,
            applied_at=_dt(payload.get("applied_at")),
            block_id=payload.get("block_id"),
            parcel_id=payload.get("parcel_id"),
            product_name=payload["product_name"],
            quantity=payload.get("quantity"),
            unit=payload.get("unit"),
            operator=payload.get("operator"),
            truth_label=payload.get("truth_label", "reported"),
            evidence_artifact_id=payload.get("evidence_artifact_id"),
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(row)
        self.db.flush()
        if app_type == "pesticide":
            self.db.add(PesticideApplication(
                id=f"pest-{uuid.uuid4().hex[:12]}",
                tenant_id=self.tenant_id,
                passport_id=passport_id,
                input_application_id=row.id,
                active_ingredient=payload.get("active_ingredient"),
                target_pest=payload.get("target_pest"),
                reentry_interval_hours=payload.get("reentry_interval_hours"),
                preharvest_interval_days=payload.get("preharvest_interval_days"),
                label_reference=payload.get("label_reference"),
                metadata_json=payload.get("pesticide_metadata") or {},
            ))
        if app_type == "fertilizer":
            self.db.add(FertilizerApplication(
                id=f"fert-{uuid.uuid4().hex[:12]}",
                tenant_id=self.tenant_id,
                passport_id=passport_id,
                input_application_id=row.id,
                nutrient_profile=payload.get("nutrient_profile") or {},
                nitrogen_kg=payload.get("nitrogen_kg"),
                phosphorus_kg=payload.get("phosphorus_kg"),
                potassium_kg=payload.get("potassium_kg"),
                metadata_json=payload.get("fertilizer_metadata") or {},
            ))
        if not payload.get("evidence_artifact_id"):
            self.add_evidence(passport_id, {
                "evidence_type": "input_application_record",
                "proof_domain": "input_proof",
                "file_ref": f"input_application://{row.id}",
                "truth_label": row.truth_label,
                "source_system": "assurance_api",
                "metadata": {"input_application_id": row.id, "product_name": row.product_name},
            }, commit=False)
        self.db.commit()
        return _as_dict(row)

    def add_harvest_lot(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._passport(passport_id)
        row = HarvestLot(
            id=payload.get("id") or f"lot-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            passport_id=passport_id,
            lot_code=payload["lot_code"],
            crop=payload.get("crop"),
            variety=payload.get("variety"),
            harvested_at=_dt(payload.get("harvested_at")),
            block_id=payload.get("block_id"),
            parcel_id=payload.get("parcel_id"),
            quantity=payload.get("quantity"),
            unit=payload.get("unit"),
            destination=payload.get("destination"),
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(row)
        self.db.commit()
        return _as_dict(row)

    def add_traceability_event(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._passport(passport_id)
        lot_id = payload.get("harvest_lot_id")
        if lot_id and not self.db.query(HarvestLot).filter_by(id=lot_id, tenant_id=self.tenant_id, passport_id=passport_id).first():
            raise ValueError("harvest_lot_id does not belong to this passport")
        row = TraceabilityEvent(
            id=payload.get("id") or f"trace-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            passport_id=passport_id,
            harvest_lot_id=lot_id,
            event_type=payload["event_type"],
            occurred_at=_dt(payload.get("occurred_at")),
            location=payload.get("location"),
            actor=payload.get("actor"),
            evidence_artifact_id=payload.get("evidence_artifact_id"),
            payload=payload.get("payload") or {},
        )
        self.db.add(row)
        if not payload.get("evidence_artifact_id"):
            self.add_evidence(passport_id, {
                "evidence_type": "traceability_record",
                "proof_domain": "traceability_proof",
                "file_ref": f"traceability_event://{row.id}",
                "truth_label": "reported",
                "source_system": "assurance_api",
                "metadata": {"traceability_event_id": row.id, "event_type": row.event_type},
            }, commit=False)
        self.db.commit()
        return _as_dict(row)

    def _passport_scope_missing(self, passport: AssurancePassport) -> list[str]:
        missing: list[str] = []
        if not passport.parcel_ids:
            missing.append("parcel_ids")
        if not passport.reporting_period:
            missing.append("reporting_period")
        return missing

    def _linked_water_budget_ids(self, passport_id: str) -> set[str]:
        evidence = self.db.query(AssuranceEvidenceArtifact).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()
        linked_ids: set[str] = set()
        for row in evidence:
            metadata = row.metadata_json or {}
            for key in ("water_budget_id", "compliance_water_budget_id"):
                if metadata.get(key):
                    linked_ids.add(str(metadata[key]))
            for key in ("water_budget_ids", "compliance_water_budget_ids"):
                values = metadata.get(key) or []
                if isinstance(values, (str, int)):
                    values = [values]
                linked_ids.update(str(value) for value in values if value)
        return linked_ids

    def _scoped_compliance_assets(self, passport: AssurancePassport) -> dict[str, Any]:
        parcel_ids = [str(parcel_id) for parcel_id in (passport.parcel_ids or []) if parcel_id]
        scope_missing = self._passport_scope_missing(passport)
        parcels = []
        if parcel_ids:
            parcels = self.db.query(ComplianceParcel).filter(
                ComplianceParcel.tenant_id == self.tenant_id,
                ComplianceParcel.id.in_(parcel_ids),
            ).all()

        jurisdictions = []
        if passport.jurisdiction_id:
            jurisdictions = self.db.query(ComplianceJurisdiction).filter_by(
                tenant_id=self.tenant_id,
                id=passport.jurisdiction_id,
            ).all()

        wells = []
        if parcel_ids:
            wells = self.db.query(ComplianceWell).filter(
                ComplianceWell.tenant_id == self.tenant_id,
                ComplianceWell.parcel_id.in_(parcel_ids),
            ).all()
        well_ids = [row.id for row in wells]

        meters = []
        if well_ids:
            meters = self.db.query(ComplianceMeter).filter(
                ComplianceMeter.tenant_id == self.tenant_id,
                ComplianceMeter.well_id.in_(well_ids),
            ).all()
        meter_ids = [row.id for row in meters]

        measurements = []
        asset_filters = []
        if parcel_ids:
            asset_filters.append((ComplianceMeasurement.related_asset_type == "parcel") & ComplianceMeasurement.related_asset_id.in_(parcel_ids))
        if well_ids:
            asset_filters.append((ComplianceMeasurement.related_asset_type == "well") & ComplianceMeasurement.related_asset_id.in_(well_ids))
        if meter_ids:
            asset_filters.append((ComplianceMeasurement.related_asset_type == "meter") & ComplianceMeasurement.related_asset_id.in_(meter_ids))
        if passport.reporting_period and asset_filters:
            measurements = self.db.query(ComplianceMeasurement).filter(
                ComplianceMeasurement.tenant_id == self.tenant_id,
                ComplianceMeasurement.reporting_period == str(passport.reporting_period),
                or_(*asset_filters),
            ).all()

        water_budgets = []
        linked_budget_ids = self._linked_water_budget_ids(passport.id)
        if passport.reporting_period and linked_budget_ids:
            water_budgets = self.db.query(ComplianceWaterBudget).filter(
                ComplianceWaterBudget.tenant_id == self.tenant_id,
                ComplianceWaterBudget.id.in_(linked_budget_ids),
                ComplianceWaterBudget.reporting_period == str(passport.reporting_period),
            ).all()

        return {
            "scope_missing": scope_missing,
            "parcels": parcels,
            "jurisdictions": jurisdictions,
            "wells": wells,
            "meters": meters,
            "measurements": measurements,
            "water_budgets": water_budgets,
        }

    def _jurisdiction_payload(self, row: ComplianceJurisdiction) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "country": row.country, "jurisdiction_level": row.jurisdiction_level, "authority_name": row.authority_name, "state": row.state, "county": row.county, "basin": row.basin, "subbasin": row.subbasin, "gsa": row.gsa, "district": row.district, "jurisdiction_pack": row.jurisdiction_pack, "reporting_year": row.reporting_year, "reporting_deadline": _iso(row.reporting_deadline), "workflow_type": row.workflow_type}

    def _parcel_payload(self, row: ComplianceParcel) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "apn": row.apn, "parcel_identifier": row.parcel_identifier, "country": row.country, "state": row.state, "county": row.county, "geometry_ref": row.geometry_ref, "geometry": row.geometry}

    def _well_payload(self, row: ComplianceWell) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "parcel_id": row.parcel_id, "well_identifier": row.well_identifier, "latitude": row.latitude, "longitude": row.longitude, "well_capacity": row.well_capacity, "capacity_unit": row.capacity_unit}

    def _meter_payload(self, row: ComplianceMeter) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "well_id": row.well_id, "meter_identifier": row.meter_identifier, "manufacturer": row.manufacturer, "serial_number": row.serial_number, "measurement_method": row.measurement_method, "calibration_date": _iso(row.calibration_date), "calibration_document_ref": row.calibration_document_ref}

    def _measurement_payload(self, row: ComplianceMeasurement) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "asset_type": row.related_asset_type, "asset_id": row.related_asset_id, "measurement_type": row.measurement_type, "value": row.value, "unit": row.unit, "method": row.method, "truth_label": row.truth_label, "source_system": row.source_system, "source_timestamp": _iso(row.source_timestamp), "ingestion_timestamp": _iso(row.ingestion_timestamp), "quality_status": row.quality_status, "reporting_period": row.reporting_period, "confidence": row.confidence, "correction_lineage": row.correction_lineage or []}

    def _water_budget_payload(self, row: ComplianceWaterBudget) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "allocation_af": row.allocation, "extraction_af": row.extraction, "irrigation_application_af": row.irrigation_application, "remaining_balance_af": row.remaining_balance, "projected_balance_af": row.projected_balance, "threshold_status": row.threshold_status, "water_source": row.water_source, "reporting_period": row.reporting_period}

    def _proof_counts(self, passport_id: str, scoped_assets: dict[str, Any] | None = None) -> dict[str, int]:
        evidence = self.db.query(AssuranceEvidenceArtifact).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()
        counts: dict[str, int] = {}
        for row in evidence:
            counts[row.evidence_type] = counts.get(row.evidence_type, 0) + 1
        if scoped_assets and not scoped_assets["scope_missing"]:
            if scoped_assets["parcels"]:
                counts["farm_boundary"] = counts.get("farm_boundary", 0) + len(scoped_assets["parcels"])
            if scoped_assets["measurements"]:
                counts["water_measurement"] = counts.get("water_measurement", 0) + len(scoped_assets["measurements"])
            if scoped_assets["water_budgets"]:
                counts["water_budget"] = counts.get("water_budget", 0) + len(scoped_assets["water_budgets"])
        return counts

    def readiness(self, passport_id: str, *, persist: bool = True) -> dict[str, Any]:
        passport = self._passport(passport_id)
        scoped_assets = self._scoped_compliance_assets(passport)
        counts = self._proof_counts(passport_id, scoped_assets)
        items = self.db.query(AssuranceChecklistItem).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()
        missing: list[dict[str, Any]] = []
        satisfied = 0
        specs = checklist_for(passport.rule_pack_ids)
        for item in items:
            spec = next((entry for entry in specs if entry["rule_pack_id"] == item.rule_pack_id and entry["key"] == item.requirement_key), {})
            is_satisfied = item.status == "satisfied"
            if not is_satisfied and spec.get("record_type") == "input_application":
                is_satisfied = self.db.query(InputApplication).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).count() > 0
            if not is_satisfied and spec.get("evidence_types"):
                is_satisfied = any(counts.get(evidence_type, 0) > 0 for evidence_type in spec["evidence_types"])
            if is_satisfied:
                satisfied += 1
                item.status = "satisfied"
            else:
                missing.append({
                    "rule_pack_id": item.rule_pack_id,
                    "requirement_key": item.requirement_key,
                    "section_type": item.section_type,
                    "severity": item.severity,
                    "needed_evidence_types": spec.get("evidence_types", []),
                })
        total = max(len(items), 1)
        readiness_score = round(satisfied / total * 100, 1)
        risk_score = max(0.0, min(100.0, 100.0 - readiness_score + len([m for m in missing if m["severity"] == "required"]) * 5))
        risk_level = "low" if risk_score < 25 else "medium" if risk_score < 60 else "high"
        scope_missing = scoped_assets["scope_missing"]
        status_value = "needs_scope_review" if scope_missing else "ready_for_review" if not missing else "missing_proof"
        review_status = "needs_review" if scope_missing or missing else "ready_for_review"
        payload = {
            "passport_id": passport_id,
            "tenant_id": self.tenant_id,
            "status": status_value,
            "review_status": review_status,
            "readiness_score": readiness_score,
            "risk_score": round(risk_score, 1),
            "risk_level": risk_level,
            "satisfied_count": satisfied,
            "checklist_count": len(items),
            "missing_evidence": missing,
            "proof_counts": counts,
            "rule_pack_ids": passport.rule_pack_ids,
            "language": "audit readiness",
            "scope": {
                "readiness_package_only": True,
                "authority_submission": False,
                "live_source_complete": False,
                "scope_status": "needs_scope_review" if scope_missing else "scoped",
                "review_status": review_status,
                "missing_scope": scope_missing,
                "parcel_ids": passport.parcel_ids or [],
                "jurisdiction_id": passport.jurisdiction_id,
                "reporting_period": passport.reporting_period,
                "scoped_record_counts": {
                    "parcels": len(scoped_assets["parcels"]),
                    "jurisdictions": len(scoped_assets["jurisdictions"]),
                    "wells": len(scoped_assets["wells"]),
                    "meters": len(scoped_assets["meters"]),
                    "measurements": len(scoped_assets["measurements"]),
                    "water_budgets": len(scoped_assets["water_budgets"]),
                },
            },
            "disclaimer": ASSURANCE_DISCLAIMER,
        }
        if persist:
            self.db.add(AssuranceRiskScore(
                id=f"risk-{uuid.uuid4().hex[:12]}",
                tenant_id=self.tenant_id,
                passport_id=passport_id,
                score_type="audit_readiness_risk",
                score=payload["risk_score"],
                risk_level=risk_level,
                factors={"missing_evidence": missing, "proof_counts": counts},
            ))
            for section_type in SECTION_TYPES:
                section = self.db.query(AssurancePassportSection).filter_by(tenant_id=self.tenant_id, passport_id=passport_id, section_type=section_type).first()
                if section:
                    section.readiness_score = readiness_score
                    section.status = "needs_review" if scope_missing else "ready_for_review" if not [m for m in missing if m["section_type"] == section_type] else "missing_proof"
                    section.payload = payload
                    section.updated_at = datetime.utcnow()
            passport.status = payload["status"]
            passport.updated_at = datetime.utcnow()
            self.db.commit()
        return payload

    def export_pdf(self, passport_id: str) -> dict[str, Any]:
        package = self._export_payload(passport_id)
        pdf_bytes = render_passport_pdf(package)
        encoded = base64.b64encode(pdf_bytes).decode("ascii")
        checksum = hashlib.sha256(pdf_bytes).hexdigest()
        export = AssuranceExport(
            id=f"aex-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            passport_id=passport_id,
            export_type="pdf",
            storage_backend="inline_base64",
            storage_ref=None,
            checksum=checksum,
            payload={**package, "content_base64": encoded, "content_type": "application/pdf"},
        )
        self.db.add(export)
        self.db.commit()
        return {
            "id": export.id,
            "passport_id": passport_id,
            "export_type": "pdf",
            "content_type": "application/pdf",
            "content_base64": encoded,
            "checksum": checksum,
            "storage_backend": export.storage_backend,
            "created_at": export.created_at.isoformat(),
            "disclaimer": ASSURANCE_DISCLAIMER,
        }

    def _export_payload(self, passport_id: str) -> dict[str, Any]:
        passport = self._passport(passport_id)
        scoped_assets = self._scoped_compliance_assets(passport)
        readiness = self.readiness(passport_id, persist=True)
        return {
            "passport": _as_dict(passport),
            "farm_summary": {
                "farm_name": passport.farm_name,
                "farm_location": passport.farm_location,
                "crop": passport.crop,
                "season": passport.season,
                "reporting_period": passport.reporting_period,
                "parcels": [self._parcel_payload(row) for row in scoped_assets["parcels"]],
                "jurisdictions": [self._jurisdiction_payload(row) for row in scoped_assets["jurisdictions"]],
            },
            "water_proof": {
                "wells": [self._well_payload(row) for row in scoped_assets["wells"]],
                "meters": [self._meter_payload(row) for row in scoped_assets["meters"]],
                "measurements": [self._measurement_payload(row) for row in scoped_assets["measurements"]],
                "water_budgets": [self._water_budget_payload(row) for row in scoped_assets["water_budgets"]],
            },
            "input_proof": [_as_dict(row) for row in self.db.query(InputApplication).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
            "traceability_proof": {
                "harvest_lots": [_as_dict(row) for row in self.db.query(HarvestLot).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
                "events": [_as_dict(row) for row in self.db.query(TraceabilityEvent).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
            },
            "evidence": [_as_dict(row) for row in self.db.query(AssuranceEvidenceArtifact).filter_by(tenant_id=self.tenant_id, passport_id=passport_id).all()],
            "readiness": readiness,
            "audit_trail": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "AGRO-AI Assurance OS",
                "scope": readiness["scope"],
            },
            "disclaimer": ASSURANCE_DISCLAIMER,
        }


def render_passport_pdf(package: dict[str, Any]) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Assurance Passport Audit Readiness")
    styles = getSampleStyleSheet()
    story = []

    def add_heading(text: str) -> None:
        story.append(Paragraph(text, styles["Heading2"]))

    def add_body(text: str) -> None:
        story.append(Paragraph(text.replace("&", "&amp;"), styles["BodyText"]))
        story.append(Spacer(1, 8))

    passport = package["passport"]
    readiness = package["readiness"]
    story.append(Paragraph("Assurance Passport - Audit Readiness", styles["Title"]))
    add_body(package["disclaimer"])
    add_heading("Farm Summary")
    add_body(f"Farm: {passport.get('farm_name')} | Crop: {passport.get('crop') or 'not provided'} | Period: {passport.get('reporting_period')}")
    add_heading("Water Proof")
    water = package["water_proof"]
    add_body(f"Wells: {len(water['wells'])}; meters: {len(water['meters'])}; measurements: {len(water['measurements'])}; water budgets: {len(water['water_budgets'])}.")
    add_heading("Input Proof")
    add_body(f"Input application records: {len(package['input_proof'])}.")
    add_heading("Traceability Proof")
    trace = package["traceability_proof"]
    add_body(f"Harvest lots: {len(trace['harvest_lots'])}; traceability events: {len(trace['events'])}.")
    add_heading("Missing Evidence")
    if readiness["missing_evidence"]:
        add_body("; ".join(item["requirement_key"] for item in readiness["missing_evidence"]))
    else:
        add_body("No missing checklist evidence detected for the selected rule packs.")
    add_heading("Readiness Score")
    add_body(f"{readiness['readiness_score']}% - {readiness['status']}.")
    add_heading("Risk Score")
    add_body(f"{readiness['risk_score']} ({readiness['risk_level']}).")
    add_heading("Audit Trail")
    add_body(f"Generated at {package['audit_trail']['generated_at']}. Scope: audit readiness evidence package for reviewer evaluation.")
    doc.build(story)
    return buf.getvalue()
