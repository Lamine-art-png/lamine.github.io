"""Founder-only customer and account observability endpoints.

This surface is intentionally separate from organization administration. A
customer may own their organization, but only a verified identity explicitly
listed in PLATFORM_ADMIN_EMAILS may enumerate platform accounts.
"""
from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform_admin
from app.db.base import get_db
from app.models.saas import Organization, OrganizationMembership, UsageEvent, User, Workspace


router = APIRouter(prefix="/platform-admin", tags=["platform-admin"])
logger = logging.getLogger(__name__)

VerificationFilter = Literal["all", "verified", "unverified"]
ActiveFilter = Literal["all", "active", "inactive"]
SortOrder = Literal["newest", "oldest", "recent_login"]
ACTIVE_PAID_STATES = {"active", "trialing", "contracted"}


def _filtered_users(
    db: Session,
    *,
    search: str | None,
    verification: VerificationFilter,
    active: ActiveFilter,
    plan: str | None,
):
    query = db.query(User)
    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        query = query.filter(
            or_(
                User.email.ilike(pattern),
                User.name.ilike(pattern),
                User.memberships.any(
                    OrganizationMembership.organization.has(Organization.name.ilike(pattern))
                ),
            )
        )
    if verification == "verified":
        query = query.filter(User.email_verification_status == "verified", User.email_verified_at.is_not(None))
    elif verification == "unverified":
        query = query.filter(
            or_(User.email_verification_status != "verified", User.email_verified_at.is_(None))
        )
    if active == "active":
        query = query.filter(User.is_active.is_(True))
    elif active == "inactive":
        query = query.filter(User.is_active.is_(False))
    normalized_plan = (plan or "").strip().lower()
    if normalized_plan:
        query = query.filter(
            User.memberships.any(
                OrganizationMembership.organization.has(Organization.plan == normalized_plan)
            )
        )
    return query


def _sort_query(query, sort: SortOrder):
    if sort == "oldest":
        return query.order_by(User.created_at.asc(), User.id.asc())
    if sort == "recent_login":
        return query.order_by(User.last_login_at.desc(), User.created_at.desc(), User.id.asc())
    return query.order_by(User.created_at.desc(), User.id.asc())


def _overview(db: Session) -> dict:
    now = datetime.utcnow()
    total_accounts = db.query(func.count(User.id)).scalar() or 0
    verified_accounts = (
        db.query(func.count(User.id))
        .filter(User.email_verification_status == "verified", User.email_verified_at.is_not(None))
        .scalar()
        or 0
    )
    active_accounts = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    signed_in_accounts = db.query(func.count(User.id)).filter(User.last_login_at.is_not(None)).scalar() or 0
    total_organizations = db.query(func.count(Organization.id)).scalar() or 0
    total_workspaces = db.query(func.count(Workspace.id)).scalar() or 0
    paid_organizations = (
        db.query(func.count(Organization.id))
        .filter(Organization.subscription_status.in_(ACTIVE_PAID_STATES), Organization.plan != "free")
        .scalar()
        or 0
    )
    registrations_7d = (
        db.query(func.count(User.id)).filter(User.created_at >= now - timedelta(days=7)).scalar() or 0
    )
    registrations_30d = (
        db.query(func.count(User.id)).filter(User.created_at >= now - timedelta(days=30)).scalar() or 0
    )
    plan_rows = db.query(Organization.plan, func.count(Organization.id)).group_by(Organization.plan).all()
    return {
        "total_accounts": int(total_accounts),
        "verified_accounts": int(verified_accounts),
        "unverified_accounts": int(total_accounts - verified_accounts),
        "active_accounts": int(active_accounts),
        "inactive_accounts": int(total_accounts - active_accounts),
        "accounts_that_signed_in": int(signed_in_accounts),
        "registrations_7d": int(registrations_7d),
        "registrations_30d": int(registrations_30d),
        "total_organizations": int(total_organizations),
        "paid_organizations": int(paid_organizations),
        "total_workspaces": int(total_workspaces),
        "organizations_by_plan": {str(plan or "unknown"): int(count or 0) for plan, count in plan_rows},
    }


