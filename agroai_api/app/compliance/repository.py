"""Tenant-scoped persistence repository for the compliance kernel."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.compliance.constants import APPROVED_FIXTURE_TENANT_ID
from app.compliance.fixtures import VINEYARD_FIXTURE
from app.models.tenant import Tenant
from app.models.compliance import (
    ComplianceEvidence,
    ComplianceExecutionLedger,
    ComplianceExportMetadata,
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


def _iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _dt(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _date(value: str | date | None) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    return date.fromisoformat(str(value))


class ComplianceRepository:
    """Read and write compliance records for exactly one authenticated tenant."""

    def __init__(self, db: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.db = db
        self.tenant_id = tenant_id

    def ensure_demo_tenant(self) -> None:
        """Provision the approved representative tenant for explicit demo mode only."""
        if self.tenant_id != APPROVED_FIXTURE_TENANT_ID:
            raise ValueError("demo tenant provisioning is restricted to the approved fixture tenant")
        if not self.db.query(Tenant).filter_by(id=self.tenant_id).first():
            self.db.add(Tenant(
                id=self.tenant_id,
                name="Non-production representative California vineyard tenant",
                email="demo-fixture@agroai.example",
                tier="demo",
                active=True,
            ))
            self.db.flush()

    def seed_demo_fixtures(self) -> None:
        """Seed approved non-production fixture data for the approved demo tenant only."""
        if self.tenant_id != APPROVED_FIXTURE_TENANT_ID:
            raise ValueError("demo fixtures can only be seeded for the approved fixture tenant")
        self.ensure_demo_tenant()
        if self.db.query(ComplianceOrganizationRole).filter_by(tenant_id=self.tenant_id).first():
            return
        org = VINEYARD_FIXTURE["organization"]
        self.db.add(ComplianceOrganizationRole(
            id=f"role-{self.tenant_id}", tenant_id=self.tenant_id,
            organization_name=org.get("name", self.tenant_id), owner=org.get("owner"),
            operator=org.get("operator"), reporting_agent=org.get("reporting_agent"),
        ))
        for row in VINEYARD_FIXTURE["jurisdictions"]:
            self.db.add(ComplianceJurisdiction(
                id=row["id"], tenant_id=self.tenant_id, state=row.get("state"), county=row.get("county"),
                basin=row.get("basin"), subbasin=row.get("subbasin"), gsa=row.get("gsa"), district=row.get("district"),
                jurisdiction_pack=row.get("jurisdiction_pack", "california_sgma_v0_1"), reporting_year=str(row.get("reporting_year")),
                reporting_deadline=_date(row.get("reporting_deadline")), workflow_type=row.get("workflow_type"),
                country="US", jurisdiction_level="state", authority_name=row.get("gsa") or row.get("district"),
            ))
        self.db.flush()
        for row in VINEYARD_FIXTURE["parcels"]:
            self.db.add(ComplianceParcel(
                id=row["id"], tenant_id=self.tenant_id, apn=row.get("apn"), parcel_identifier=row.get("parcel_identifier") or row.get("apn") or row["id"],
                country="US", state="CA", county=row.get("county"), geometry_ref=row.get("geometry_ref"), geometry=row.get("geometry"),
            ))
        self.db.flush()
        for row in VINEYARD_FIXTURE["wells"]:
            self.db.add(ComplianceWell(
                id=row["id"], tenant_id=self.tenant_id, parcel_id=row.get("parcel_id"), well_identifier=row.get("well_identifier"),
                latitude=row.get("latitude"), longitude=row.get("longitude"), well_capacity=row.get("well_capacity_gpm"), capacity_unit="gpm",
            ))
        self.db.flush()
        for row in VINEYARD_FIXTURE["meters"]:
            self.db.add(ComplianceMeter(
                id=row["id"], tenant_id=self.tenant_id, well_id=row.get("well_id"), meter_identifier=row.get("meter_identifier"),
                manufacturer=row.get("manufacturer"), serial_number=row.get("serial_number"), measurement_method=row.get("measurement_method"),
                calibration_date=_date(row.get("calibration_date")), calibration_document_ref=row.get("calibration_document_ref"),
            ))
        self.db.flush()
        for row in VINEYARD_FIXTURE["measurements"]:
            self.add_measurement({
                "id": row.get("id"), "asset_type": row.get("asset_type"), "asset_id": row.get("asset_id"),
                "measurement_type": row.get("measurement_type"), "value": row.get("value"), "unit": row.get("unit"),
                "method": row.get("method"), "truth_label": row.get("truth_label"), "source_system": row.get("source_system"),
                "source_timestamp": row.get("source_timestamp"), "ingestion_timestamp": row.get("ingestion_timestamp"),
                "quality_status": row.get("quality_status"), "reporting_period": row.get("reporting_period"),
                "confidence": row.get("confidence"), "correction_lineage": row.get("correction_lineage", []),
            }, commit=False)
        self.db.flush()
        for row in VINEYARD_FIXTURE["evidence"]:
            self.db.add(ComplianceEvidence(
                id=row["id"], tenant_id=self.tenant_id, artifact_type=row.get("artifact_type"), file_ref=row.get("file_ref", "demo-fixture"),
                truth_label=row.get("truth_label", "reported"), review_status=row.get("review_status", "pending_review"),
                metadata_json={"notes": row.get("notes"), "demo_fixture": True},
            ))
        for row in VINEYARD_FIXTURE["water_budgets"]:
            remaining = float(row.get("allocation_af", 0)) - float(row.get("extraction_af", 0))
            self.db.add(ComplianceWaterBudget(
                id=row["id"], tenant_id=self.tenant_id, allocation=row.get("allocation_af", 0), extraction=row.get("extraction_af", 0),
                irrigation_application=row.get("irrigation_application_af", 0), remaining_balance=remaining,
                projected_balance=row.get("projected_balance_af", remaining), threshold_status="unchecked",
                water_source=row.get("water_source", "groundwater"), reporting_period=str(row.get("reporting_period")),
            ))
        for row in VINEYARD_FIXTURE["reconciliation"]:
            self.db.add(ComplianceExecutionLedger(
                id=row["id"], tenant_id=self.tenant_id, recommendation_id=row.get("recommendation_id"),
                measured_extraction_id=row.get("measured_extraction_id"), variance=row.get("variance_af"),
                operator_note=row.get("operator_note"), truth_labels=row.get("truth_labels", {}),
                reporting_period=str(row.get("reporting_period")), payload=row,
            ))
        self.db.commit()

    def organization(self) -> dict[str, Any]:
        row = self.db.query(ComplianceOrganizationRole).filter_by(tenant_id=self.tenant_id).first()
        if not row:
            return {"id": self.tenant_id}
        return {"id": self.tenant_id, "name": row.organization_name, "owner": row.owner, "operator": row.operator, "reporting_agent": row.reporting_agent}

    def list_jurisdictions(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceJurisdiction).filter_by(tenant_id=self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "country": r.country, "jurisdiction_level": r.jurisdiction_level, "authority_name": r.authority_name, "state": r.state, "county": r.county, "basin": r.basin, "subbasin": r.subbasin, "gsa": r.gsa, "district": r.district, "jurisdiction_pack": r.jurisdiction_pack, "reporting_year": r.reporting_year, "reporting_deadline": _iso(r.reporting_deadline), "workflow_type": r.workflow_type} for r in rows]

    def list_parcels(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceParcel).filter_by(tenant_id=self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "apn": r.apn, "parcel_identifier": r.parcel_identifier, "country": r.country, "state": r.state, "county": r.county, "geometry_ref": r.geometry_ref, "geometry": r.geometry} for r in rows]

    def list_wells(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceWell).filter_by(tenant_id=self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "parcel_id": r.parcel_id, "well_identifier": r.well_identifier, "latitude": r.latitude, "longitude": r.longitude, "well_capacity": r.well_capacity, "capacity_unit": r.capacity_unit} for r in rows]

    def list_meters(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceMeter).filter_by(tenant_id=self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "well_id": r.well_id, "meter_identifier": r.meter_identifier, "manufacturer": r.manufacturer, "serial_number": r.serial_number, "measurement_method": r.measurement_method, "calibration_date": _iso(r.calibration_date), "calibration_document_ref": r.calibration_document_ref} for r in rows]

    def list_measurements(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceMeasurement).filter_by(tenant_id=self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "asset_type": r.related_asset_type, "asset_id": r.related_asset_id, "measurement_type": r.measurement_type, "value": r.value, "unit": r.unit, "method": r.method, "truth_label": r.truth_label, "source_system": r.source_system, "source_timestamp": _iso(r.source_timestamp), "ingestion_timestamp": _iso(r.ingestion_timestamp), "quality_status": r.quality_status, "reporting_period": r.reporting_period, "confidence": r.confidence, "correction_lineage": r.correction_lineage or []} for r in rows]

    def list_evidence(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceEvidence).filter_by(tenant_id=self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "artifact_type": r.artifact_type, "file_ref": r.file_ref, "truth_label": r.truth_label, "review_status": r.review_status, "metadata": r.metadata_json or {}} for r in rows]

    def list_budgets(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceWaterBudget).filter_by(tenant_id=self.tenant_id).all()
        return [{"id": r.id, "organization_id": r.tenant_id, "allocation_af": r.allocation, "extraction_af": r.extraction, "irrigation_application_af": r.irrigation_application, "remaining_balance_af": r.remaining_balance, "projected_balance_af": r.projected_balance, "threshold_status": r.threshold_status, "water_source": r.water_source, "reporting_period": r.reporting_period} for r in rows]

    def list_execution_ledger(self) -> list[dict[str, Any]]:
        rows = self.db.query(ComplianceExecutionLedger).filter_by(tenant_id=self.tenant_id).all()
        result = []
        for r in rows:
            payload = dict(r.payload or {})
            variance = r.variance
            planned = payload.get("recommended_volume_af") or payload.get("approved_volume_af") or payload.get("planned_volume_af")
            applied = payload.get("applied_volume_af") or payload.get("measured_volume_af")
            if variance is None and planned is not None and applied is not None:
                variance = float(applied) - float(planned)
            variance_pct = payload.get("variance_pct")
            if variance_pct is None and variance is not None and planned not in (None, 0, 0.0):
                variance_pct = round(float(variance) / float(planned) * 100, 2)
            payload.update({
                "id": r.id, "organization_id": r.tenant_id, "recommendation_id": r.recommendation_id,
                "measured_extraction_id": r.measured_extraction_id, "variance_af": variance, "variance_pct": variance_pct,
                "operator_note": r.operator_note, "truth_labels": r.truth_labels, "reporting_period": r.reporting_period,
            })
            result.append(payload)
        return result

    def list_assets(self, kind: str) -> list[dict[str, Any]]:
        return {"parcels": self.list_parcels, "wells": self.list_wells, "meters": self.list_meters}[kind]()

    def _asset_exists(self, asset_type: str, asset_id: str) -> bool:
        model = {"parcel": ComplianceParcel, "well": ComplianceWell, "meter": ComplianceMeter}.get(asset_type)
        if not model:
            return False
        return self.db.query(model).filter_by(tenant_id=self.tenant_id, id=asset_id).first() is not None

    def add_measurement(self, payload: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        self.db.flush()
        if not self._asset_exists(payload["asset_type"], payload["asset_id"]):
            raise ValueError("measurement asset does not belong to authenticated tenant")
        row = ComplianceMeasurement(
            id=payload.get("id") or f"meas-{uuid.uuid4().hex[:12]}", tenant_id=self.tenant_id,
            measurement_type=payload["measurement_type"], source_system=payload["source_system"], truth_label=payload["truth_label"],
            source_timestamp=_dt(payload.get("source_timestamp")), ingestion_timestamp=_dt(payload.get("ingestion_timestamp")),
            value=float(payload["value"]), unit=payload["unit"], method=payload["method"], confidence=payload.get("confidence"),
            quality_status=payload.get("quality_status", "pending_review"), related_asset_type=payload["asset_type"], related_asset_id=payload["asset_id"],
            reporting_period=str(payload["reporting_period"]), correction_lineage=payload.get("correction_lineage", []),
        )
        self.db.add(row)
        if commit:
            self.db.commit()
        return {"id": row.id, "organization_id": self.tenant_id, **payload}

    def add_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = ComplianceEvidence(
            id=payload.get("id") or f"ev-{uuid.uuid4().hex[:12]}", tenant_id=self.tenant_id,
            artifact_type=payload["artifact_type"], file_ref=payload["file_ref"], truth_label=payload.get("truth_label", "reported"),
            review_status=payload.get("review_status", "pending_review"), metadata_json={"notes": payload.get("notes")},
        )
        self.db.add(row)
        self.db.commit()
        return {"id": row.id, "organization_id": self.tenant_id, **payload}

    def persist_readiness_snapshot(self, payload: dict[str, Any], reporting_year: str | None = None) -> dict[str, Any]:
        snapshot = ComplianceReadinessSnapshot(
            id=f"ready-{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            workflow_type=payload["workflow_type"],
            reporting_year=str(reporting_year or payload.get("reporting_year") or datetime.utcnow().year),
            readiness_status=payload["readiness_status"],
            readiness_percentage=float(payload["readiness_percentage"]),
            payload=payload,
            created_at=datetime.utcnow(),
        )
        self.db.add(snapshot)
        self.db.commit()
        return {"id": snapshot.id, "tenant_id": snapshot.tenant_id}

    def count_readiness_snapshots(self) -> int:
        return self.db.query(ComplianceReadinessSnapshot).filter_by(tenant_id=self.tenant_id).count()

    def persist_export_metadata(self, payload: dict[str, Any], export_type: str, workflow_type: str, storage_backend: str) -> dict[str, Any]:
        export_id = payload.get("id") or f"export-{uuid.uuid4().hex[:10]}"
        payload["id"] = export_id
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        row = ComplianceExportMetadata(
            id=export_id, tenant_id=self.tenant_id,
            export_type=export_type, workflow_type=workflow_type, storage_backend=storage_backend,
            storage_ref=None, checksum=checksum, payload=payload, created_at=datetime.utcnow(),
        )
        self.db.add(row)
        self.db.commit()
        return self.get_export(row.id) or payload

    def get_export(self, export_id: str) -> dict[str, Any] | None:
        row = self.db.query(ComplianceExportMetadata).filter_by(tenant_id=self.tenant_id, id=export_id).first()
        if not row:
            return None
        payload = dict(row.payload or {})
        payload.update({"id": row.id, "storage_backend": row.storage_backend, "storage_ref": row.storage_ref, "checksum": row.checksum})
        return payload
