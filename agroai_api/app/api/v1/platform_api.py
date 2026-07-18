from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
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
    PlatformWebhookDeliveryAttempt,
    PlatformWebhookEndpoint,
    PlatformWebhookEvent,
    PlatformWebhookOutbox,
)
from app.models.saas import Workspace
from app.platform_api.deps import require_developer_control_plane, require_platform_api_principal
from app.platform_api.idempotency import begin_idempotent_operation, complete_idempotent_operation
from app.platform_api.isolation import compatible_workspace_id
from app.platform_api.keys import create_platform_key, rotate_platform_key
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.credential_vault import production_vault_keyring_configured
from app.platform_api.rate_limits import apply_rate_limit_headers, enforce_rate_limit, platform_rate_limiter_readiness
from app.platform_api.route_manifest import manifest_dicts, public_routes
from app.platform_api.scopes import normalize_scopes, require_scopes
from app.platform_api.restrictions import enforce_provider_access, enforce_resource_access, provider_allowed
from app.platform_api.usage import record_usage_event
from app.platform_api.webhook_delivery import emit_webhook_event, publish_pending_webhook_outbox
from app.platform_api.webhooks import (
    SAFE_WEBHOOK_EVENTS,
    audit_webhook_event,
    disable_webhook_endpoint,
    generate_webhook_secret,
    revoke_webhook_endpoint,
    rotate_webhook_secret,
    store_webhook_secret,
    validate_webhook_url,
    webhook_secret_keyring,
)
from app.services.redis_task_queue import queue_configured
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
    provider_id: str | None = Field(default=None, max_length=120)
    resource_id: str | None = Field(default=None, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)


class WebhookRotateRequest(BaseModel):
    overlap_minutes: int = Field(default=60, ge=0, le=1440)


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
        "cidr_allowlist": list(row.cidr_allowlist_json or []),
        "provider_restrictions": dict(row.provider_restrictions_json or {}),
        "resource_restrictions": dict(row.resource_restrictions_json or {}),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "overlap_expires_at": row.overlap_expires_at.isoformat() if row.overlap_expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/platform/health")