def _serialize_customers(db: Session, users: list[User]) -> list[dict]:
    if not users:
        return []
    user_ids = [user.id for user in users]
    memberships = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id.in_(user_ids))
        .order_by(OrganizationMembership.created_at.asc())
        .all()
    )
    memberships_by_user: dict[str, list[OrganizationMembership]] = defaultdict(list)
    org_ids: set[str] = set()
    for membership in memberships:
        memberships_by_user[membership.user_id].append(membership)
        org_ids.add(membership.organization_id)

    workspace_counts = {
        org_id: int(count or 0)
        for org_id, count in (
            db.query(Workspace.organization_id, func.count(Workspace.id))
            .filter(Workspace.organization_id.in_(org_ids))
            .group_by(Workspace.organization_id)
            .all()
            if org_ids
            else []
        )
    }
    usage_by_user = {
        user_id: {
            "event_count": int(event_count or 0),
            "quantity": int(quantity or 0),
            "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
        }
        for user_id, event_count, quantity, last_activity_at in (
            db.query(
                UsageEvent.user_id,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.quantity), 0),
                func.max(UsageEvent.created_at),
            )
            .filter(UsageEvent.user_id.in_(user_ids))
            .group_by(UsageEvent.user_id)
            .all()
        )
    }

    rows: list[dict] = []
    for user in users:
        organizations = []
        for membership in memberships_by_user.get(user.id, []):
            org = membership.organization
            organizations.append(
                {
                    "id": org.id,
                    "name": org.name,
                    "role": membership.role,
                    "plan": org.plan,
                    "subscription_status": org.subscription_status,
                    "workspace_count": workspace_counts.get(org.id, 0),
                    "created_at": org.created_at.isoformat() if org.created_at else None,
                }
            )
        rows.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "is_active": bool(user.is_active),
                "verification_status": user.email_verification_status,
                "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
                "auth_provider": user.auth_provider or "password",
                "organizations": organizations,
                "organization_count": len(organizations),
                "activity": usage_by_user.get(
                    user.id,
                    {"event_count": 0, "quantity": 0, "last_activity_at": None},
                ),
            }
        )
    return rows


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"


@router.get("/customers")
def list_customers(
    response: Response,
    search: str | None = Query(default=None, max_length=160),
    verification: VerificationFilter = "all",
    active: ActiveFilter = "all",
    plan: str | None = Query(default=None, max_length=40),
    sort: SortOrder = "newest",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _no_store(response)
    query = _filtered_users(
        db,
        search=search,
        verification=verification,
        active=active,
        plan=plan,
    )
    filtered_count = int(query.count())
    users = _sort_query(query, sort).offset(offset).limit(limit).all()
    logger.info(
        "Platform customer directory viewed actor_user_id=%s offset=%s limit=%s filtered_count=%s",
        ctx.user.id,
        offset,
        limit,
        filtered_count,
    )
    return {
        "overview": _overview(db),
        "customers": _serialize_customers(db, users),
        "pagination": {
            "offset": offset,
            "limit": limit,
            "filtered_count": filtered_count,
            "has_more": offset + len(users) < filtered_count,
        },
        "filters": {
            "search": search,
            "verification": verification,
            "active": active,
            "plan": plan,
            "sort": sort,
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def _csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@router.get("/customers.csv")
def export_customers_csv(
    search: str | None = Query(default=None, max_length=160),
    verification: VerificationFilter = "all",
    active: ActiveFilter = "all",
    plan: str | None = Query(default=None, max_length=40),
    sort: SortOrder = "newest",
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> Response:
    query = _filtered_users(
        db,
        search=search,
        verification=verification,
        active=active,
        plan=plan,
    )
    users = _sort_query(query, sort).limit(10_000).all()
    customers = _serialize_customers(db, users)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "name",
            "email",
            "account_created_at",
            "verification_status",
            "email_verified_at",
            "last_login_at",
            "active",
            "organizations",
            "plans",
            "subscription_statuses",
            "workspace_count",
            "activity_events",
            "last_activity_at",
        ]
    )
    for customer in customers:
        organizations = customer["organizations"]
        writer.writerow(
            [
                _csv_safe(customer["name"]),
                _csv_safe(customer["email"]),
                customer["created_at"],
                customer["verification_status"],
                customer["email_verified_at"],
                customer["last_login_at"],
                customer["is_active"],
                _csv_safe(" | ".join(org["name"] for org in organizations)),
                _csv_safe(" | ".join(org["plan"] for org in organizations)),
                _csv_safe(" | ".join(org["subscription_status"] for org in organizations)),
                sum(int(org["workspace_count"]) for org in organizations),
                customer["activity"]["event_count"],
                customer["activity"]["last_activity_at"],
            ]
        )
    logger.info("Platform customer CSV exported actor_user_id=%s rows=%s", ctx.user.id, len(customers))
    filename = f"agroai-customers-{datetime.utcnow().date().isoformat()}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
        },
    )
