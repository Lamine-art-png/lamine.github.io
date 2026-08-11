"""Add Platform API applications, programs, partner review, and legal acceptance.

Revision ID: 024_platform_api_programs
Revises: 023_field_intelligence
Create Date: 2026-07-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "024_platform_api_programs"
down_revision = "023_field_intelligence"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(), primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "organization_memberships",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )
    op.create_index("ix_organization_memberships_status", "organization_memberships", ["status"])
    op.create_table(
        "platform_api_applications",
        _id(),
        sa.Column("applicant_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("organization_website", sa.Text(), nullable=False),
        sa.Column("corporate_email", sa.String(), nullable=False),
        sa.Column("company_description", sa.Text(), nullable=False),
        sa.Column("intended_product", sa.Text(), nullable=False),
        sa.Column("use_case", sa.Text(), nullable=False),
        sa.Column("target_users", sa.Text(), nullable=False),
        sa.Column("expected_api_operations_json", sa.JSON(), nullable=False),
        sa.Column("expected_monthly_volume", sa.String(), nullable=False),
        sa.Column("expected_data_volume", sa.String(), nullable=False),
        sa.Column("requested_environment", sa.String(), nullable=False),
        sa.Column("required_providers_json", sa.JSON(), nullable=False),
        sa.Column("geography_json", sa.JSON(), nullable=False),
        sa.Column("data_residency_needs", sa.Text(), nullable=True),
        sa.Column("compliance_needs", sa.Text(), nullable=True),
        sa.Column("security_contact", sa.String(), nullable=False),
        sa.Column("technical_contact", sa.String(), nullable=False),
        sa.Column("billing_contact", sa.String(), nullable=True),
        sa.Column("target_integration_date", sa.DateTime(), nullable=True),
        sa.Column("requested_support", sa.String(), nullable=False),
        sa.Column("partner_documentation_status", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("terms_version", sa.String(), nullable=False),
        sa.Column("privacy_version", sa.String(), nullable=False),
        sa.Column("provider_company", sa.String(), nullable=True),
        sa.Column("integration_category", sa.String(), nullable=True),
        sa.Column("sandbox_availability", sa.String(), nullable=True),
        sa.Column("authentication_type", sa.String(), nullable=True),
        sa.Column("expected_resources_json", sa.JSON(), nullable=False),
        sa.Column("webhook_needs", sa.Text(), nullable=True),
        sa.Column("read_capabilities_json", sa.JSON(), nullable=False),
        sa.Column("potential_write_capabilities_json", sa.JSON(), nullable=False),
        sa.Column("nda_status", sa.String(), nullable=True),
        sa.Column("contract_status", sa.String(), nullable=True),
        sa.Column("technical_owner", sa.String(), nullable=True),
        sa.Column("commercial_owner", sa.String(), nullable=True),
        sa.Column("implementation_stage", sa.String(), nullable=True),
        sa.Column("readiness_blockers_json", sa.JSON(), nullable=False),
        sa.Column("document_references_json", sa.JSON(), nullable=False),
        sa.Column("assigned_reviewer_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_platform_application_org_status", "platform_api_applications", ["organization_id", "status", "created_at"])
    op.create_index("ix_platform_application_type_status", "platform_api_applications", ["application_type", "status", "created_at"])
    op.create_index("ix_platform_application_applicant", "platform_api_applications", ["applicant_user_id"])

    op.create_table(
        "platform_program_enrollments",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.String(), sa.ForeignKey("platform_api_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("program", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
        sa.Column("suspension_reason", sa.Text(), nullable=True),
        sa.Column("allowed_environments_json", sa.JSON(), nullable=False),
        sa.Column("maximum_projects", sa.Integer(), nullable=False),
        sa.Column("maximum_live_projects", sa.Integer(), nullable=False),
        sa.Column("maximum_service_accounts", sa.Integer(), nullable=False),
        sa.Column("maximum_keys", sa.Integer(), nullable=False),
        sa.Column("maximum_webhooks", sa.Integer(), nullable=False),
        sa.Column("provider_restrictions_json", sa.JSON(), nullable=False),
        sa.Column("resource_restrictions_json", sa.JSON(), nullable=False),
        sa.Column("default_scopes_json", sa.JSON(), nullable=False),
        sa.Column("rate_limit_policy_json", sa.JSON(), nullable=False),
        sa.Column("quota_policy_json", sa.JSON(), nullable=False),
        sa.Column("billing_mode", sa.String(), nullable=False),
        sa.Column("plan_identifier", sa.String(), nullable=True),
        sa.Column("contract_reference", sa.String(), nullable=True),
        sa.Column("support_tier", sa.String(), nullable=False),
        sa.Column("data_retention_policy_json", sa.JSON(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "program", name="uq_platform_enrollment_org_program"),
    )
    op.create_index("ix_platform_enrollment_org_status", "platform_program_enrollments", ["organization_id", "status"])

    op.create_table(
        "platform_live_access_requests",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("intended_production_use", sa.Text(), nullable=False),
        sa.Column("expected_users", sa.String(), nullable=False),
        sa.Column("expected_volume", sa.String(), nullable=False),
        sa.Column("expected_peak_rate", sa.String(), nullable=False),
        sa.Column("data_categories_json", sa.JSON(), nullable=False),
        sa.Column("provider_dependencies_json", sa.JSON(), nullable=False),
        sa.Column("geographic_regions_json", sa.JSON(), nullable=False),
        sa.Column("security_contact", sa.String(), nullable=False),
        sa.Column("incident_contact", sa.String(), nullable=False),
        sa.Column("compliance_needs", sa.Text(), nullable=True),
        sa.Column("cidr_strategy", sa.Text(), nullable=False),
        sa.Column("webhook_use", sa.Text(), nullable=True),
        sa.Column("data_retention", sa.String(), nullable=False),
        sa.Column("billing_plan", sa.String(), nullable=False),
        sa.Column("target_launch_date", sa.DateTime(), nullable=True),
        sa.Column("assigned_reviewer_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("conditions_json", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_platform_live_access_org_status", "platform_live_access_requests", ["organization_id", "status", "created_at"])

    op.create_table(
        "platform_partner_dossiers",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enrollment_id", sa.String(), sa.ForeignKey("platform_program_enrollments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("application_id", sa.String(), sa.ForeignKey("platform_api_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("partner_name", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("integration_owner_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("commercial_owner", sa.String(), nullable=True),
        sa.Column("technical_owner", sa.String(), nullable=True),
        sa.Column("nda_status", sa.String(), nullable=False),
        sa.Column("contract_status", sa.String(), nullable=False),
        sa.Column("documentation_received", sa.Boolean(), nullable=False),
        sa.Column("authentication_confirmed", sa.Boolean(), nullable=False),
        sa.Column("sandbox_credentials_received", sa.Boolean(), nullable=False),
        sa.Column("endpoint_allowlist_approved", sa.Boolean(), nullable=False),
        sa.Column("schemas_received", sa.Boolean(), nullable=False),
        sa.Column("rate_limits_received", sa.Boolean(), nullable=False),
        sa.Column("webhook_contract_received", sa.Boolean(), nullable=False),
        sa.Column("data_retention_terms", sa.Text(), nullable=True),
        sa.Column("support_contacts_json", sa.JSON(), nullable=False),
        sa.Column("milestones_json", sa.JSON(), nullable=False),
        sa.Column("read_readiness", sa.String(), nullable=False),
        sa.Column("write_readiness", sa.String(), nullable=False),
        sa.Column("sandbox_readiness", sa.String(), nullable=False),
        sa.Column("production_readiness", sa.String(), nullable=False),
        sa.Column("blockers_json", sa.JSON(), nullable=False),
        sa.Column("custom_rate_card_json", sa.JSON(), nullable=False),
        sa.Column("custom_limits_json", sa.JSON(), nullable=False),
        sa.Column("document_references_json", sa.JSON(), nullable=False),
        sa.Column("credential_vault_references_json", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "provider_id", name="uq_platform_partner_org_provider"),
    )
    op.create_index("ix_platform_partner_readiness", "platform_partner_dossiers", ["provider_id", "production_readiness"])

    op.create_table(
        "platform_product_audit_events",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_platform_product_audit_org_time", "platform_product_audit_events", ["organization_id", "created_at"])
    op.create_index("ix_platform_product_audit_subject", "platform_product_audit_events", ["subject_type", "subject_id", "created_at"])

    op.create_table(
        "platform_terms_documents",
        _id(),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("reacceptance_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_type", "version", name="uq_platform_terms_type_version"),
    )

    op.create_table(
        "platform_terms_acceptances",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("platform_terms_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("document_version", sa.String(), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", "document_type", "document_version", name="uq_platform_terms_acceptance"),
    )
    op.create_index("ix_platform_terms_acceptance_org", "platform_terms_acceptances", ["organization_id", "accepted_at"])


def downgrade() -> None:
    for table in (
        "platform_terms_acceptances",
        "platform_terms_documents",
        "platform_product_audit_events",
        "platform_partner_dossiers",
        "platform_live_access_requests",
        "platform_program_enrollments",
        "platform_api_applications",
    ):
        op.drop_table(table)
    op.drop_index("ix_organization_memberships_status", table_name="organization_memberships")
    op.drop_column("organization_memberships", "status")