def platform_health() -> dict[str, Any]:
    enabled = bool(getattr(settings, "PLATFORM_API_ENABLED", False))
    limiter = platform_rate_limiter_readiness() if enabled else {"ready": False, "backend": None, "reason": "platform_api_disabled"}
    production_vault_ready = production_vault_keyring_configured() if enabled and str(getattr(settings, "APP_ENV", "development")).lower() == "production" else None
    edge_auth_ready = bool(str(getattr(settings, "PLATFORM_API_EDGE_AUTH_SECRET", "") or "").strip())
    delivery_enabled = bool(getattr(settings, "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED", False))
    try:
        webhook_vault_ready = bool(webhook_secret_keyring()[1])
    except RuntimeError:
        webhook_vault_ready = False
    webhook_delivery_ready = (not delivery_enabled) or (webhook_vault_ready and queue_configured())
    runtime_ready = enabled and limiter["ready"] and production_vault_ready is not False and edge_auth_ready and webhook_delivery_ready
    return {
        "status": "ready" if runtime_ready else ("disabled" if not enabled else "not_ready"),
        "platform_api_enabled": enabled,
        "developer_control_plane_enabled": bool(getattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", False)),
        "rate_limiter": limiter,
        "production_vault_keyring_ready": production_vault_ready,
        "cidr_trusted_proxy_ready": edge_auth_ready,
        "webhook_delivery": {
            "enabled": delivery_enabled,
            "ready": webhook_delivery_ready,
            "vault_keyring_ready": webhook_vault_ready,
            "queue_ready": queue_configured() if delivery_enabled else False,
        },
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
    standard_headers = {
        "X-Request-Id": {"description": "Server-generated or accepted bounded request identifier.", "schema": {"type": "string"}},
        "RateLimit-Limit": {"description": "Effective request limit.", "schema": {"type": "integer"}},
        "RateLimit-Remaining": {"description": "Requests remaining in the limiting window.", "schema": {"type": "integer"}},
        "RateLimit-Reset": {"description": "Unix timestamp when the limiting window resets.", "schema": {"type": "integer"}},
    }
    for route in public_routes():
        path = route["route"].replace("/v1", "")
        method = route["method"].lower()
        response_schema = "GenericResponse"
        if path == "/platform/health":
            response_schema = "HealthResponse"
        elif path == "/platform/me":
            response_schema = "PrincipalResponse"
        elif path == "/platform/providers":
            response_schema = "ProviderListResponse"
        elif "validate-credentials" in path:
            response_schema = "ProviderValidationResponse"
        elif path == "/platform/actions/plan":
            response_schema = "ActionPlanResponse"
        success_headers = (
            standard_headers
            if route["rate_limit_policy"] != "none"
            else {"X-Request-Id": standard_headers["X-Request-Id"]}
        )
        operation: dict[str, Any] = {
            "summary": f"{route['surface']} {route['method']} {route['route']}",
            "x-agroai-surface": route["surface"],
            "x-agroai-authentication": route["authentication"],
            "x-agroai-required-scopes": list(route["required_scopes"]),
            "security": [] if route["authentication"] == "anonymous" else [{"PlatformApiKey": []}],
            "parameters": [
                {
                    "name": "X-Request-Id",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "maxLength": 128},
                }
            ],
            "responses": {
                "400": {"$ref": "#/components/responses/StandardError"},
                "401": {"$ref": "#/components/responses/StandardError"},
                "403": {"$ref": "#/components/responses/StandardError"},
                "409": {"$ref": "#/components/responses/StandardError"},
                "422": {"$ref": "#/components/responses/StandardError"},
                "429": {"$ref": "#/components/responses/StandardError"},
            },
        }
        if path != "/platform/actions/execute":
            operation["responses"]["200"] = {
                "description": "Success",
                "headers": success_headers,
                "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{response_schema}"}}},
            }
        if route["idempotency_required"]:
            operation["parameters"].append(
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "minLength": 1, "maxLength": 255},
                }
            )
        if method == "post":
            schema_name = "ProviderCredentialProbe" if "validate-credentials" in path else "ActionPlanRequest"
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema_name}"}}},
            }
        paths.setdefault(path, {})[method] = operation
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "AGRO-AI Platform API",
            "version": "2026-07-private-beta",
            "description": "Disabled-by-default private beta. Test and live project creation require separate server flags. EarthDaily and Valley are readiness-only; Valley physical writes are disabled.",
        },
        "servers": [{"url": "/v1", "description": "Platform API v1 base path"}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "PlatformApiKey": {"type": "http", "scheme": "bearer", "bearerFormat": "agro_test_... or agro_live_..."}
            },
            "schemas": {
                "GenericResponse": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "HealthResponse": {
                    "type": "object",
                    "required": ["status", "platform_api_enabled"],
                    "properties": {
                        "status": {"type": "string", "enum": ["ready", "disabled", "not_ready"]},
                        "platform_api_enabled": {"type": "boolean"},
                        "developer_control_plane_enabled": {"type": "boolean"},
                        "earthdaily_status": {"type": "string"},
                        "valley_irrigation_status": {"type": "string"},
                        "physical_irrigation_commands": {"type": "string", "enum": ["disabled"]},
                    },
                },
                "PrincipalResponse": {
                    "type": "object",
                    "required": ["status", "principal"],
                    "properties": {
                        "status": {"type": "string"},
                        "principal": {"type": "object", "additionalProperties": True},
                    },
                },
                "ProviderListResponse": {
                    "type": "object",
                    "required": ["status", "providers"],
                    "properties": {
                        "status": {"type": "string"},
                        "providers": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    },
                },
                "ProviderValidationResponse": {
                    "type": "object",
                    "required": ["status", "provider_id", "validation"],
                    "properties": {
                        "status": {"type": "string", "enum": ["ok"]},
                        "provider_id": {"type": "string"},
                        "validation": {"type": "object", "additionalProperties": True},
                    },
                },
                "ActionPlanResponse": {
                    "type": "object",
                    "required": ["status", "action_type", "execution_enabled", "requires_customer_approval"],
                    "properties": {
                        "status": {"type": "string", "enum": ["planned"]},
                        "action_type": {"type": "string"},
                        "execution_enabled": {"type": "boolean", "const": False},
                        "requires_customer_approval": {"type": "boolean"},
                        "message": {"type": "string"},
                    },
                },
                "StandardError": {
                    "type": "object",
                    "required": ["code", "type", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "type": {"type": "string"},
                        "message": {"type": "string"},
                        "request_id": {"type": ["string", "null"]},
                    },
                },
                "ProviderCredentialProbe": {
                    "type": "object",
                    "required": ["provider_id", "credentials"],
                    "properties": {
                        "provider_id": {"type": "string"},
                        "credentials": {"type": "object", "additionalProperties": True},
                    },
                },
                "ActionPlanRequest": {
                    "type": "object",
                    "required": ["action_type"],
                    "properties": {
                        "action_type": {"type": "string"},
                        "provider_id": {"type": ["string", "null"]},
                        "resource_id": {"type": ["string", "null"]},
                        "parameters": {"type": "object", "additionalProperties": True},
                    },
                },
                "Page": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {}},
                        "next_cursor": {"type": ["string", "null"]},
                        "has_more": {"type": "boolean"},
                    },
                },
            },
            "responses": {
                "StandardError": {
                    "description": "Standard Platform API error",
                    "headers": standard_headers,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/StandardError"}}},
                }
            },
        },
        "x-agroai-environments": {
            "test": {"semantics": "evaluation-only; creation disabled unless PLATFORM_API_TEST_PROJECTS_ENABLED=true"},
            "live": {"semantics": "disabled unless PLATFORM_API_LIVE_PROJECTS_ENABLED=true"},
        },
        "x-agroai-provider-readiness": {
            "earthdaily": "awaiting_partner_contract",
            "valley_irrigation": "awaiting_partner_contract; physical writes disabled",
        },
    }


