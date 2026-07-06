"""SaaS foundation models for users, organizations, workspaces, billing, and usage."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
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

    owned_organizations = relationship("Organization", back_populates="owner")
    memberships = relationship("OrganizationMembership", back_populates="user", cascade="all, delete-orphan")
    usage_events = relationship("UsageEvent", back_populates="user")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=new_id, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    plan = Column(String, default="free", nullable=False)
    plan_version = Column(String, default="2026-07", nullable=False)
    customer_class = Column(String, default="individual_operator", nullable=False, index=True)
    organization_type = Column(String, nullable=True, index=True)
    operating_scale = Column(JSON, nullable=True)
    commercial_metadata_json = Column(JSON, nullable=True)
    subscription_status = Column(String, default="inactive", nullable=False)
    billing_period = Column(String, nullable=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)
    stripe_product_id = Column(String, nullable=True)
    stripe_price_id = Column(String, nullable=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    subscription_source = Column(String, default="self_serve", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="owned_organizations", foreign_keys=[owner_user_id])
    memberships = relationship("OrganizationMembership", back_populates="organization", cascade="all, delete-orphan")
    workspaces = relationship("Workspace", back_populates="organization", cascade="all, delete-orphan")
    billing_events = relationship("BillingEvent", back_populates="organization")
    usage_events = relationship("UsageEvent", back_populates="organization")
    entitlement_overrides = relationship("EntitlementOverride", back_populates="organization", cascade="all, delete-orphan")
    commercial_contracts = relationship("CommercialContract", back_populates="organization", cascade="all, delete-orphan")
    managed_entities = relationship("ManagedEntity", back_populates="organization", cascade="all, delete-orphan")


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

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    feature_key = Column(String, nullable=False, index=True)
    value_json = Column(JSON, nullable=False)
    reason = Column(String, nullable=True)
    source = Column(String, default="admin", nullable=False)
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="entitlement_overrides")


class CommercialContract(Base):
    __tablename__ = "commercial_contracts"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    contract_code = Column(String, nullable=False, index=True)
    status = Column(String, default="draft", nullable=False, index=True)
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="commercial_contracts")


class ManagedEntity(Base):
    __tablename__ = "managed_entities"
    __table_args__ = (UniqueConstraint("organization_id", "entity_type", "external_id", name="uq_managed_entity_external"),)

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    entity_type = Column(String, nullable=False, index=True)
    external_id = Column(String, nullable=True)
    display_name = Column(String, nullable=False)
    status = Column(String, default="active", nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="managed_entities")
