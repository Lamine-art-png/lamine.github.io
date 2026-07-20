"""Platform API product, commerce, and operations records.

These tables extend the shared Phase 1 Platform API control plane. They are
intentionally separate from the Enterprise Portal subscription lifecycle:
organizations may hold a Portal subscription, an API subscription, both, or a
contract-backed API enrollment.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


def new_product_id() -> str:
    return str(uuid.uuid4())


class PlatformApiApplication(Base):
    __tablename__ = "platform_api_applications"
    __table_args__ = (
        Index("ix_platform_application_org_status", "organization_id", "status", "created_at"),
        Index("ix_platform_application_type_status", "application_type", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    applicant_user_id = Column(String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    application_type = Column(String, nullable=False, index=True)
    status = Column(String, default="draft", nullable=False, index=True)
    organization_website = Column(Text, nullable=False)
    corporate_email = Column(String, nullable=False)
    company_description = Column(Text, nullable=False)
    intended_product = Column(Text, nullable=False)
    use_case = Column(Text, nullable=False)
    target_users = Column(Text, nullable=False)
    expected_api_operations_json = Column(JSON, nullable=False, default=list)
    expected_monthly_volume = Column(String, nullable=False)
    expected_data_volume = Column(String, nullable=False)
    requested_environment = Column(String, nullable=False)
    required_providers_json = Column(JSON, nullable=False, default=list)
    geography_json = Column(JSON, nullable=False, default=list)
    data_residency_needs = Column(Text, nullable=True)
    compliance_needs = Column(Text, nullable=True)
    security_contact = Column(String, nullable=False)
    technical_contact = Column(String, nullable=False)
    billing_contact = Column(String, nullable=True)
    target_integration_date = Column(DateTime, nullable=True)
    requested_support = Column(String, nullable=False)
    partner_documentation_status = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    terms_version = Column(String, nullable=False)
    privacy_version = Column(String, nullable=False)
    provider_company = Column(String, nullable=True)
    integration_category = Column(String, nullable=True)
    sandbox_availability = Column(String, nullable=True)
    authentication_type = Column(String, nullable=True)
    expected_resources_json = Column(JSON, nullable=False, default=list)
    webhook_needs = Column(Text, nullable=True)
    read_capabilities_json = Column(JSON, nullable=False, default=list)
    potential_write_capabilities_json = Column(JSON, nullable=False, default=list)
    nda_status = Column(String, nullable=True)
    contract_status = Column(String, nullable=True)
    technical_owner = Column(String, nullable=True)
    commercial_owner = Column(String, nullable=True)
    implementation_stage = Column(String, nullable=True)
    readiness_blockers_json = Column(JSON, nullable=False, default=list)
    document_references_json = Column(JSON, nullable=False, default=list)
    assigned_reviewer_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    decision_reason = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=True, index=True)
    decided_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformProgramEnrollment(Base):
    __tablename__ = "platform_program_enrollments"
    __table_args__ = (
        UniqueConstraint("organization_id", "program", name="uq_platform_enrollment_org_program"),
        Index("ix_platform_enrollment_org_status", "organization_id", "status"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(String, ForeignKey("platform_api_applications.id", ondelete="SET NULL"), nullable=True, index=True)
    program = Column(String, nullable=False, index=True)
    status = Column(String, default="pending", nullable=False, index=True)
    approved_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    suspension_reason = Column(Text, nullable=True)
    allowed_environments_json = Column(JSON, nullable=False, default=list)
    maximum_projects = Column(Integer, nullable=False, default=0)
    maximum_live_projects = Column(Integer, nullable=False, default=0)
    maximum_service_accounts = Column(Integer, nullable=False, default=0)
    maximum_keys = Column(Integer, nullable=False, default=0)
    maximum_webhooks = Column(Integer, nullable=False, default=0)
    provider_restrictions_json = Column(JSON, nullable=False, default=dict)
    resource_restrictions_json = Column(JSON, nullable=False, default=dict)
    default_scopes_json = Column(JSON, nullable=False, default=list)
    rate_limit_policy_json = Column(JSON, nullable=False, default=dict)
    quota_policy_json = Column(JSON, nullable=False, default=dict)
    billing_mode = Column(String, default="none", nullable=False, index=True)
    plan_identifier = Column(String, nullable=True, index=True)
    contract_reference = Column(String, nullable=True)
    support_tier = Column(String, default="documentation", nullable=False)
    data_retention_policy_json = Column(JSON, nullable=False, default=dict)
    effective_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformLiveAccessRequest(Base):
    __tablename__ = "platform_live_access_requests"
    __table_args__ = (
        Index("ix_platform_live_access_org_status", "organization_id", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_user_id = Column(String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String, default="not_requested", nullable=False, index=True)
    intended_production_use = Column(Text, nullable=False)
    expected_users = Column(String, nullable=False)
    expected_volume = Column(String, nullable=False)
    expected_peak_rate = Column(String, nullable=False)
    data_categories_json = Column(JSON, nullable=False, default=list)
    provider_dependencies_json = Column(JSON, nullable=False, default=list)
    geographic_regions_json = Column(JSON, nullable=False, default=list)
    security_contact = Column(String, nullable=False)
    incident_contact = Column(String, nullable=False)
    compliance_needs = Column(Text, nullable=True)
    cidr_strategy = Column(Text, nullable=False)
    webhook_use = Column(Text, nullable=True)
    data_retention = Column(String, nullable=False)
    billing_plan = Column(String, nullable=False)
    target_launch_date = Column(DateTime, nullable=True)
    assigned_reviewer_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision_reason = Column(Text, nullable=True)
    conditions_json = Column(JSON, nullable=False, default=list)
    submitted_at = Column(DateTime, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformPartnerDossier(Base):
    __tablename__ = "platform_partner_dossiers"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_id", name="uq_platform_partner_org_provider"),
        Index("ix_platform_partner_readiness", "provider_id", "production_readiness"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    enrollment_id = Column(String, ForeignKey("platform_program_enrollments.id", ondelete="SET NULL"), nullable=True)
    application_id = Column(String, ForeignKey("platform_api_applications.id", ondelete="SET NULL"), nullable=True)
    partner_name = Column(String, nullable=False)
    provider_id = Column(String, nullable=False, index=True)
    integration_owner_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    commercial_owner = Column(String, nullable=True)
    technical_owner = Column(String, nullable=True)
    nda_status = Column(String, default="not_started", nullable=False)
    contract_status = Column(String, default="awaiting_partner_contract", nullable=False, index=True)
    documentation_received = Column(Boolean, default=False, nullable=False)
    authentication_confirmed = Column(Boolean, default=False, nullable=False)
    sandbox_credentials_received = Column(Boolean, default=False, nullable=False)
    endpoint_allowlist_approved = Column(Boolean, default=False, nullable=False)
    schemas_received = Column(Boolean, default=False, nullable=False)
    rate_limits_received = Column(Boolean, default=False, nullable=False)
    webhook_contract_received = Column(Boolean, default=False, nullable=False)
    data_retention_terms = Column(Text, nullable=True)
    support_contacts_json = Column(JSON, nullable=False, default=list)
    milestones_json = Column(JSON, nullable=False, default=list)
    read_readiness = Column(String, default="awaiting_partner_contract", nullable=False)
    write_readiness = Column(String, default="disabled", nullable=False)
    sandbox_readiness = Column(String, default="awaiting_partner_contract", nullable=False)
    production_readiness = Column(String, default="awaiting_partner_contract", nullable=False)
    blockers_json = Column(JSON, nullable=False, default=list)
    custom_rate_card_json = Column(JSON, nullable=False, default=dict)
    custom_limits_json = Column(JSON, nullable=False, default=dict)
    document_references_json = Column(JSON, nullable=False, default=list)
    credential_vault_references_json = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformProductAuditEvent(Base):
    __tablename__ = "platform_product_audit_events"
    __table_args__ = (
        Index("ix_platform_product_audit_org_time", "organization_id", "created_at"),
        Index("ix_platform_product_audit_subject", "subject_type", "subject_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_type = Column(String, nullable=False)
    event_type = Column(String, nullable=False, index=True)
    subject_type = Column(String, nullable=False)
    subject_id = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    request_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class PlatformTermsDocument(Base):
    __tablename__ = "platform_terms_documents"
    __table_args__ = (
        UniqueConstraint("document_type", "version", name="uq_platform_terms_type_version"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    document_type = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False)
    status = Column(String, default="draft_legal_review_required", nullable=False, index=True)
    content_digest = Column(String(64), nullable=False)
    effective_at = Column(DateTime, nullable=True)
    reacceptance_required = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformTermsAcceptance(Base):
    __tablename__ = "platform_terms_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            "document_type",
            "document_version",
            name="uq_platform_terms_acceptance",
        ),
        Index("ix_platform_terms_acceptance_org", "organization_id", "accepted_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(
        String,
        ForeignKey("platform_terms_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_type = Column(String, nullable=False)
    document_version = Column(String, nullable=False)
    ip_hash = Column(String(64), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    accepted_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformApiPlan(Base):
    __tablename__ = "platform_api_plans"
    __table_args__ = (
        UniqueConstraint("catalog_version", "plan_identifier", name="uq_platform_api_plan_version"),
        Index("ix_platform_api_plan_active", "active", "catalog_version"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    catalog_version = Column(String, nullable=False, index=True)
    plan_identifier = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    status = Column(String, default="provisional", nullable=False)
    active = Column(Boolean, default=False, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    monthly_price_cents = Column(Integer, nullable=True)
    annual_price_cents = Column(Integer, nullable=True)
    included_credits = Column(Integer, nullable=True)
    overage_price_per_1000_cents = Column(Integer, nullable=True)
    overages_allowed = Column(Boolean, default=False, nullable=False)
    limits_json = Column(JSON, nullable=False, default=dict)
    support_tier = Column(String, nullable=False)
    stripe_product_config_key = Column(String, nullable=True)
    stripe_monthly_price_config_key = Column(String, nullable=True)
    stripe_annual_price_config_key = Column(String, nullable=True)
    stripe_overage_price_config_key = Column(String, nullable=True)
    effective_at = Column(DateTime, nullable=True)
    retired_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformApiOperationCost(Base):
    __tablename__ = "platform_api_operation_costs"
    __table_args__ = (
        UniqueConstraint("catalog_version", "operation_id", "environment", name="uq_platform_cost_version_operation_env"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    catalog_version = Column(String, nullable=False, index=True)
    operation_id = Column(String, nullable=False, index=True)
    operation_class = Column(String, nullable=False, index=True)
    environment = Column(String, nullable=False)
    credits = Column(Integer, nullable=False)
    active = Column(Boolean, default=False, nullable=False)
    description = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformApiSubscription(Base):
    __tablename__ = "platform_api_subscriptions"
    __table_args__ = (
        UniqueConstraint("organization_id", "status_slot", name="uq_platform_api_subscription_active_slot"),
        Index("ix_platform_api_subscription_stripe", "stripe_subscription_id"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    enrollment_id = Column(String, ForeignKey("platform_program_enrollments.id", ondelete="SET NULL"), nullable=True)
    plan_id = Column(String, ForeignKey("platform_api_plans.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String, default="free", nullable=False, index=True)
    status_slot = Column(String, default="active", nullable=False)
    billing_mode = Column(String, default="none", nullable=False)
    billing_interval = Column(String, nullable=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, unique=True)
    stripe_price_id = Column(String, nullable=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    grace_ends_at = Column(DateTime, nullable=True)
    stripe_state_updated_at = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    contract_reference = Column(String, nullable=True)
    entitlement_policy_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformCheckoutIdempotency(Base):
    __tablename__ = "platform_checkout_idempotency"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "operation",
            "client_key",
            name="uq_platform_checkout_idempotency_scope",
        ),
        Index("ix_platform_checkout_idempotency_expires", "expires_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(
        String,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation = Column(String, nullable=False)
    client_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String, default="in_progress", nullable=False, index=True)
    subscription_id = Column(
        String,
        ForeignKey("platform_api_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    stripe_checkout_session_id = Column(String, nullable=True)
    response_json = Column(JSON, nullable=True)
    first_request_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)


class PlatformCreditReservation(Base):
    __tablename__ = "platform_credit_reservations"
    __table_args__ = (
        UniqueConstraint("organization_id", "api_project_id", "logical_operation_id", name="uq_platform_credit_logical_operation"),
        Index("ix_platform_credit_period_state", "organization_id", "billing_period_key", "state"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key_id = Column(String, ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True)
    operation_id = Column(String, nullable=False, index=True)
    logical_operation_id = Column(String, nullable=False)
    billing_period_key = Column(String, nullable=False)
    reserved_credits = Column(Integer, nullable=False)
    committed_credits = Column(Integer, nullable=True)
    state = Column(String, default="reserved", nullable=False, index=True)
    overage_credits = Column(Integer, default=0, nullable=False)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    committed_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)


class PlatformStripeMeterOutbox(Base):
    __tablename__ = "platform_stripe_meter_outbox"
    __table_args__ = (
        UniqueConstraint("usage_event_id", name="uq_platform_meter_usage_event"),
        UniqueConstraint("meter_event_identifier", name="uq_platform_meter_event_identifier"),
        Index("ix_platform_meter_outbox_ready", "status", "next_attempt_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(String, ForeignKey("platform_api_subscriptions.id", ondelete="CASCADE"), nullable=False)
    usage_event_id = Column(String, ForeignKey("platform_api_usage_events.id", ondelete="CASCADE"), nullable=False)
    meter_event_identifier = Column(String, nullable=False)
    meter_event_name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String, default="pending", nullable=False, index=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    next_attempt_at = Column(DateTime, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    exported_at = Column(DateTime, nullable=True)
    reconciled_at = Column(DateTime, nullable=True)
    last_error_class = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformStripeEvent(Base):
    __tablename__ = "platform_stripe_events"
    __table_args__ = (
        UniqueConstraint("stripe_event_id", name="uq_platform_stripe_event"),
        Index("ix_platform_stripe_event_processing", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    stripe_event_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    subscription_id = Column(String, ForeignKey("platform_api_subscriptions.id", ondelete="SET NULL"), nullable=True)
    status = Column(String, default="received", nullable=False)
    event_created_at = Column(DateTime, nullable=False)
    payload_digest = Column(String(64), nullable=False)
    safe_metadata_json = Column(JSON, nullable=False, default=dict)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformRequestLog(Base):
    __tablename__ = "platform_request_logs"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_id", name="uq_platform_request_log_org_request"),
        Index("ix_platform_request_log_project_time", "api_project_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id = Column(String, nullable=False)
    client_correlation_id = Column(String(96), nullable=True, index=True)
    method = Column(String, nullable=False)
    operation_id = Column(String, nullable=False, index=True)
    status_code = Column(Integer, nullable=False)
    latency_ms = Column(Integer, nullable=False)
    environment = Column(String, nullable=False)
    key_fingerprint = Column(String(32), nullable=True)
    usage_cost = Column(Integer, nullable=False, default=0)
    safe_error_code = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class PlatformNotification(Base):
    __tablename__ = "platform_notifications"
    __table_args__ = (
        UniqueConstraint("organization_id", "notification_type", "dedupe_key", name="uq_platform_notification_dedupe"),
        Index("ix_platform_notification_delivery", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notification_type = Column(String, nullable=False)
    dedupe_key = Column(String, nullable=False)
    locale = Column(String, default="en", nullable=False)
    status = Column(String, default="pending", nullable=False)
    safe_context_json = Column(JSON, nullable=False, default=dict)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformSandboxState(Base):
    __tablename__ = "platform_sandbox_states"
    __table_args__ = (
        UniqueConstraint("api_project_id", name="uq_platform_sandbox_project"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False)
    fixture_version = Column(String, nullable=False)
    reset_counter = Column(Integer, default=0, nullable=False)
    seed = Column(String, nullable=False)
    last_reset_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_reset_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformSupportRequest(Base):
    __tablename__ = "platform_support_requests"
    __table_args__ = (
        Index("ix_platform_support_org_status", "organization_id", "status", "created_at"),
        Index("ix_platform_support_queue", "severity", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    assigned_to_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    category = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, index=True)
    subject = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    environment = Column(String, nullable=True)
    request_id_reference = Column(String, nullable=True)
    key_fingerprint = Column(String(32), nullable=True)
    job_id = Column(String, nullable=True)
    webhook_delivery_id = Column(String, nullable=True)
    invoice_reference = Column(String, nullable=True)
    contact_email = Column(String, nullable=False)
    attachment_references_json = Column(JSON, nullable=False, default=list)
    status = Column(String, default="open", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformSupportMessage(Base):
    __tablename__ = "platform_support_messages"
    __table_args__ = (
        Index("ix_platform_support_message_request", "support_request_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    support_request_id = Column(String, ForeignKey("platform_support_requests.id", ondelete="CASCADE"), nullable=False)
    author_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    visibility = Column(String, default="customer", nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformStatusComponent(Base):
    __tablename__ = "platform_status_components"

    id = Column(String, primary_key=True, default=new_product_id)
    component_key = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    status = Column(String, default="operational", nullable=False)
    public = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformStatusIncident(Base):
    __tablename__ = "platform_status_incidents"
    __table_args__ = (
        Index("ix_platform_status_incident_state", "status", "started_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    title = Column(String, nullable=False)
    status = Column(String, default="investigating", nullable=False)
    severity = Column(String, nullable=False)
    public_summary = Column(Text, nullable=False)
    component_keys_json = Column(JSON, nullable=False, default=list)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformStatusIncidentUpdate(Base):
    __tablename__ = "platform_status_incident_updates"
    __table_args__ = (
        Index("ix_platform_status_update_incident", "incident_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    incident_id = Column(String, ForeignKey("platform_status_incidents.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)
    public_message = Column(Text, nullable=False)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformAbuseEvent(Base):
    __tablename__ = "platform_abuse_events"
    __table_args__ = (
        Index("ix_platform_abuse_org_state", "organization_id", "status", "created_at"),
        Index("ix_platform_abuse_signal", "signal_type", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_product_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="SET NULL"), nullable=True)
    api_key_id = Column(String, ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True)
    signal_type = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    status = Column(String, default="open", nullable=False)
    automated_action = Column(String, nullable=True)
    evidence_summary_json = Column(JSON, nullable=False, default=dict)
    reviewed_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