@router.get("/platform/me")
def platform_me(
    response: Response,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"projects:read"})
    decision = enforce_rate_limit(principal, route_id="platform.me")
    apply_rate_limit_headers(response, decision)
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
    response: Response,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"connectors:read"})
    decision = enforce_rate_limit(principal, route_id="platform.providers")
    apply_rate_limit_headers(response, decision)
    record_usage_event(db, principal=principal, event_type="api_request", metric="api_requests", operation="platform.providers", status_code=200)
    db.commit()
    return {
        "status": "ok",
        "providers": [
            provider for provider in provider_catalog()
            if provider_allowed(principal, str(provider.get("provider_id")))
        ],
    }


@router.post("/platform/providers/{provider_id}/validate-credentials")
def validate_provider_credentials(
    provider_id: str,
    payload: ProviderCredentialProbe,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"connectors:write"})
    if payload.provider_id != provider_id:
        raise HTTPException(status_code=400, detail="Provider path and request body must match")
    enforce_provider_access(principal, provider_id)
    decision = enforce_rate_limit(principal, route_id="platform.provider.validate")
    apply_rate_limit_headers(response, decision)
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
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"actions:plan"})
    if payload.provider_id:
        enforce_provider_access(principal, payload.provider_id)
    enforce_resource_access(principal, resource_id=payload.resource_id)
    decision = enforce_rate_limit(principal, route_id="platform.actions.plan")
    apply_rate_limit_headers(response, decision)
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
    emit_webhook_event(
        db,
        organization_id=principal.organization_id,
        api_project_id=principal.api_project_id,
        event_type="action.approval_required",
        payload={
            "action_type": payload.action_type,
            "provider_id": payload.provider_id,
            "resource_id": payload.resource_id,
            "execution_enabled": False,
        },
    )
    record_usage_event(db, principal=principal, event_type="action_plan", metric="operational_command_plans", operation="platform.actions.plan", status_code=200)
    db.commit()
    return body


