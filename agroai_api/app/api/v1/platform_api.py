from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import get_db
from app.models.platform_api import (
    ApiProject,
    ApiServiceAccount,
    PlatformApiKey,
    PlatformApiUsageEvent,
    PlatformWebhookEndpoint,
)
from app.models.saas import Workspace
from app.platform_api.deps import require_developer_control_plane, require_platform_api_principal
from app.platform_api.idempotency import begin_idempotent_operation, complete_idempotent_operation
from app.platform_api.keys import create_platform_key, rotate_platform_key
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.rate_limits import enforce_rate_limit
from app.platform_api.route_manifest import manifest_dicts, public_routes
from app.platform_api.scopes import normalize_scopes, require_scopes
from app.platform_api.usage import record_usage_event
from app.platform_api.webhooks import SAFE_WEBHOOK_EVENTS, generate_webhook_secret, validate_webhook_url
from app.provider_adapters.registry import get_provider_adapter, provider_catalog


router = APIRouter(tags=["platform-api"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=80)
    environment: str = Field(pattern="^(test|live)$")
    workspace_id: str | None = None


class ServiceAccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    scopes: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    resource_restrictions: dict[str, Any] = Field(default_factory=dict)
    provider_restrictions: dict[str, Any] = Field(default_factory=dict)


class KeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(default_factory=list)
    expires_days: int | None = Field(default=None, ge=1, le=3660)
    workspace_id: str | None = None
    cidr_allowlist: list[str] = Field(default_factory=list)
    provider_restrictions: dict[str, Any] = Field(default_factory=dict)
    resource_restrictions: dict[str, Any] = Field(default_factory=dict)


class RotateKeyRequest(BaseModel):
    overlap_minutes: int = Field(default=60, ge=0, le=1440)


class WebhookCreate(BaseModel):
    api_project_id: str
    url: str
    description: str | None = Field(default=None, max_length=1000)
    subscribed_event_types: list[str] = Field(default_factory=list)


class ProviderCredentialProbe(BaseModel):
    provider_id: str
    credentials: dict[str, Any] = Field(default_factory=dict)


class ActionPlanRequest(BaseModel):
    action_type: str = Field(min_length=1, max_length=120)
    resource_id: str | None = Field(default=None, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "api-project"


def _project_public(row: ApiProject) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "slug": row.slug,
        "environment": row.environment,
        "status": row.status,
        "default_rate_limit_policy": row.default_rate_limit_policy or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _service_account_public(row: ApiServiceAccount) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "api_project_id": row.api_project_id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "scopes": list(row.scopes or []),
        "resource_restrictions": row.resource_restrictions_json or {},
        "provider_restrictions": row.provider_restrictions_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "disabled_at": row.disabled_at.isoformat() if row.disabled_at else None,
    }


def _key_public(row: PlatformApiKey) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "api_project_id": row.api_project_id,
        "service_account_id": row.service_account_id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "environment": row.environment,
        "scopes": list(row.scopes or []),
        "status": row.status,
        "key_prefix": row.key_prefix,
        "fingerprint": row.fingerprint,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "overlap_expires_at": row.overlap_expires_at.isoformat() if row.overlap_expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/platform/health")
def platform_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "platform_api_enabled": bool(getattr(settings, "PLATFORM_API_ENABLED", False)),
        "developer_control_plane_enabled": bool(getattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", False)),
        "earthdaily_status": "awaiting_partner_contract",
        "valley_irrigation_status": "awaiting_partner_contract",
        "physical_irrigation_commands": "disabled",
    }


@router.get("/platform/route-manifest")
def route_manifest() -> dict[str, Any]:
    return {"status": "ok", "routes": manifest_dicts()}


@router.get("/platform/openapi.json")
def platform_openapi() -> dict[str, Any]:
    if not bool(getattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", False)):
        raise HTTPException(status_code=404, detail="Not found")
    paths: dict[str, Any] = {}
    for route in public_routes():
        path = route["route"].replace("/v1", "")
        method = route["method"].lower()
        paths.setdefault(path, {})[method] = {
            "summary": f"{route['surface']} {route['method']} {route['route']}",
            "x-agroai-surface": route["surface"],
            "x-agroai-authentication": route["authentication"],
            "x-agroai-required-scopes": list(route["required_scopes"]),
            "responses": {
                "200": {"description": "Success"},
                "401": {"description": "Authentication error"},
                "403": {"description": "Authorization error"},
                "429": {"description": "Rate limit"},
            },
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "AGRO-AI Platform API", "version": "2026-07-private-beta"},
        "paths": paths,
    }


@router.get("/platform/me")
def platform_me(
    response: Response,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"projects:read"})
    decision = enforce_rate_limit(principal, route_id="platform.me")
    response.headers["RateLimit-Limit"] = str(decision.limit)
    response.headers["RateLimit-Remaining"] = str(decision.remaining)
    response.headers["RateLimit-Reset"] = str(decision.reset_epoch)
    record_usage_event(db, principal=principal, event_type="api_request", metric="api_requests", operation="platform.me", status_code=200)
    db.commit()
    return {
        "status": "ok",
        "principal": {
            "authentication_type": principal.authentication_type,
            "organization_id": principal.organization_id,
            "workspace_id": principal.workspace_id,
            "api_project_id": principal.api_project_id,
            "service_account_id": principal.service_account_id,
            "api_key_id": principal.api_key_id,
            "scopes": sorted(principal.scopes),
            "environment": principal.environment,
            "request_id": principal.request_id,
            "provider_restrictions": principal.provider_restrictions,
            "resource_restrictions": principal.resource_restrictions,
        },
    }


