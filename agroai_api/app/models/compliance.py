"""SQLAlchemy models for the compliance kernel."""
from datetime import datetime
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from app.db.base import Base


class ComplianceJurisdiction(Base):
    __tablename__ = "compliance_jurisdictions"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    country_code = Column(String, nullable=False, default="US", index=True)
    region_name = Column(String, nullable=True, index=True)
    state = Column(String, nullable=False, index=True)
    county = Column(String, nullable=False, index=True)
    basin = Column(String, nullable=True, index=True)
    subbasin = Column(String, nullable=True, index=True)
    gsa = Column(String, nullable=True, index=True)
    district = Column(String, nullable=True)
    authority_name = Column(String, nullable=True, index=True)
    jurisdiction_pack = Column(String, nullable=False, index=True)
    pack_version = Column(String, nullable=True, index=True)
    legal_review_status = Column(String, nullable=False, default="pending_legal_review", index=True)
    enabled = Column(Boolean, default=False, nullable=False, index=True)
    reporting_year = Column(String, nullable=False, index=True)
    reporting_deadline = Column(Date, nullable=False, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ComplianceOrganizationRole(Base):
    __tablename__ = "compliance_organization_roles"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    organization_name = Column(String, nullable=False)
    owner = Column(String, nullable=True)
    operator = Column(String, nullable=True)
    reporting_agent = Column(String, nullable=True)
    authorization_artifact_id = Column(String, nullable=True, index=True)
    consent_scope = Column(Text, nullable=True)
    reviewer_role = Column(String, nullable=True)


class ComplianceParcel(Base):
    __tablename__ = "compliance_parcels"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    apn = Column(String, nullable=False, index=True)
    geometry_ref = Column(Text, nullable=True)
    geometry = Column(JSON, nullable=True)
    county = Column(String, nullable=True, index=True)
    __table_args__ = (UniqueConstraint("tenant_id", "apn", name="uq_compliance_parcel_tenant_apn"),)


class ComplianceWell(Base):
    __tablename__ = "compliance_wells"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    parcel_id = Column(String, ForeignKey("compliance_parcels.id"), nullable=True, index=True)
    well_identifier = Column(String, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    well_capacity = Column(Float, nullable=True)
    capacity_unit = Column(String, default="gpm")
    __table_args__ = (UniqueConstraint("tenant_id", "well_identifier", name="uq_compliance_well_tenant_identifier"),)


class ComplianceMeter(Base):
    __tablename__ = "compliance_meters"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    well_id = Column(String, ForeignKey("compliance_wells.id"), nullable=False, index=True)
    meter_identifier = Column(String, nullable=False, index=True)
    manufacturer = Column(String, nullable=True)
    serial_number = Column(String, nullable=True, index=True)
    measurement_method = Column(String, nullable=False)
    calibration_date = Column(Date, nullable=True, index=True)
    calibration_document_ref = Column(Text, nullable=True)


class ComplianceMeasurement(Base):
    __tablename__ = "compliance_measurements"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    measurement_type = Column(String, nullable=False, index=True)
    source_system = Column(String, nullable=False, index=True)
    truth_label = Column(String, nullable=False, index=True)
    source_timestamp = Column(DateTime, nullable=False, index=True)
    ingestion_timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    value = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    method = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    quality_status = Column(String, nullable=False, index=True)
    related_asset_type = Column(String, nullable=False)
    related_asset_id = Column(String, nullable=False, index=True)
    reporting_period = Column(String, nullable=False, index=True)
    correction_lineage = Column(JSON, nullable=True)
    __table_args__ = (Index("ix_compliance_measurement_asset_period", "tenant_id", "related_asset_id", "reporting_period"),)


class ComplianceExecutionLedger(Base):
    __tablename__ = "compliance_execution_ledger"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    recommendation_id = Column(String, nullable=True, index=True)
    approved_recommendation_id = Column(String, nullable=True, index=True)
    scheduled_event_id = Column(String, nullable=True, index=True)
    controller_command_id = Column(String, nullable=True, index=True)
    applied_event_id = Column(String, nullable=True, index=True)
    measured_extraction_id = Column(String, nullable=True, index=True)
    variance = Column(Float, nullable=True)
    operator_note = Column(Text, nullable=True)
    truth_labels = Column(JSON, nullable=False)
    ledger_payload = Column(JSON, nullable=True)
    reporting_period = Column(String, nullable=False, index=True)


class ComplianceWaterBudget(Base):
    __tablename__ = "compliance_water_budgets"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    allocation = Column(Float, nullable=False)
    extraction = Column(Float, nullable=False)
    irrigation_application = Column(Float, nullable=False)
    remaining_balance = Column(Float, nullable=False)
    projected_balance = Column(Float, nullable=False)
    threshold_status = Column(String, nullable=False, index=True)
    water_source = Column(String, nullable=False, index=True)
    reporting_period = Column(String, nullable=False, index=True)


class ComplianceEvidence(Base):
    __tablename__ = "compliance_evidence"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    artifact_type = Column(String, nullable=False, index=True)
    file_ref = Column(Text, nullable=False)
    truth_label = Column(String, nullable=False, index=True)
    review_status = Column(String, nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ComplianceRulePack(Base):
    __tablename__ = "compliance_rule_packs"
    id = Column(String, primary_key=True)
    pack_id = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, index=True)
    effective_date = Column(Date, nullable=False, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    required_fields = Column(JSON, nullable=False)
    conditional_fields = Column(JSON, nullable=False)
    validation_rules = Column(JSON, nullable=False)
    deadlines = Column(JSON, nullable=False)
    warning_thresholds = Column(JSON, nullable=False)
    export_schema = Column(JSON, nullable=False)
    disclaimer_text = Column(Text, nullable=False)
    country_code = Column(String, nullable=False, default="US", index=True)
    authority_name = Column(String, nullable=True, index=True)
    legal_review_status = Column(String, nullable=False, default="pending_legal_review", index=True)
    enabled = Column(Boolean, default=False, nullable=False, index=True)


class ComplianceReadinessSnapshot(Base):
    __tablename__ = "compliance_readiness_snapshots"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    reporting_year = Column(String, nullable=False, index=True)
    readiness_status = Column(String, nullable=False, index=True)
    readiness_percentage = Column(Float, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ComplianceExport(Base):
    __tablename__ = "compliance_exports"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    export_type = Column(String, nullable=False, index=True)
    readiness_status = Column(String, nullable=False, index=True)
    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    storage_backend = Column(String, nullable=False, default="database_dev_fallback", index=True)
    storage_ref = Column(Text, nullable=False)
    checksum_sha256 = Column(String, nullable=False, index=True)
    content_bytes = Column(Integer, nullable=False, default=0)
    content_base64 = Column(Text, nullable=True)  # local development/demo fallback only
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_compliance_export_tenant_type", "tenant_id", "export_type", "created_at"),
    )
