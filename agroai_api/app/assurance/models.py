"""SQLAlchemy models for the Assurance Audit MVP."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


class AssurancePassport(Base):
    __tablename__ = "assurance_passports"

    id = Column(String, primary_key=True)
    # ``tenant_id`` preserves the historical API-key domain. New Enterprise
    # Portal rows use the current Organization/Workspace identity instead.
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    entity_type = Column(String, default="farm", nullable=False, index=True)
    entity_id = Column(String, nullable=True, index=True)
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
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    section_type = Column(String, nullable=False, index=True)
    status = Column(String, default="pending", nullable=False, index=True)
    readiness_score = Column(Float, default=0.0, nullable=False)
    summary = Column(Text, nullable=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "passport_id", "section_type", name="uq_assurance_section_passport_type"),
        UniqueConstraint("organization_id", "workspace_id", "passport_id", "section_type", name="uq_assurance_section_workspace_type"),
    )


class AssuranceEvidenceArtifact(Base):
    __tablename__ = "assurance_evidence_artifacts"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    # V2 treats this historical table as a Passport-to-source mapping. The
    # canonical record remains in EvidenceRecord or Field Intelligence.
    canonical_evidence_id = Column(String, ForeignKey("evidence_records.id", ondelete="RESTRICT"), nullable=True, index=True)
    field_observation_id = Column(String, ForeignKey("field_observations.id", ondelete="RESTRICT"), nullable=True, index=True)
    compliance_evidence_id = Column(String, ForeignKey("compliance_evidence.id"), nullable=True, index=True)
    workbench_artifact_id = Column(String, nullable=True, index=True)
    source_kind = Column(String, default="legacy", nullable=False, index=True)
    source_id = Column(String, nullable=True, index=True)
    evidence_type = Column(String, nullable=False, index=True)
    proof_domain = Column(String, nullable=False, index=True)
    file_ref = Column(Text, nullable=False)
    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    checksum = Column(String, nullable=True, index=True)
    truth_label = Column(String, default="reported", nullable=False, index=True)
    review_status = Column(String, default="pending_review", nullable=False, index=True)
    mapping_status = Column(String, default="mapped", nullable=False, index=True)
    source_system = Column(String, default="uploaded", nullable=False, index=True)
    event_timestamp = Column(DateTime, nullable=True, index=True)
    ingestion_timestamp = Column(DateTime, nullable=True, index=True)
    reporting_period = Column(String, nullable=True, index=True)
    confidence = Column(Float, nullable=True)
    data_quality = Column(String, default="unknown", nullable=False, index=True)
    stale_after = Column(DateTime, nullable=True, index=True)
    unresolved_issue = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "workspace_id", "passport_id", "source_kind", "source_id", "evidence_type",
            name="uq_assurance_evidence_canonical_mapping",
        ),
    )


class AssuranceChecklistItem(Base):
    __tablename__ = "assurance_checklist_items"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    rule_pack_id = Column(String, nullable=False, index=True)
    requirement_key = Column(String, nullable=False, index=True)
    section_type = Column(String, nullable=False, index=True)
    status = Column(String, default="missing", nullable=False, index=True)
    severity = Column(String, default="required", nullable=False, index=True)
    blocking = Column(Boolean, default=True, nullable=False, index=True)
    explanation = Column(Text, nullable=True)
    review_required = Column(Boolean, default=True, nullable=False, index=True)
    evidence_artifact_ids = Column(JSON, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "passport_id", "rule_pack_id", "requirement_key", name="uq_assurance_checklist_requirement"),
        UniqueConstraint("organization_id", "workspace_id", "passport_id", "rule_pack_id", "requirement_key", name="uq_assurance_checklist_workspace_requirement"),
    )


class AssuranceRiskScore(Base):
    __tablename__ = "assurance_risk_scores"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    score_type = Column(String, nullable=False, index=True)
    score = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False, index=True)
    factors = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class InputApplication(Base):
    __tablename__ = "input_applications"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
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
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
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
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
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
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
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

    __table_args__ = (
        UniqueConstraint("tenant_id", "passport_id", "lot_code", name="uq_harvest_lot_passport_code"),
        UniqueConstraint("organization_id", "workspace_id", "passport_id", "lot_code", name="uq_harvest_lot_workspace_code"),
    )


class TraceabilityEvent(Base):
    __tablename__ = "traceability_events"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
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
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
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
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=False, index=True)
    export_type = Column(String, nullable=False, index=True)
    package_type = Column(String, default="assurance_passport", nullable=False, index=True)
    package_version = Column(Integer, default=1, nullable=False)
    package_status = Column(String, default="draft_only", nullable=False, index=True)
    generated_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key = Column(String, nullable=True, index=True)
    rule_pack_versions = Column(JSON, nullable=False, default=dict)
    evidence_references = Column(JSON, nullable=False, default=list)
    generated_artifact_id = Column(
        String,
        ForeignKey("generated_artifacts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    storage_backend = Column(String, default="metadata_inline", nullable=False, index=True)
    storage_ref = Column(Text, nullable=True)
    checksum = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_assurance_exports_passport_created", "tenant_id", "passport_id", "created_at"),
        UniqueConstraint("organization_id", "passport_id", "package_type", "package_version", name="uq_assurance_package_version"),
    )


class AssuranceReviewEvent(Base):
    """Append-only human review decision for an evidence mapping or requirement."""

    __tablename__ = "assurance_review_events"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_artifact_id = Column(String, ForeignKey("assurance_evidence_artifacts.id", ondelete="RESTRICT"), nullable=True, index=True)
    checklist_item_id = Column(String, ForeignKey("assurance_checklist_items.id", ondelete="RESTRICT"), nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    actor_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_label = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    previous_state = Column(JSON, nullable=False, default=dict)
    next_state = Column(JSON, nullable=False, default=dict)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AssuranceAuditEvent(Base):
    """Append-only provenance ledger for material Assurance events."""

    __tablename__ = "assurance_audit_events"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    actor_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    source_system = Column(String, default="assurance", nullable=False, index=True)
    subject_type = Column(String, nullable=True, index=True)
    subject_id = Column(String, nullable=True, index=True)
    rule_pack_versions = Column(JSON, nullable=False, default=dict)
    details_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (Index("ix_assurance_audit_passport_time", "passport_id", "created_at"),)