@router.get("/platform/providers")
def platform_providers(
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"connectors:read"})
    enforce_rate_limit(principal, route_id="platform.providers")
    record_usage_event(db, principal=principal, event_type="api_request", metric="api_requests", operation="platform.providers", status_code=200)
    db.commit()
    return {"status": "ok", "providers": provider_catalog()}


@router.post("/platform/providers/{provider_id}/validate-credentials")
def validate_provider_credentials(
    provider_id: str,
    payload: ProviderCredentialProbe,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"connectors:write"})
    enforce_rate_limit(principal, route_id="platform.provider.validate", cost=2)
    idem, replay = begin_idempotent_operation(db, principal=principal, operation=f"provider.validate:{provider_id}", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    adapter = get_provider_adapter(provider_id)
    result = adapter.validate_credentials(payload.credentials)
    body = {"status": "ok", "provider_id": provider_id, "validation": result}
    complete_idempotent_operation(idem, response_status=200, response_json=body)
    record_usage_event(db, principal=principal, event_type="provider_validation", metric="api_requests", operation="platform.provider.validate", status_code=200)
    db.commit()
    return body


@router.post("/platform/actions/plan")
def plan_action(
    payload: ActionPlanRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"actions:plan"})
    enforce_rate_limit(principal, route_id="platform.actions.plan", cost=2)
    idem, replay = begin_idempotent_operation(db, principal=principal, operation="actions.plan", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    body = {
        "status": "planned",
        "action_type": payload.action_type,
        "execution_enabled": False,
        "requires_customer_approval": True,
        "message": "Action planning is available, but physical execution remains disabled in the private beta foundation.",
    }
    complete_idempotent_operation(idem, response_status=200, response_json=body)
    record_usage_event(db, principal=principal, event_type="action_plan", metric="operational_command_plans", operation="platform.actions.plan", status_code=200)
    db.commit()
    return body


@router.post("/platform/actions/execute")
def execute_action(
    payload: ActionPlanRequest,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"actions:execute"})
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "physical_action_disabled",
            "type": "safety_error",
            "message": "Physical irrigation command execution is disabled for the Platform API private beta.",
            "request_id": principal.request_id,
        },
    )


