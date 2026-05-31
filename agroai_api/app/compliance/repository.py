"""Database repositories for the jurisdiction-neutral compliance kernel."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.compliance.constants import TRUTH_LABELS
from app.compliance.fixtures import ORG_ID, VINEYARD_FIXTURE
from app.models.audit_log import AuditLog
from app.models.tenant import Tenant
from app.models.compliance import (
    ComplianceEvidence,
    ComplianceExecutionLedger,
    ComplianceExport,
    ComplianceJurisdiction,
    ComplianceMeasurement,
    ComplianceMeter,
    ComplianceOrganizationRole,
    ComplianceParcel,
    ComplianceReadinessSnapshot,
    ComplianceRulePack,
    ComplianceWaterBudget,
    ComplianceWell,
)


class ComplianceContext:
    """Authenticated compliance request context."""

    def __init__(self, tenant_id: str, actor: str | None = None, demo_mode: bool = False):
        self.tenant_id = tenant_id
        self.actor = actor or "compliance-api"
        self.demo_mode = demo_mode


class ComplianceRepository:
    """Tenant-scoped database access for compliance records."""

    def __init__(self, db: Session, context: ComplianceContext):
        self.db = db
        self.context = context

    @property
    def tenant_id(self) -> str:
        return self.context.tenant_id

    def seed_demo_fixture_if_empty(self) -> None:
        """Explicit demo-only fixture loader; never called unless demo mode is enabled."""
        if self.tenant_id != ORG_ID:
            return
        exists = self.db.query(ComplianceJurisdiction).filter(ComplianceJurisdiction.tenant_id == self.tenant_id).first()
        if exists:
            return
        org = VINEYARD_FIXTURE["organization"]
        if not self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first():
            self.db.add(Tenant(id=self.tenant_id, name=org["name"], email="compliance-demo@agroai.local", tier="enterprise", active=True))
            self.db.flush()
        self.db.add(ComplianceOrganizationRole(
            id=org["id"], tenant_id=self.tenant_id, organization_name=org["name"], owner=org["owner"],
            operator=org["operator"], reporting_agent=org["reporting_agent"],
            authorization_artifact_id=org["authorization_artifact_id"], consent_scope=org["consent_scope"],
            reviewer_role=org["reviewer_role"],
        ))
        for jur in VINEYARD_FIXTURE["jurisdictions"]:
            self.db.add(ComplianceJurisdiction(
                id=jur["id"], tenant_id=self.tenant_id, country_code="US", state=jur["state"], county=jur["county"],
                basin=jur["basin"], subbasin=jur["subbasin"], gsa=jur["gsa"], district=jur["district"],
                authority_name=jur["gsa"], jurisdiction_pack=jur["jurisdiction_pack"], pack_version=jur["pack_version"],
                reporting_year=str(jur["reporting_year"]), reporting_deadline=date.fromisoformat(jur["reporting_deadline"]),
                workflow_type=jur["workflow_type"], legal_review_status="approved", enabled=True,
            ))
        for parcel in VINEYARD_FIXTURE["parcels"]:
            self.db.add(ComplianceParcel(id=parcel["id"], tenant_id=self.tenant_id, apn=parcel["apn"], geometry_ref=parcel["geometry_ref"], county=parcel["county"]))
        for well in VINEYARD_FIXTURE["wells"]:
            self.db.add(ComplianceWell(id=well["id"], tenant_id=self.tenant_id, parcel_id=well["parcel_id"], well_identifier=well["well_identifier"], latitude=well["latitude"], longitude=well["longitude"], well_capacity=well["well_capacity_gpm"], capacity_unit="gpm"))
        for meter in VINEYARD_FIXTURE["meters"]:
            self.db.add(ComplianceMeter(id=meter["id"], tenant_id=self.tenant_id, well_id=meter["well_id"], meter_identifier=meter["meter_identifier"], manufacturer=meter["manufacturer"], serial_number=meter["serial_number"], measurement_method=meter["measurement_method"], calibration_date=date.fromisoformat(meter["calibration_date"]), calibration_document_ref=meter["calibration_document_ref"]))
        for measurement in VINEYARD_FIXTURE["measurements"]:
            self.db.add(ComplianceMeasurement(
                id=measurement["id"], tenant_id=self.tenant_id, measurement_type=measurement["measurement_type"],
                source_system=measurement["source_system"], truth_label=measurement["truth_label"],
                source_timestamp=datetime.fromisoformat(measurement["source_timestamp"].replace("Z", "+00:00")).replace(tzinfo=None),
                ingestion_timestamp=datetime.fromisoformat(measurement["ingestion_timestamp"].replace("Z", "+00:00")).replace(tzinfo=None),
                value=measurement["value"], unit=measurement["unit"], method=measurement["method"],
                confidence=measurement.get("confidence"), quality_status=measurement["quality_status"],
                related_asset_type=measurement["asset_type"], related_asset_id=measurement["asset_id"],
                reporting_period=measurement["reporting_period"], correction_lineage=measurement.get("correction_lineage", []),
            ))
        for row in VINEYARD_FIXTURE["reconciliation"]:
            self.db.add(ComplianceExecutionLedger(
                id=row["id"], tenant_id=self.tenant_id, recommendation_id=row["recommendation_id"],
                approved_recommendation_id=row["approved_recommendation_id"], scheduled_event_id=row["scheduled_event_id"],
                controller_command_id=row["controller_command_id"], applied_event_id=row["applied_event_id"],
                measured_extraction_id=row["measured_extraction_id"], variance=row["variance_af"],
                operator_note=row["operator_note"], truth_labels=row["truth_labels"], reporting_period="2026",
                ledger_payload=row,
            ))
        for budget in VINEYARD_FIXTURE["water_budgets"]:
            self.db.add(ComplianceWaterBudget(id=budget["id"], tenant_id=self.tenant_id, allocation=budget["allocation_af"], extraction=budget["extraction_af"], irrigation_application=budget["irrigation_application_af"], remaining_balance=budget["remaining_balance_af"], projected_balance=budget["projected_balance_af"], threshold_status=budget["threshold_status"], water_source=budget["water_source"], reporting_period=budget["reporting_period"]))
        for ev in VINEYARD_FIXTURE["evidence"]:
            self.db.add(ComplianceEvidence(id=ev["id"], tenant_id=self.tenant_id, artifact_type=ev["artifact_type"], file_ref=ev["file_ref"], truth_label=ev["truth_label"], review_status=ev["review_status"], metadata_json={}))
        self.db.commit()

    def organization(self) -> dict[str, Any]:
        row = self.db.query(ComplianceOrganizationRole).filter(ComplianceOrganizationRole.tenant_id == self.tenant_id).first()
        return {} if not row else {"id": row.id, "name": row.organization_name, "owner": row.owner, "operator": row.operator, "reporting_agent": row.reporting_agent, "authorization_artifact_id": row.authorization_artifact_id, "consent_scope": row.consent_scope, "reviewer_role": row.reviewer_role}

    def jurisdictions(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceJurisdiction).filter(ComplianceJurisdiction.tenant_id == self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "country_code": r.country_code, "state": r.state, "county": r.county, "basin": r.basin, "subbasin": r.subbasin, "gsa": r.gsa, "district": r.district, "authority_name": r.authority_name, "jurisdiction_pack": r.jurisdiction_pack, "pack_version": r.pack_version, "reporting_year": int(r.reporting_year) if str(r.reporting_year).isdigit() else r.reporting_year, "reporting_deadline": r.reporting_deadline.isoformat(), "workflow_type": r.workflow_type, "legal_review_status": r.legal_review_status, "enabled": r.enabled} for r in rows]

    def parcels(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "organization_id": r.tenant_id, "apn": r.apn, "geometry_ref": r.geometry_ref, "county": r.county} for r in self.db.query(ComplianceParcel).filter(ComplianceParcel.tenant_id == self.tenant_id).all()]

    def wells(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "organization_id": r.tenant_id, "parcel_id": r.parcel_id, "well_identifier": r.well_identifier, "latitude": r.latitude, "longitude": r.longitude, "well_capacity_gpm": r.well_capacity, "capacity_unit": r.capacity_unit} for r in self.db.query(ComplianceWell).filter(ComplianceWell.tenant_id == self.tenant_id).all()]

    def meters(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "organization_id": r.tenant_id, "well_id": r.well_id, "meter_identifier": r.meter_identifier, "manufacturer": r.manufacturer, "serial_number": r.serial_number, "measurement_method": r.measurement_method, "calibration_date": r.calibration_date.isoformat() if r.calibration_date else None, "calibration_document_ref": r.calibration_document_ref} for r in self.db.query(ComplianceMeter).filter(ComplianceMeter.tenant_id == self.tenant_id).all()]

    def measurements(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceMeasurement).filter(ComplianceMeasurement.tenant_id == self.tenant_id).order_by(ComplianceMeasurement.source_timestamp).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "asset_type": r.related_asset_type, "asset_id": r.related_asset_id, "measurement_type": r.measurement_type, "value": r.value, "unit": r.unit, "method": r.method, "truth_label": r.truth_label, "source_system": r.source_system, "source_timestamp": r.source_timestamp.isoformat(), "ingestion_timestamp": r.ingestion_timestamp.isoformat(), "quality_status": r.quality_status, "confidence": r.confidence, "reporting_period": r.reporting_period, "correction_lineage": r.correction_lineage or []} for r in rows]

    def add_measurement(self, payload: dict[str, Any]) -> dict[str, Any]:
        label = payload.get("truth_label")
        if label not in TRUTH_LABELS:
            raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
        source_ts = datetime.fromisoformat(str(payload["source_timestamp"]).replace("Z", "+00:00")).replace(tzinfo=None)
        row = ComplianceMeasurement(id=payload.get("id") or f"meas-{uuid.uuid4().hex[:12]}", tenant_id=self.tenant_id, measurement_type=payload["measurement_type"], source_system=payload["source_system"], truth_label=label, source_timestamp=source_ts, ingestion_timestamp=datetime.now(timezone.utc).replace(tzinfo=None), value=float(payload["value"]), unit=payload["unit"], method=payload["method"], confidence=payload.get("confidence"), quality_status=payload.get("quality_status", "pending_review"), related_asset_type=payload["asset_type"], related_asset_id=payload["asset_id"], reporting_period=str(payload["reporting_period"]), correction_lineage=payload.get("correction_lineage", []))
        self.db.add(row)
        self.db.commit()
        return self.measurement(row.id)

    def measurement(self, measurement_id: str) -> dict[str, Any]:
        return next(m for m in self.measurements() if m["id"] == measurement_id)

    def evidence(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "organization_id": r.tenant_id, "artifact_type": r.artifact_type, "file_ref": r.file_ref, "truth_label": r.truth_label, "review_status": r.review_status, "metadata": r.metadata_json or {}} for r in self.db.query(ComplianceEvidence).filter(ComplianceEvidence.tenant_id == self.tenant_id).all()]

    def add_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        label = payload.get("truth_label", "reported")
        if label not in TRUTH_LABELS:
            raise ValueError("invalid truth_label")
        row = ComplianceEvidence(id=payload.get("id") or f"ev-{uuid.uuid4().hex[:12]}", tenant_id=self.tenant_id, artifact_type=payload["artifact_type"], file_ref=payload["file_ref"], truth_label=label, review_status=payload.get("review_status", "pending_review"), metadata_json={"notes": payload.get("notes")})
        self.db.add(row)
        self.db.commit()
        return next(e for e in self.evidence() if e["id"] == row.id)

    def reconciliation(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceExecutionLedger).filter(ComplianceExecutionLedger.tenant_id == self.tenant_id).all()
        return [r.ledger_payload or {"id": r.id, "organization_id": r.tenant_id, "recommendation_id": r.recommendation_id, "approved_recommendation_id": r.approved_recommendation_id, "scheduled_event_id": r.scheduled_event_id, "controller_command_id": r.controller_command_id, "applied_event_id": r.applied_event_id, "measured_extraction_id": r.measured_extraction_id, "variance_af": r.variance, "operator_note": r.operator_note, "truth_labels": r.truth_labels} for r in rows]

    def water_budgets(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceWaterBudget).filter(ComplianceWaterBudget.tenant_id == self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "reporting_period": r.reporting_period, "water_source": r.water_source, "allocation_af": r.allocation, "extraction_af": r.extraction, "irrigation_application_af": r.irrigation_application, "remaining_balance_af": r.remaining_balance, "projected_balance_af": r.projected_balance, "threshold_status": r.threshold_status} for r in rows]

    def audit_log(self) -> list[dict[str, Any]]:
        rows = self.db.query(AuditLog).filter(AuditLog.tenant_id == self.tenant_id, AuditLog.resource_type.like("compliance%")).order_by(desc(AuditLog.timestamp)).limit(100).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "event": r.action, "actor": r.actor, "timestamp": r.timestamp.isoformat(), "details": r.details or {}} for r in rows]

    def save_export(self, package: dict[str, Any]) -> dict[str, Any]:
        metadata_payload = {k: v for k, v in package.items() if k != "content_base64"}
        row = ComplianceExport(
            id=package["id"], tenant_id=self.tenant_id, workflow_type=package["workflow_type"],
            export_type=package["format"], readiness_status=package["readiness"]["readiness_status"],
            file_name=package["file_name"], mime_type=package["mime_type"],
            storage_backend=package["storage_backend"], storage_ref=package["storage_ref"],
            checksum_sha256=package["checksum_sha256"], content_bytes=package["content_bytes"],
            content_base64=package.get("content_base64"), payload=metadata_payload,
        )
        self.db.add(row)
        self.db.commit()
        return package

    def get_export(self, export_id: str) -> dict[str, Any] | None:
        row = self.db.query(ComplianceExport).filter(ComplianceExport.tenant_id == self.tenant_id, ComplianceExport.id == export_id).first()
        if not row:
            return None
        payload = dict(row.payload or {})
        payload.update({
            "id": row.id, "organization_id": row.tenant_id, "workflow_type": row.workflow_type,
            "format": row.export_type, "readiness_status": row.readiness_status, "file_name": row.file_name,
            "mime_type": row.mime_type, "storage_backend": row.storage_backend, "storage_ref": row.storage_ref,
            "checksum_sha256": row.checksum_sha256, "content_bytes": row.content_bytes,
            "content_base64": row.content_base64, "download_available": bool(row.content_base64),
        })
        return payload
