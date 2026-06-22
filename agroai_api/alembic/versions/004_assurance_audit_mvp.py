"""assurance audit mvp

Revision ID: 004_assurance_audit_mvp
Revises: 003_global_compliance_kernel
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "004_assurance_audit_mvp"
down_revision = "003_global_compliance_kernel"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name):
    return table_name in inspector.get_table_names()


def _create_index(table_name, name, columns):
    op.create_index(name, table_name, columns)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "assurance_passports"):
        op.create_table(
            "assurance_passports",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("farm_name", sa.String(), nullable=False),
            sa.Column("farm_location", sa.String(), nullable=True),
            sa.Column("crop", sa.String(), nullable=True),
            sa.Column("season", sa.String(), nullable=True),
            sa.Column("reporting_period", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("rule_pack_ids", sa.JSON(), nullable=False),
            sa.Column("jurisdiction_id", sa.String(), sa.ForeignKey("compliance_jurisdictions.id"), nullable=True),
            sa.Column("parcel_ids", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_assurance_passports_tenant_id": ["tenant_id"],
            "ix_assurance_passports_farm_name": ["farm_name"],
            "ix_assurance_passports_crop": ["crop"],
            "ix_assurance_passports_season": ["season"],
            "ix_assurance_passports_reporting_period": ["reporting_period"],
            "ix_assurance_passports_status": ["status"],
            "ix_assurance_passports_jurisdiction_id": ["jurisdiction_id"],
            "ix_assurance_passports_created_at": ["created_at"],
            "ix_assurance_passports_updated_at": ["updated_at"],
        }.items():
            _create_index("assurance_passports", name, cols)

    if not _has_table(inspector, "assurance_passport_sections"):
        op.create_table(
            "assurance_passport_sections",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("section_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("readiness_score", sa.Float(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "passport_id", "section_type", name="uq_assurance_section_passport_type"),
        )
        for name, cols in {
            "ix_assurance_passport_sections_tenant_id": ["tenant_id"],
            "ix_assurance_passport_sections_passport_id": ["passport_id"],
            "ix_assurance_passport_sections_section_type": ["section_type"],
            "ix_assurance_passport_sections_status": ["status"],
        }.items():
            _create_index("assurance_passport_sections", name, cols)

    if not _has_table(inspector, "assurance_evidence_artifacts"):
        op.create_table(
            "assurance_evidence_artifacts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("compliance_evidence_id", sa.String(), sa.ForeignKey("compliance_evidence.id"), nullable=True),
            sa.Column("workbench_artifact_id", sa.String(), nullable=True),
            sa.Column("evidence_type", sa.String(), nullable=False),
            sa.Column("proof_domain", sa.String(), nullable=False),
            sa.Column("file_ref", sa.Text(), nullable=False),
            sa.Column("filename", sa.String(), nullable=True),
            sa.Column("content_type", sa.String(), nullable=True),
            sa.Column("checksum", sa.String(), nullable=True),
            sa.Column("truth_label", sa.String(), nullable=False),
            sa.Column("review_status", sa.String(), nullable=False),
            sa.Column("source_system", sa.String(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_assurance_evidence_artifacts_tenant_id": ["tenant_id"],
            "ix_assurance_evidence_artifacts_passport_id": ["passport_id"],
            "ix_assurance_evidence_artifacts_compliance_evidence_id": ["compliance_evidence_id"],
            "ix_assurance_evidence_artifacts_workbench_artifact_id": ["workbench_artifact_id"],
            "ix_assurance_evidence_artifacts_evidence_type": ["evidence_type"],
            "ix_assurance_evidence_artifacts_proof_domain": ["proof_domain"],
            "ix_assurance_evidence_artifacts_checksum": ["checksum"],
            "ix_assurance_evidence_artifacts_truth_label": ["truth_label"],
            "ix_assurance_evidence_artifacts_review_status": ["review_status"],
            "ix_assurance_evidence_artifacts_source_system": ["source_system"],
            "ix_assurance_evidence_artifacts_created_at": ["created_at"],
        }.items():
            _create_index("assurance_evidence_artifacts", name, cols)

    if not _has_table(inspector, "assurance_checklist_items"):
        op.create_table(
            "assurance_checklist_items",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("rule_pack_id", sa.String(), nullable=False),
            sa.Column("requirement_key", sa.String(), nullable=False),
            sa.Column("section_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False),
            sa.Column("evidence_artifact_ids", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "passport_id", "rule_pack_id", "requirement_key", name="uq_assurance_checklist_requirement"),
        )
        for name, cols in {
            "ix_assurance_checklist_items_tenant_id": ["tenant_id"],
            "ix_assurance_checklist_items_passport_id": ["passport_id"],
            "ix_assurance_checklist_items_rule_pack_id": ["rule_pack_id"],
            "ix_assurance_checklist_items_requirement_key": ["requirement_key"],
            "ix_assurance_checklist_items_section_type": ["section_type"],
            "ix_assurance_checklist_items_status": ["status"],
            "ix_assurance_checklist_items_severity": ["severity"],
        }.items():
            _create_index("assurance_checklist_items", name, cols)

    if not _has_table(inspector, "assurance_risk_scores"):
        op.create_table(
            "assurance_risk_scores",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("score_type", sa.String(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("risk_level", sa.String(), nullable=False),
            sa.Column("factors", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_assurance_risk_scores_tenant_id": ["tenant_id"],
            "ix_assurance_risk_scores_passport_id": ["passport_id"],
            "ix_assurance_risk_scores_score_type": ["score_type"],
            "ix_assurance_risk_scores_risk_level": ["risk_level"],
            "ix_assurance_risk_scores_created_at": ["created_at"],
        }.items():
            _create_index("assurance_risk_scores", name, cols)

    if not _has_table(inspector, "input_applications"):
        op.create_table(
            "input_applications",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("application_type", sa.String(), nullable=False),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
            sa.Column("block_id", sa.String(), sa.ForeignKey("blocks.id"), nullable=True),
            sa.Column("parcel_id", sa.String(), sa.ForeignKey("compliance_parcels.id"), nullable=True),
            sa.Column("product_name", sa.String(), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(), nullable=True),
            sa.Column("operator", sa.String(), nullable=True),
            sa.Column("truth_label", sa.String(), nullable=False),
            sa.Column("evidence_artifact_id", sa.String(), sa.ForeignKey("assurance_evidence_artifacts.id"), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_input_applications_tenant_id": ["tenant_id"],
            "ix_input_applications_passport_id": ["passport_id"],
            "ix_input_applications_application_type": ["application_type"],
            "ix_input_applications_applied_at": ["applied_at"],
            "ix_input_applications_block_id": ["block_id"],
            "ix_input_applications_parcel_id": ["parcel_id"],
            "ix_input_applications_product_name": ["product_name"],
            "ix_input_applications_truth_label": ["truth_label"],
            "ix_input_applications_evidence_artifact_id": ["evidence_artifact_id"],
            "ix_input_applications_created_at": ["created_at"],
        }.items():
            _create_index("input_applications", name, cols)

    if not _has_table(inspector, "pesticide_applications"):
        op.create_table(
            "pesticide_applications",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("input_application_id", sa.String(), sa.ForeignKey("input_applications.id"), nullable=False),
            sa.Column("active_ingredient", sa.String(), nullable=True),
            sa.Column("target_pest", sa.String(), nullable=True),
            sa.Column("reentry_interval_hours", sa.Float(), nullable=True),
            sa.Column("preharvest_interval_days", sa.Float(), nullable=True),
            sa.Column("label_reference", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
        )
        for name, cols in {
            "ix_pesticide_applications_tenant_id": ["tenant_id"],
            "ix_pesticide_applications_passport_id": ["passport_id"],
            "ix_pesticide_applications_input_application_id": ["input_application_id"],
            "ix_pesticide_applications_active_ingredient": ["active_ingredient"],
        }.items():
            _create_index("pesticide_applications", name, cols)

    if not _has_table(inspector, "fertilizer_applications"):
        op.create_table(
            "fertilizer_applications",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("input_application_id", sa.String(), sa.ForeignKey("input_applications.id"), nullable=False),
            sa.Column("nutrient_profile", sa.JSON(), nullable=False),
            sa.Column("nitrogen_kg", sa.Float(), nullable=True),
            sa.Column("phosphorus_kg", sa.Float(), nullable=True),
            sa.Column("potassium_kg", sa.Float(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
        )
        for name, cols in {
            "ix_fertilizer_applications_tenant_id": ["tenant_id"],
            "ix_fertilizer_applications_passport_id": ["passport_id"],
            "ix_fertilizer_applications_input_application_id": ["input_application_id"],
        }.items():
            _create_index("fertilizer_applications", name, cols)

    if not _has_table(inspector, "harvest_lots"):
        op.create_table(
            "harvest_lots",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("lot_code", sa.String(), nullable=False),
            sa.Column("crop", sa.String(), nullable=True),
            sa.Column("variety", sa.String(), nullable=True),
            sa.Column("harvested_at", sa.DateTime(), nullable=True),
            sa.Column("block_id", sa.String(), sa.ForeignKey("blocks.id"), nullable=True),
            sa.Column("parcel_id", sa.String(), sa.ForeignKey("compliance_parcels.id"), nullable=True),
            sa.Column("quantity", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(), nullable=True),
            sa.Column("destination", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "passport_id", "lot_code", name="uq_harvest_lot_passport_code"),
        )
        for name, cols in {
            "ix_harvest_lots_tenant_id": ["tenant_id"],
            "ix_harvest_lots_passport_id": ["passport_id"],
            "ix_harvest_lots_lot_code": ["lot_code"],
            "ix_harvest_lots_crop": ["crop"],
            "ix_harvest_lots_harvested_at": ["harvested_at"],
            "ix_harvest_lots_block_id": ["block_id"],
            "ix_harvest_lots_parcel_id": ["parcel_id"],
            "ix_harvest_lots_created_at": ["created_at"],
        }.items():
            _create_index("harvest_lots", name, cols)

    if not _has_table(inspector, "traceability_events"):
        op.create_table(
            "traceability_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("harvest_lot_id", sa.String(), sa.ForeignKey("harvest_lots.id"), nullable=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=True),
            sa.Column("location", sa.String(), nullable=True),
            sa.Column("actor", sa.String(), nullable=True),
            sa.Column("evidence_artifact_id", sa.String(), sa.ForeignKey("assurance_evidence_artifacts.id"), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_traceability_events_tenant_id": ["tenant_id"],
            "ix_traceability_events_passport_id": ["passport_id"],
            "ix_traceability_events_harvest_lot_id": ["harvest_lot_id"],
            "ix_traceability_events_event_type": ["event_type"],
            "ix_traceability_events_occurred_at": ["occurred_at"],
            "ix_traceability_events_evidence_artifact_id": ["evidence_artifact_id"],
            "ix_traceability_events_created_at": ["created_at"],
        }.items():
            _create_index("traceability_events", name, cols)

    if not _has_table(inspector, "buyer_requirements"):
        op.create_table(
            "buyer_requirements",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("buyer_name", sa.String(), nullable=False),
            sa.Column("requirement_key", sa.String(), nullable=False),
            sa.Column("standard", sa.String(), nullable=True),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("rule_pack_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_buyer_requirements_tenant_id": ["tenant_id"],
            "ix_buyer_requirements_buyer_name": ["buyer_name"],
            "ix_buyer_requirements_requirement_key": ["requirement_key"],
            "ix_buyer_requirements_standard": ["standard"],
            "ix_buyer_requirements_rule_pack_id": ["rule_pack_id"],
            "ix_buyer_requirements_status": ["status"],
            "ix_buyer_requirements_created_at": ["created_at"],
        }.items():
            _create_index("buyer_requirements", name, cols)

    if not _has_table(inspector, "assurance_rule_packs"):
        op.create_table(
            "assurance_rule_packs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("required_evidence_types", sa.JSON(), nullable=False),
            sa.Column("checklist", sa.JSON(), nullable=False),
            sa.Column("validation_rules", sa.JSON(), nullable=False),
            sa.Column("scoring_weights", sa.JSON(), nullable=False),
            sa.Column("disclaimer_text", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_assurance_rule_packs_scope": ["scope"],
            "ix_assurance_rule_packs_version": ["version"],
            "ix_assurance_rule_packs_status": ["status"],
            "ix_assurance_rule_packs_created_at": ["created_at"],
        }.items():
            _create_index("assurance_rule_packs", name, cols)

    if not _has_table(inspector, "assurance_exports"):
        op.create_table(
            "assurance_exports",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=False),
            sa.Column("export_type", sa.String(), nullable=False),
            sa.Column("storage_backend", sa.String(), nullable=False),
            sa.Column("storage_ref", sa.Text(), nullable=True),
            sa.Column("checksum", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_assurance_exports_tenant_id": ["tenant_id"],
            "ix_assurance_exports_passport_id": ["passport_id"],
            "ix_assurance_exports_export_type": ["export_type"],
            "ix_assurance_exports_storage_backend": ["storage_backend"],
            "ix_assurance_exports_checksum": ["checksum"],
            "ix_assurance_exports_created_at": ["created_at"],
            "ix_assurance_exports_passport_created": ["tenant_id", "passport_id", "created_at"],
        }.items():
            _create_index("assurance_exports", name, cols)

    if not _has_table(inspector, "workbench_sessions"):
        op.create_table(
            "workbench_sessions",
            sa.Column("session_id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("assurance_passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=True),
            sa.Column("workspace_name", sa.String(), nullable=False),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("is_sample_package", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_workbench_sessions_tenant_id": ["tenant_id"],
            "ix_workbench_sessions_assurance_passport_id": ["assurance_passport_id"],
            "ix_workbench_sessions_mode": ["mode"],
            "ix_workbench_sessions_status": ["status"],
            "ix_workbench_sessions_created_at": ["created_at"],
            "ix_workbench_sessions_updated_at": ["updated_at"],
        }.items():
            _create_index("workbench_sessions", name, cols)

    if not _has_table(inspector, "workbench_data_artifacts"):
        op.create_table(
            "workbench_data_artifacts",
            sa.Column("artifact_id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), sa.ForeignKey("workbench_sessions.session_id"), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("content_type", sa.String(), nullable=False),
            sa.Column("source_kind", sa.String(), nullable=False),
            sa.Column("rows_detected", sa.String(), nullable=False),
            sa.Column("columns_detected", sa.JSON(), nullable=False),
            sa.Column("parse_status", sa.String(), nullable=False),
            sa.Column("warnings", sa.JSON(), nullable=False),
            sa.Column("parsed_rows", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for name, cols in {
            "ix_workbench_data_artifacts_session_id": ["session_id"],
            "ix_workbench_data_artifacts_source_kind": ["source_kind"],
            "ix_workbench_data_artifacts_parse_status": ["parse_status"],
            "ix_workbench_data_artifacts_created_at": ["created_at"],
        }.items():
            _create_index("workbench_data_artifacts", name, cols)

    if not _has_table(inspector, "workbench_analyses"):
        op.create_table(
            "workbench_analyses",
            sa.Column("analysis_id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), sa.ForeignKey("workbench_sessions.session_id"), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        _create_index("workbench_analyses", "ix_workbench_analyses_session_id", ["session_id"])
        _create_index("workbench_analyses", "ix_workbench_analyses_created_at", ["created_at"])

    if not _has_table(inspector, "workbench_audit_events"):
        op.create_table(
            "workbench_audit_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), sa.ForeignKey("workbench_sessions.session_id"), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        _create_index("workbench_audit_events", "ix_workbench_audit_events_session_id", ["session_id"])
        _create_index("workbench_audit_events", "ix_workbench_audit_events_created_at", ["created_at"])

    if not _has_table(inspector, "workbench_evidence_actions"):
        op.create_table(
            "workbench_evidence_actions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), sa.ForeignKey("workbench_sessions.session_id"), nullable=False),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        _create_index("workbench_evidence_actions", "ix_workbench_evidence_actions_session_id", ["session_id"])
        _create_index("workbench_evidence_actions", "ix_workbench_evidence_actions_action_type", ["action_type"])
        _create_index("workbench_evidence_actions", "ix_workbench_evidence_actions_created_at", ["created_at"])
        _create_index("workbench_evidence_actions", "ix_workbench_evidence_session_action", ["session_id", "action_type"])


def downgrade():
    for table_name in [
        "workbench_evidence_actions",
        "workbench_audit_events",
        "workbench_analyses",
        "workbench_data_artifacts",
        "workbench_sessions",
        "assurance_exports",
        "assurance_rule_packs",
        "buyer_requirements",
        "traceability_events",
        "harvest_lots",
        "fertilizer_applications",
        "pesticide_applications",
        "input_applications",
        "assurance_risk_scores",
        "assurance_checklist_items",
        "assurance_evidence_artifacts",
        "assurance_passport_sections",
        "assurance_passports",
    ]:
        op.drop_table(table_name)