@router.post("/platform/actions/execute")
def execute_action(
    payload: ActionPlanRequest,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"actions:execute"})
    if payload.provider_id:
        enforce_provider_access(principal, payload.provider_id)
    enforce_resource_access(principal, resource_id=payload.resource_id)
    enforce_rate_limit(principal, route_id="platform.actions.execute")
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
    if payload.environment == "test" and not bool(getattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", False)):
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
    try:
        workspace_id = compatible_workspace_id(
            db,
            organization_id=ctx.organization.id,
            project=project,
            supplied_workspace_id=payload.workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scopes = normalize_scopes(payload.scopes)
    now = datetime.utcnow()
    row = ApiServiceAccount(
        organization_id=ctx.organization.id,
        api_project_id=project.id,
        workspace_id=workspace_id,
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
    try:
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    try:
        new_key, plaintext = rotate_platform_key(db, old_key=row, overlap_minutes=payload.overlap_minutes, rotated_by_user_id=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        id=str(uuid.uuid4()),
        organization_id=ctx.organization.id,
        api_project_id=project.id,
        url="",
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
    try:
        row.url = validate_webhook_url(payload.url)
        store_webhook_secret(row, plaintext)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(row)
    audit_webhook_event(
        db,
        endpoint=row,
        action="created",
        actor_type="portal_user",
        actor_id=ctx.user.id,
    )
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


def _owned_webhook(db: Session, *, endpoint_id: str, organization_id: str) -> PlatformWebhookEndpoint:
    endpoint = (
        db.query(PlatformWebhookEndpoint)
        .filter(
            PlatformWebhookEndpoint.id == endpoint_id,
            PlatformWebhookEndpoint.organization_id == organization_id,
        )
        .first()
    )
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    project = db.get(ApiProject, endpoint.api_project_id)
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    return endpoint


@router.post("/platform/developer/webhooks/{endpoint_id}/secret/rotate")
def rotate_webhook_endpoint_secret(
    endpoint_id: str,
    payload: WebhookRotateRequest,
    ctx=Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    endpoint = _owned_webhook(db, endpoint_id=endpoint_id, organization_id=ctx.organization.id)
    try:
        plaintext = rotate_webhook_secret(
            db,
            endpoint=endpoint,
            actor_id=ctx.user.id,
            overlap_minutes=payload.overlap_minutes,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {
        "status": "rotated",
        "webhook_id": endpoint.id,
        "signing_secret_prefix": endpoint.signing_secret_prefix,
        "signing_secret": plaintext,
        "plaintext_display": "one_time_only",
        "previous_secret_expires_at": endpoint.previous_secret_expires_at.isoformat()
        if endpoint.previous_secret_expires_at
        else None,
    }


@router.post("/platform/developer/webhooks/{endpoint_id}/disable")
def disable_webhook(
    endpoint_id: str,
    ctx=Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    endpoint = _owned_webhook(db, endpoint_id=endpoint_id, organization_id=ctx.organization.id)
    disable_webhook_endpoint(db, endpoint=endpoint, actor_id=ctx.user.id)
    db.query(PlatformWebhookOutbox).filter(
        PlatformWebhookOutbox.endpoint_id == endpoint.id,
        PlatformWebhookOutbox.status.in_(["pending", "queued", "retrying", "delivering"]),
    ).update(
        {
            PlatformWebhookOutbox.status: "failed",
            PlatformWebhookOutbox.last_error: "endpoint_disabled",
            PlatformWebhookOutbox.completed_at: datetime.utcnow(),
        },
        synchronize_session=False,
    )
    db.commit()
    return {"status": "disabled", "webhook_id": endpoint.id}


@router.post("/platform/developer/webhooks/{endpoint_id}/revoke")
def revoke_webhook(
    endpoint_id: str,
    ctx=Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    endpoint = _owned_webhook(db, endpoint_id=endpoint_id, organization_id=ctx.organization.id)
    revoke_webhook_endpoint(db, endpoint=endpoint, actor_id=ctx.user.id)
    db.commit()
    return {"status": "revoked", "webhook_id": endpoint.id}


@router.get("/platform/developer/webhooks/{endpoint_id}/deliveries")
def webhook_delivery_history(
    endpoint_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    ctx=Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    endpoint = _owned_webhook(db, endpoint_id=endpoint_id, organization_id=ctx.organization.id)
    outboxes = (
        db.query(PlatformWebhookOutbox)
        .filter(
            PlatformWebhookOutbox.endpoint_id == endpoint.id,
            PlatformWebhookOutbox.organization_id == ctx.organization.id,
        )
        .order_by(PlatformWebhookOutbox.created_at.desc())
        .limit(limit)
        .all()
    )
    deliveries = []
    for outbox in outboxes:
        event = db.get(PlatformWebhookEvent, outbox.event_id)
        attempts = (
            db.query(PlatformWebhookDeliveryAttempt)
            .filter(
                PlatformWebhookDeliveryAttempt.endpoint_id == endpoint.id,
                PlatformWebhookDeliveryAttempt.event_id == outbox.event_id,
            )
            .order_by(PlatformWebhookDeliveryAttempt.attempt_number.asc())
            .all()
        )
        deliveries.append(
            {
                "id": outbox.id,
                "event_id": outbox.event_id,
                "event_type": event.event_type if event else None,
                "event_version": event.version if event else None,
                "status": outbox.status,
                "attempt_count": outbox.attempt_count,
                "next_attempt_at": outbox.next_attempt_at.isoformat() if outbox.next_attempt_at else None,
                "completed_at": outbox.completed_at.isoformat() if outbox.completed_at else None,
                "attempts": [
                    {
                        "id": attempt.id,
                        "attempt_number": attempt.attempt_number,
                        "status": attempt.status,
                        "response_status": attempt.response_status,
                        "response_excerpt": attempt.response_excerpt,
                        "error_classification": attempt.error_classification,
                        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
                    }
                    for attempt in attempts
                ],
            }
        )
    return {"status": "ok", "deliveries": deliveries}


@router.post(
    "/platform/developer/webhooks/{endpoint_id}/deliveries/{delivery_id}/redeliver",
    status_code=status.HTTP_202_ACCEPTED,
)
def redeliver_webhook(
    endpoint_id: str,
    delivery_id: str,
    ctx=Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    endpoint = _owned_webhook(db, endpoint_id=endpoint_id, organization_id=ctx.organization.id)
    if endpoint.status != "active" or endpoint.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Webhook endpoint is not active")
    outbox = (
        db.query(PlatformWebhookOutbox)
        .filter(
            PlatformWebhookOutbox.id == delivery_id,
            PlatformWebhookOutbox.endpoint_id == endpoint.id,
            PlatformWebhookOutbox.organization_id == ctx.organization.id,
            PlatformWebhookOutbox.api_project_id == endpoint.api_project_id,
        )
        .first()
    )
    if outbox is None:
        raise HTTPException(status_code=404, detail="Webhook delivery not found")
    original_event = db.get(PlatformWebhookEvent, outbox.event_id)
    if (
        original_event is None
        or original_event.organization_id != ctx.organization.id
        or original_event.api_project_id != endpoint.api_project_id
    ):
        raise HTTPException(status_code=404, detail="Webhook event not found")
    now = datetime.utcnow()
    replay_event = PlatformWebhookEvent(
        organization_id=original_event.organization_id,
        api_project_id=original_event.api_project_id,
        event_type=original_event.event_type,
        version=original_event.version,
        payload_json=dict(original_event.payload_json or {}),
        created_at=now,
    )
    db.add(replay_event)
    db.flush()
    replay_outbox = PlatformWebhookOutbox(
        organization_id=ctx.organization.id,
        api_project_id=endpoint.api_project_id,
        event_id=replay_event.id,
        endpoint_id=endpoint.id,
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(replay_outbox)
    db.flush()
    audit_webhook_event(
        db,
        endpoint=endpoint,
        action="manual_redelivery_requested",
        actor_type="portal_user",
        actor_id=ctx.user.id,
        details={
            "original_delivery_id": outbox.id,
            "original_event_id": outbox.event_id,
            "redelivery_id": replay_outbox.id,
            "redelivery_event_id": replay_event.id,
        },
    )
    db.commit()
    queue_result = publish_pending_webhook_outbox(db, limit=1)
    return {
        "status": "queued" if queue_result["published"] else "accepted",
        "delivery_id": replay_outbox.id,
        "event_id": replay_event.id,
        "delivery_enabled": bool(getattr(settings, "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED", False)),
    }
