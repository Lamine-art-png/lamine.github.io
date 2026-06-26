from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context, get_current_user
from app.core.security import create_access_token
from app.db.base import get_db
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.services.entitlements import serialize_entitlements
from app.services.evaluation_seed import ensure_evaluation_context

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    name: str | None = None
    organization_name: str = Field(min_length=2)
    workspace_name: str = "Evaluation workspace"
    crop: str | None = None
    region: str | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email required")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email required")
        return value


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "organization"


def _unique_slug(db: Session, name: str) -> str:
    base = _slugify(name)
    slug = base
    suffix = 2
    while db.query(Organization).filter(Organization.slug == slug).first():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _first_workspace(db: Session, org_id: str) -> Workspace | None:
    return (
        db.query(Workspace)
        .filter(Workspace.organization_id == org_id)
        .order_by(Workspace.created_at.asc())
        .first()
    )


def _session_response(user: User, org: Organization, membership: OrganizationMembership) -> dict:
    token = create_access_token({"sub": user.id, "tenant_id": org.id, "org_id": org.id, "role": membership.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "name": user.name, "is_active": user.is_active},
        "current_organization": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "plan": org.plan,
            "subscription_status": org.subscription_status,
            "role": membership.role,
        },
        "entitlements": serialize_entitlements(org),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with that email already exists")

    user = User(
        email=email,
        name=payload.name,
        password_hash=pwd_context.hash(payload.password),
    )
    db.add(user)
    db.flush()

    org = Organization(
        name=payload.organization_name,
        slug=_unique_slug(db, payload.organization_name),
        owner_user_id=user.id,
        plan="free",
        subscription_status="inactive",
    )
    db.add(org)
    db.flush()

    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(
        organization_id=org.id,
        name=payload.workspace_name,
        crop=payload.crop,
        region=payload.region,
        mode="evaluation",
    )
    db.add_all([membership, workspace])
    db.flush()
    ensure_evaluation_context(db, org, workspace)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registration could not be completed")
    db.refresh(user)
    db.refresh(org)
    db.refresh(membership)
    return _session_response(user, org, membership)


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not user.password_hash or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    user.last_login_at = datetime.utcnow()
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user.id)
        .order_by(OrganizationMembership.created_at.asc())
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no organization membership")

    ensure_evaluation_context(db, membership.organization, _first_workspace(db, membership.organization_id))
    db.commit()
    return _session_response(user, membership.organization, membership)


@router.post("/logout")
def logout(_: User = Depends(get_current_user)) -> dict:
    return {"ok": True}


@router.get("/me")
def me(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    if ctx.organization:
        ensure_evaluation_context(db, ctx.organization, _first_workspace(db, ctx.organization.id))
        db.commit()

    orgs = [
        {
            "id": membership.organization.id,
            "name": membership.organization.name,
            "slug": membership.organization.slug,
            "plan": membership.organization.plan,
            "subscription_status": membership.organization.subscription_status,
            "role": membership.role,
        }
        for membership in ctx.user.memberships
    ]
    current = orgs[0] if orgs else None
    return {
        "user": {"id": ctx.user.id, "email": ctx.user.email, "name": ctx.user.name, "is_active": ctx.user.is_active},
        "organizations": orgs,
        "current_organization": current,
        "role": current["role"] if current else None,
        "plan": current["plan"] if current else None,
        "subscription_status": current["subscription_status"] if current else None,
        "entitlements": serialize_entitlements(ctx.organization) if ctx.organization else None,
    }
