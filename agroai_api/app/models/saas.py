"""SaaS foundation models for users, organizations, workspaces, billing, and usage."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_id, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=True)
    password_hash = Column(String, nullable=True)
    auth_provider = Column(String, nullable=True)
    auth_provider_subject = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified_at = Column(DateTime, nullable=True)
    email_verification_status = Column(String, default="unverified", nullable=False, index=True)
    credentials_changed_at = Column(DateTime, nullable=True)
    account_status = Column(String, default="active", nullable=False, index=True)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    failed_login_window_started_at = Column(DateTime, nullable=True)
    locked_until = Column(DateTime, nullable=True, index=True)

    owned_organizations = relationship("Organization", back_populates="owner")
    memberships = relationship("OrganizationMembership", back_populates="user", cascade="all, delete-orphan")
    usage_events = relationship("UsageEvent", back_populates="user")
    email_verification_tokens = relationship("EmailVerificationToken", back_populates="user", cascade="all, delete-orphan")
    account_recovery_tokens = relationship("AccountRecoveryToken", back_populates="user", cascade="all, delete-orphan")
    team_invitations_sent = relationship("TeamInvitation", back_populates="invited_by_user", cascade="all, delete-orphan")
    security_events = relationship("SecurityAuditEvent", back_populates="user")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=new_id, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    plan = Column(String, default="free", nullable=False)
    plan_version = Column(String, default="2026-07", nullable=False, index=True)
    customer_class = Column(String, default="individual_operator", nullable=False, index=True)
    organization_type = Column(String, nullable=True, index=True)
    commercial_metadata_json = Column(JSON, nullable=True)
    subscription_status = Column(String, default="inactive", nullable=False)
    verification_status = Column(String, default="approved_legacy", nullable=False, index=True)
    verification_score = Column(Integer, nullable=True)
    verification_reason_codes_json = Column(JSON, nullable=True)
    verification_engine_version = Column(String, nullable=True)
    verification_submitted_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    subscription_source = Column(String, default="local", nullable=False, index=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)
    stripe_product_id = Column(String, nullable=True, index=True)
    stripe_price_id = Column(String, nullable=True, index=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="owned_organizations", foreign_keys=[owner_user_id])
    memberships = relationship("OrganizationMembership", back_populates="organization", cascade="all, delete-orphan")
    workspaces = relationship("Workspace", back_populates="organization", cascade="all, delete-orphan")
    billing_events = relationship("BillingEvent", back_populates="organization")
    usage_events = relationship("UsageEvent", back_populates="organization")
    verification_profile = relationship("OrganizationVerificationProfile", back_populates="organization", uselist=False, cascade="all, delete-orphan")
    security_events = relationship("SecurityAuditEvent", back_populates="organization")


class OrganizationVerificationProfile(Base):
    __tablename__ = "organization_verification_profiles"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    professional_role = Column(String, nullable=False)
    organization_type = Column(String, nullable=False, index=True)
    website_url = Column(String, nullable=True)
    professional_profile_url = Column(String, nullable=True)
    country = Column(String, nullable=False, index=True)
    operating_region = Column(String, nullable=False)
    acres_or_sites = Column(String, nullable=False)
    primary_crops = Column(String, nullable=False)
    intended_use = Column(Text, nullable=False)
    planned_data_sources = Column(Text, nullable=False)
    email_domain = Column(String, nullable=False, index=True)
    domain_classification = Column(String, nullable=False, index=True)
    phone_algorithm = Column(String, nullable=False)
    phone_key_version = Column(String, nullable=False)
    phone_nonce_b64 = Column(Text, nullable=False)
    phone_ciphertext_b64 = Column(Text, nullable=False)
    phone_last4 = Column(String(4), nullable=False)
    decision = Column(String, nullable=False, index=True)
    score = Column(Integer, nullable=False)
    reason_codes_json = Column(JSON, nullable=True)
    engine_version = Column(String, nullable=False)
    evidence_digest = Column(String(64), nullable=False, index=True)
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    decided_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="verification_profile")


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_events"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    outcome = Column(String, nullable=False, index=True)
    subject_hash = Column(String(64), nullable=True, index=True)
    ip_hash = Column(String(64), nullable=True, index=True)
    user_agent_hash = Column(String(64), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    organization = relationship("Organization", back_populates="security_events")
    user = relationship("User", back_populates="security_events")


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_membership_user"),)

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, default="operator", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="memberships")
    user = relationship("User", back_populates="memberships")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    crop = Column(String, nullable=True)
    region = Column(String, nullable=True)
    mode = Column(String, default="evaluation", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="workspaces")
    usage_events = relationship("UsageEvent", back_populates="workspace")


class BillingEvent(Base):
    __tablename__ = "billing_events"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    stripe_event_id = Column(String, nullable=False, unique=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="billing_events")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    metric = Column(String, nullable=True, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    unit = Column(String, default="count", nullable=False)
    period_key = Column(String, nullable=True, index=True)
    request_id = Column(String, nullable=True, index=True)
    reservation_id = Column(String, nullable=True, index=True)
    state = Column(String, default="committed", nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    organization = relationship("Organization", back_populates="usage_events")
    workspace = relationship("Workspace", back_populates="usage_events")
    user = relationship("User", back_populates="usage_events")


class EntitlementOverride(Base):
    __tablename__ = "entitlement_overrides"
    __table_args__ = (UniqueConstraint("organization_id", "feature_key", "valid_from", name="uq_entitlement_override_window"),)

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_key = Column(String, nullable=False, index=True)
    value_json = Column(JSON, nullable=False)
    reason = Column(String, nullable=True)
    source = Column(String, default="manual", nullable=False, index=True)
    valid_from = Column(DateTime, nullable=True, index=True)
    valid_until = Column(DateTime, nullable=True, index=True)
    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class CommercialContract(Base):
    __tablename__ = "commercial_contracts"
    __table_args__ = (UniqueConstraint("organization_id", "contract_code", name="uq_contract_org_code"),)

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_code = Column(String, nullable=False, index=True)
    status = Column(String, default="draft", nullable=False, index=True)
    effective_from = Column(DateTime, nullable=True, index=True)
    effective_to = Column(DateTime, nullable=True, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ManagedEntity(Base):
    __tablename__ = "managed_entities"
    __table_args__ = (UniqueConstraint("organization_id", "entity_type", "external_id", name="uq_managed_entity_external"),)

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    entity_type = Column(String, nullable=False, index=True)
    external_id = Column(String, nullable=True, index=True)
    display_name = Column(String, nullable=False)
    status = Column(String, default="active", nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class QuotaReservation(Base):
    __tablename__ = "quota_reservations"
    __table_args__ = (UniqueConstraint("organization_id", "metric", "request_id", name="uq_quota_reservation_request"),)

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    metric = Column(String, nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    unit = Column(String, default="count", nullable=False)
    period_key = Column(String, nullable=False, index=True)
    request_id = Column(String, nullable=False, index=True)
    state = Column(String, default="reserved", nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    committed_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)


class SaaSRequest(Base):
    __tablename__ = "saas_requests"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    type = Column(String, nullable=False, index=True)
    status = Column(String, default="received", nullable=False, index=True)
    priority = Column(String, default="medium", nullable=False, index=True)
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    company = Column(String, nullable=True)
    role = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    message = Column(String, nullable=False)
    source_page = Column(String, nullable=True)
    notification_status = Column(String, default="stored", nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    status = Column(String, default="open", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(String, primary_key=True, default=new_id, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    role = Column(String, nullable=False, index=True)
    content = Column(String, nullable=False)
    artifacts_json = Column(JSON, nullable=True)
    citations_json = Column(JSON, nullable=True)
    missing_data_json = Column(JSON, nullable=True)
    recommended_actions_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    conversation = relationship("Conversation", back_populates="messages")


class OnboardingState(Base):
    __tablename__ = "onboarding_states"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_onboarding_org_user"),)

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    current_step = Column(String, default="account", nullable=False)
    selected_plan = Column(String, nullable=True)
    organization_type = Column(String, nullable=True)
    acres_or_sites = Column(String, nullable=True)
    primary_goal = Column(String, nullable=True)
    completed_steps_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(String, primary_key=True, default=new_id, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = relationship("User", back_populates="email_verification_tokens")


class AccountRecoveryToken(Base):
    __tablename__ = "account_recovery_tokens"

    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = relationship("User", back_populates="account_recovery_tokens")


class TeamInvitation(Base):
    __tablename__ = "team_invitations"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    role = Column(String, default="viewer", nullable=False)
    status = Column(String, default="pending", nullable=False, index=True)
    invited_by_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=True, unique=True, index=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    invited_by_user = relationship("User", back_populates="team_invitations_sent")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    locale = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    notifications_json = Column(Text, nullable=True)
    ui_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
