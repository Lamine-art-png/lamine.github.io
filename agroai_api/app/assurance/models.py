"""SQLAlchemy models for the Assurance Audit MVP."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint

from app.db.base import Base


class AssurancePassport(Base):
    __tablename__ = "assurance_passports"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    farm_name = Column(String, nullable=False, index=True)
    farm_location = Column(String, nullable=True)
    crop = Column(String, nullable=True, index=True)
    season = Column(String, nullable=True, index=True)
    reporting_period = Column(String, nullable=True, index=True)
    status = Column(String, default="draft", nullable=False, index=True)
    rule_pack_ids = Column(JSON, nullable=False)
    jurisdiction_id = Column(String, ForeignKey("compliance_jurisdictions.id"), nullable=True, index=True)
    parcel_ids = Column(JSON, nullable=False)
    metadata_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class AssurancePassportSection(Base):
    __tablename__ = "assurance_passport_sections"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    section_type = Column(String, nullable=False, index=True)
    status = Column(String, default="pending", nullable=False, index=True)
    readiness_score = Column(Float, default=0.0, nullable=False)
    summary = Column(Text, nullable=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "passport_id", "section_type", name="uq_assurance_section_passport_type"),)


class AssuranceEvidenceArtifact(Base):
    __tablename__ = "assurance_evidence_artifacts"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    compliance_evidence_id = Column(String, ForeignKey("compliance_evidence.id"), nullable=True, index=True)
    workbench_artifact_id = Column(String, nullable=True, index=True)
    evidence_type = Column(String, nullable=False, index=True)
    proof_domain = Column(String, nullable=False, index=True)
    file_ref = Column(Text, nullable=False)
    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    checksum = Column(String, nullable=True, index=True)
    truth_label = Column(String, default="reported", nullable=False, index=True)
    review_status = Column(String, default="pending_review", nullable=False, index=True)
    source_system = Column(String, default="uploaded", nullable=False, index=True)
    metadata_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AssuranceChecklistItem(Base):
    __tablename__ = "assurance_checklist_items"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    rule_pack_id = Column(String, nullable=False, index=True)
    requirement_key = Column(String, nullable=False, index=True)
    section_type = Column(String, nullable=False, index=True)
    status = Column(String, default="missing", nullable=False, index=True)
    severity = Column(String, default="required", nullable=False, index=True)
    evidence_artifact_ids = Column(JSON, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "passport_id", "rule_pack_id", "requirement_key", name="uq_assurance_checklist_requirement"),)


class AssuranceRiskScore(Base):
    __tablename__ = "assurance_risk_scores"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    score_type = Column(String, nullable=False, index=True)
    score = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False, index=True)
    factors = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class InputApplication(Base):
    __tablename__ = "input_applications"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    application_type = Column(String, nullable=False, index=True)
    applied_at = Column(DateTime, nullable=True, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=True, index=True)
    parcel_id = Column(String, ForeignKey("compliance_parcels.id"), nullable=True, index=True)
    product_name = Column(String, nullable=False, index=True)
    quantity = Column(Float, nullable=True)
    unit = Column(String, nullable=True)
    operator = Column(String, nullable=True)
    truth_label = Column(String, default="reported", nullable=False, index=True)
    evidence_artifact_id = Column(String, ForeignKey("assurance_evidence_artifacts.id"), nullable=True, index=True)
    metadata_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PesticideApplication(Base):
    __tablename__ = "pesticide_applications"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    input_application_id = Column(String, ForeignKey("input_applications.id"), nullable=False, index=True)
    active_ingredient = Column(String, nullable=True, index=True)
    target_pest = Column(String, nullable=True)
    reentry_interval_hours = Column(Float, nullable=True)
    preharvest_interval_days = Column(Float, nullable=True)
    label_reference = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=False)


class FertilizerApplication(Base):
    __tablename__ = "fertilizer_applications"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    input_application_id = Column(String, ForeignKey("input_applications.id"), nullable=False, index=True)
    nutrient_profile = Column(JSON, nullable=False)
    nitrogen_kg = Column(Float, nullable=True)
    phosphorus_kg = Column(Float, nullable=True)
    potassium_kg = Column(Float, nullable=True)
    metadata_json = Column(JSON, nullable=False)


class HarvestLot(Base):
    __tablename__ = "harvest_lots"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    lot_code = Column(String, nullable=False, index=True)
    crop = Column(String, nullable=True, index=True)
    variety = Column(String, nullable=True)
    harvested_at = Column(DateTime, nullable=True, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=True, index=True)
    parcel_id = Column(String, ForeignKey("compliance_parcels.id"), nullable=True, index=True)
    quantity = Column(Float, nullable=True)
    unit = Column(String, nullable=True)
    destination = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (UniqueConstraint("tenant_id", "passport_id", "lot_code", name="uq_harvest_lot_passport_code"),)


class TraceabilityEvent(Base):
    __tablename__ = "traceability_events"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    harvest_lot_id = Column(String, ForeignKey("harvest_lots.id"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    occurred_at = Column(DateTime, nullable=True, index=True)
    location = Column(String, nullable=True)
    actor = Column(String, nullable=True)
    evidence_artifact_id = Column(String, ForeignKey("assurance_evidence_artifacts.id"), nullable=True, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class BuyerRequirement(Base):
    __tablename__ = "buyer_requirements"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    buyer_name = Column(String, nullable=False, index=True)
    requirement_key = Column(String, nullable=False, index=True)
    standard = Column(String, nullable=True, index=True)
    description = Column(Text, nullable=False)
    rule_pack_id = Column(String, nullable=True, index=True)
    status = Column(String, default="active", nullable=False, index=True)
    metadata_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class RulePack(Base):
    __tablename__ = "assurance_rule_packs"

    id = Column(String, primary_key=True)
    scope = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, index=True)
    status = Column(String, default="active", nullable=False, index=True)
    required_evidence_types = Column(JSON, nullable=False)
    checklist = Column(JSON, nullable=False)
    validation_rules = Column(JSON, nullable=False)
    scoring_weights = Column(JSON, nullable=False)
    disclaimer_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AssuranceExport(Base):
    __tablename__ = "assurance_exports"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    export_type = Column(String, nullable=False, index=True)
    storage_backend = Column(String, default="metadata_inline", nullable=False, index=True)
    storage_ref = Column(Text, nullable=True)
    checksum = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("ix_assurance_exports_passport_created", "tenant_id", "passport_id", "created_at"),)