@router.get("/platform/developer/projects")
def list_projects(ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.query(ApiProject).filter(ApiProject.organization_id == ctx.organization.id).order_by(ApiProject.created_at.desc()).all()
    return {"status": "ok", "projects": [_project_public(row) for row in rows]}


@router.post("/platform/developer/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.environment == "live" and not bool(getattr(settings, "PLATFORM_API_LIVE_PROJECTS_ENABLED", False)):
        raise HTTPException(status_code=403, detail="Live Platform API projects are not enabled")
    if payload.environment == "test" and not bool(getattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", True)):
        raise HTTPException(status_code=403, detail="Test Platform API projects are not enabled")
    if payload.workspace_id:
        workspace = db.get(Workspace, payload.workspace_id)
        if not workspace or workspace.organization_id != ctx.organization.id:
            raise HTTPException(status_code=404, detail="Workspace not found")
    now = datetime.utcnow()
    row = ApiProject(
        organization_id=ctx.organization.id,
        workspace_id=payload.workspace_id,
        name=payload.name,
        slug=payload.slug or _slug(payload.name),
        environment=payload.environment,
        status="active" if payload.environment == "test" else "disabled",
        default_rate_limit_policy={"window_seconds": 60, "burst": 60 if payload.environment == "test" else 600},
        created_by_user_id=ctx.user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "ok", "project": _project_public(row)}


@router.post("/platform/developer/projects/{project_id}/service-accounts", status_code=status.HTTP_201_CREATED)
def create_service_account(project_id: str, payload: ServiceAccountCreate, ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = db.get(ApiProject, project_id)
    if not project or project.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Project not found")
    scopes = normalize_scopes(payload.scopes)
    now = datetime.utcnow()
    row = ApiServiceAccount(
        organization_id=ctx.organization.id,
        api_project_id=project.id,
        workspace_id=payload.workspace_id or project.workspace_id,
        name=payload.name,
        description=payload.description,
        status="active",
        scopes=scopes,
        resource_restrictions_json=payload.resource_restrictions,
        provider_restrictions_json=payload.provider_restrictions,
        created_by_user_id=ctx.user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "ok", "service_account": _service_account_public(row)}


@router.post("/platform/developer/service-accounts/{service_account_id}/keys", status_code=status.HTTP_201_CREATED)
def create_key(service_account_id: str, payload: KeyCreate, ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    service_account = db.get(ApiServiceAccount, service_account_id)
    if not service_account or service_account.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Service account not found")
    project = db.get(ApiProject, service_account.api_project_id)
    if not project or project.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Project not found")
    requested_scopes = normalize_scopes(payload.scopes)
    if not set(requested_scopes).issubset(set(service_account.scopes or [])):
        raise HTTPException(status_code=403, detail="Key scopes must be a subset of service account scopes")
    row, plaintext = create_platform_key(
        db,
        project=project,
        service_account=service_account,
        name=payload.name,
        scopes=requested_scopes,
        created_by_user_id=ctx.user.id,
        expires_days=payload.expires_days,
        workspace_id=payload.workspace_id,
        cidr_allowlist=payload.cidr_allowlist,
        provider_restrictions=payload.provider_restrictions,
        resource_restrictions=payload.resource_restrictions,
    )
    db.commit()
    db.refresh(row)
    return {"status": "ok", "key": _key_public(row), "plaintext_key": plaintext, "plaintext_display": "one_time_only"}


@router.post("/platform/developer/keys/{key_id}/revoke")
def revoke_key(key_id: str, ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(PlatformApiKey, key_id)
    if not row or row.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Key not found")
    row.status = "revoked"
    row.revoked_at = datetime.utcnow()
    row.revoked_by_user_id = ctx.user.id
    db.commit()
    return {"status": "revoked", "key": _key_public(row)}


@router.post("/platform/developer/keys/{key_id}/rotate")
def rotate_key(key_id: str, payload: RotateKeyRequest, ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(PlatformApiKey, key_id)
    if not row or row.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Key not found")
    new_key, plaintext = rotate_platform_key(db, old_key=row, overlap_minutes=payload.overlap_minutes, rotated_by_user_id=ctx.user.id)
    db.commit()
    db.refresh(new_key)
    return {"status": "rotated", "old_key": _key_public(row), "new_key": _key_public(new_key), "plaintext_key": plaintext, "plaintext_display": "one_time_only"}


@router.get("/platform/developer/usage")
def usage_summary(ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = (
        db.query(PlatformApiUsageEvent.metric, func.count(PlatformApiUsageEvent.id), func.sum(PlatformApiUsageEvent.quantity))
        .filter(PlatformApiUsageEvent.organization_id == ctx.organization.id)
        .group_by(PlatformApiUsageEvent.metric)
        .all()
    )
    return {"status": "ok", "usage": [{"metric": metric, "events": count, "quantity": quantity or 0} for metric, count, quantity in rows]}


@router.post("/platform/developer/webhooks", status_code=status.HTTP_201_CREATED)
def create_webhook(payload: WebhookCreate, ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = db.get(ApiProject, payload.api_project_id)
    if not project or project.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Project not found")
    event_types = sorted(set(payload.subscribed_event_types))
    unsupported = [event for event in event_types if event not in SAFE_WEBHOOK_EVENTS]
    if unsupported:
        raise HTTPException(status_code=400, detail={"unsupported_event_types": unsupported})
    plaintext, digest, prefix = generate_webhook_secret()
    now = datetime.utcnow()
    row = PlatformWebhookEndpoint(
        organization_id=ctx.organization.id,
        api_project_id=project.id,
        url=validate_webhook_url(payload.url),
        description=payload.description,
        subscribed_event_types=event_types,
        status="active",
        signing_secret_hash=digest,
        signing_secret_prefix=prefix,
        signing_secret_version="v1",
        created_by_user_id=ctx.user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "status": "ok",
        "webhook": {
            "id": row.id,
            "api_project_id": row.api_project_id,
            "url": row.url,
            "description": row.description,
            "subscribed_event_types": row.subscribed_event_types,
            "status": row.status,
            "signing_secret_prefix": row.signing_secret_prefix,
        },
        "signing_secret": plaintext,
        "plaintext_display": "one_time_only",
    }


@router.get("/platform/developer/webhooks")
def list_webhooks(ctx=Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.query(PlatformWebhookEndpoint).filter(PlatformWebhookEndpoint.organization_id == ctx.organization.id).order_by(PlatformWebhookEndpoint.created_at.desc()).all()
    return {
        "status": "ok",
        "webhooks": [
            {
                "id": row.id,
                "api_project_id": row.api_project_id,
                "url": row.url,
                "description": row.description,
                "subscribed_event_types": row.subscribed_event_types,
                "status": row.status,
                "signing_secret_prefix": row.signing_secret_prefix,
            }
            for row in rows
        ],
    }
