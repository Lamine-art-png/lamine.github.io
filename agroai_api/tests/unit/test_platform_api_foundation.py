from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.security import create_access_token, get_current_tenant_id
from app.main import app
from fastapi import HTTPException

from app.models.platform_api import (
    ApiProject,
    ApiServiceAccount,
    PlatformApiKey,
    PlatformWebhookEndpoint,
)
from app.models.platform_api import ActionSafetyConfiguration
from app.models.platform_product import PlatformProgramEnrollment
from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.platform_api.action_safety import PhysicalActionSafetyInput, evaluate_physical_action_safety
from app.platform_api.credential_vault import (
    CredentialVaultContext,
    inspect_platform_connector_secret,
    retrieve_platform_connector_secret,
    revoke_platform_connector_secret,
    rotate_platform_connector_secret,
    store_platform_connector_secret,
)
from app.platform_api.idempotency import begin_idempotent_operation, complete_idempotent_operation
from app.platform_api.keys import create_platform_key, rotate_platform_key, verify_platform_key
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.rate_limits import _MEMORY_BUCKETS, RedisRateLimiter, check_rate_limit, enforce_rate_limit
from app.platform_api.webhooks import generate_webhook_secret, validate_webhook_url, webhook_signature
from app.api.v1.platform_api import platform_health
from app.provider_adapters.security import validate_provider_base_url
from app.provider_adapters.registry import get_provider_adapter, provider_catalog


def _vault_key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("=")


class SharedFakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}
        self.responses = {}
        self.fail = False

    def eval(self, _script, numkeys, *keys_and_args):
        if self.fail:
            raise RuntimeError("redis unavailable")
        keys = list(keys_and_args[:numkeys])
        args = list(keys_and_args[numkeys:])
        cost = int(args[0])
        now = int(args[1])
        counter_count = int(args[2])
        retry_key = keys[counter_count]
        if retry_key in self.responses:
            return self.responses[retry_key]
        allowed = 1
        selected_limit = 0
        selected_reset = 0
        min_remaining = None
        retry_after = 0
        for index, key in enumerate(keys[:counter_count]):
            offset = 3 + index * 3
            limit = int(args[offset])
            _window_seconds = int(args[offset + 1])
            reset = int(args[offset + 2])
            used = self.values.get(key, 0) + cost
            self.values[key] = used
            if used == cost:
                self.expirations[key] = reset + 5
            remaining = limit - used
            if min_remaining is None or remaining < min_remaining:
                min_remaining = remaining
                selected_limit = limit
                selected_reset = reset
            if used > limit:
                allowed = 0
                retry_after = max(retry_after, reset - now)
        result = [allowed, selected_limit, max(0, min_remaining or 0), selected_reset, max(1, retry_after) if not allowed else 0]
        self.responses[retry_key] = result
        return result


class AmbiguousWriteFakeRedis(SharedFakeRedis):
    def __init__(self):
        super().__init__()
        self.raise_after_first_write = True

    def eval(self, *args, **kwargs):
        result = super().eval(*args, **kwargs)
        if self.raise_after_first_write:
            from redis.exceptions import ConnectionError as RedisConnectionError

            self.raise_after_first_write = False
            raise RedisConnectionError("response lost after atomic write")
        return result


def _org(db):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"owner-platform-{suffix}@example.com",
        password_hash="x",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()
    org = Organization(
        name="Platform Farms",
        slug=f"platform-farms-{suffix}",
        owner_user_id=user.id,
        plan="enterprise",
        subscription_status="active",
    )
    db.add(org)
    db.flush()
    workspace = Workspace(organization_id=org.id, name="Platform Workspace", mode="evaluation")
    db.add(workspace)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
    db.add(
        PlatformProgramEnrollment(
            organization_id=org.id,
            program="developer_private_beta",
            status="active",
            approved_by_user_id=user.id,
            approved_at=datetime.utcnow(),
            allowed_environments_json=["test", "live"],
            maximum_projects=20,
            maximum_live_projects=10,
            maximum_service_accounts=50,
            maximum_keys=100,
            maximum_webhooks=50,
            billing_mode="none",
        )
    )
    db.commit()
    return user, org, workspace


def _project_and_key(db, *, scopes=None, environment="test"):
    user, org, workspace = _org(db)
    project = ApiProject(
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Private beta",
        slug="private-beta",
        environment=environment,
        status="active",
        default_rate_limit_policy={},
        created_by_user_id=user.id,
    )
    db.add(project)
    db.flush()
    service_account = ApiServiceAccount(
        organization_id=org.id,
        api_project_id=project.id,
        workspace_id=workspace.id,
        name="sync",
        status="active",
        scopes=scopes or ["projects:read", "connectors:read", "actions:plan", "actions:execute"],
        created_by_user_id=user.id,
    )
    db.add(service_account)
    db.flush()
    key, plaintext = create_platform_key(
        db,
        project=project,
        service_account=service_account,
        name="test key",
        scopes=scopes or ["projects:read", "connectors:read", "actions:plan", "actions:execute"],
        created_by_user_id=user.id,
        workspace_id=workspace.id,
    )
    db.commit()
    return user, org, workspace, project, service_account, key, plaintext


def _connector_connection(db, *, org, workspace, provider="earthdaily", status="credentials_submitted"):
    connection = ConnectorConnection(
        tenant_id=org.id,
        workspace_id=workspace.id,
        provider=provider,
        display_name=provider,
        status=status,
        mode="api",
        required_plan="enterprise",
        config_json={},
    )
    db.add(connection)
    db.flush()
    return connection


def _platform_principal_for(org, workspace, project, service_account, key=None, *, scopes=None, provider_restrictions=None):
    return PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id=org.id,
        workspace_id=workspace.id,
        api_project_id=project.id,
        service_account_id=service_account.id,
        api_key_id=key.id if key is not None else "key-test",
        scopes=frozenset(scopes or {"connectors:sync", "connectors:read"}),
        environment=project.environment,
        provider_restrictions=provider_restrictions or {},
    )


def test_platform_key_plaintext_is_one_time_and_hash_is_not_public(db):
    *_items, key, plaintext = _project_and_key(db)

    assert plaintext.startswith("agro_test_")
    assert key.key_hash != plaintext
    public = {
        "id": key.id,
        "key_prefix": key.key_prefix,
        "fingerprint": key.fingerprint,
        "scopes": key.scopes,
    }
    assert "key_hash" not in public
    assert plaintext not in str(public)


def test_platform_key_verification_is_read_oriented(db, monkeypatch):
    *_items, key, plaintext = _project_and_key(db)
    calls = {"commit": 0}
    original_commit = db.commit

    def counted_commit():
        calls["commit"] += 1
        return original_commit()

    monkeypatch.setattr(db, "commit", counted_commit)
    verified = verify_platform_key(db, plaintext)

    assert verified is not None
    assert verified.key.id == key.id
    assert calls["commit"] == 0


def test_platform_routes_require_platform_api_key_and_do_not_accept_portal_jwt(client, db, monkeypatch):
    user, *_rest = _project_and_key(db)
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    token = create_access_token({"sub": user.id})

    response = client.get("/v1/platform/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_api_key"


def test_test_tenant_fallback_cannot_activate_in_production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "attacker-controlled-value")

    with pytest.raises(HTTPException) as exc:
        get_current_tenant_id(credentials=None)

    assert exc.value.status_code == 401


def test_legacy_demo_tenant_fallback_remains_local_only(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    assert get_current_tenant_id(credentials=None) == "demo-tenant"


def test_platform_key_can_call_me_with_scope(client, db, monkeypatch):
    *_items, plaintext = _project_and_key(db)
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")

    response = client.get("/v1/platform/me", headers={"Authorization": f"Bearer {plaintext}", "X-Request-Id": "req-test-1"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["principal"]["authentication_type"] == "platform_api_key"
    assert body["principal"]["request_id"].startswith("req_")
    assert body["principal"]["request_id"] != "req-test-1"
    assert response.headers["x-request-id"] == body["principal"]["request_id"]


def test_platform_rate_limit_response_uses_standard_envelope_and_headers(client, db, monkeypatch):
    *_items, plaintext = _project_and_key(db)
    _MEMORY_BUCKETS.clear()
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_BURST_LIMIT", 1)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_SUSTAINED_LIMIT", 10)
    monkeypatch.setattr(settings, "APP_ENV", "test")

    first = client.get("/v1/platform/me", headers={"Authorization": f"Bearer {plaintext}"})
    denied = client.get("/v1/platform/me", headers={"Authorization": f"Bearer {plaintext}"})

    assert first.status_code == 200
    assert first.headers["RateLimit-Limit"] == "1"
    assert first.headers["RateLimit-Remaining"] == "0"
    assert "RateLimit-Reset" in first.headers
    assert denied.status_code == 429
    assert denied.json()["code"] == "rate_limit_exceeded"
    assert "detail" not in denied.json()
    assert denied.headers["RateLimit-Limit"] == "1"
    assert denied.headers["RateLimit-Remaining"] == "0"
    assert "RateLimit-Reset" in denied.headers
    assert int(denied.headers["Retry-After"]) >= 1


def test_provider_readiness_adapters_do_not_claim_live_status():
    catalog = provider_catalog()
    earthdaily = get_provider_adapter("earthdaily").metadata()
    valley = get_provider_adapter("valley_irrigation").metadata()

    assert {item["provider_id"] for item in catalog} >= {"earthdaily", "valley_irrigation"}
    assert earthdaily.readiness == "awaiting_partner_contract"
    assert valley.readiness == "awaiting_partner_contract"
    assert any(capability.name == "physical_command_execution" and capability.status == "disabled" for capability in valley.capabilities)


def test_physical_action_execution_is_disabled(client, db, monkeypatch):
    *_items, plaintext = _project_and_key(db)
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")

    response = client.post(
        "/v1/platform/actions/execute",
        headers={"Authorization": f"Bearer {plaintext}"},
        json={"action_type": "irrigation_start", "resource_id": "pivot-1", "parameters": {"minutes": 10}},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "physical_action_disabled"


def test_public_openapi_excludes_internal_admin_and_portal_routes(client, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", True)

    response = client.get("/v1/platform/openapi.json")

    assert response.status_code == 200
    text = response.text
    assert "/internal/queue" not in text
    assert "/platform-admin" not in text
    assert "/auth/login" not in text


def test_public_openapi_reviewed_snapshot_digest(client, monkeypatch):
    """Any public contract change requires an explicit reviewed digest update."""

    monkeypatch.setattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", True)
    response = client.get("/v1/platform/openapi.json")
    assert response.status_code == 200
    canonical = json.dumps(response.json(), sort_keys=True, separators=(",", ":")).encode()
    expected = (
        Path(__file__).resolve().parents[1]
        / "contracts"
        / "platform_api_openapi.sha256"
    ).read_text(encoding="utf-8").strip()
    assert hashlib.sha256(canonical).hexdigest() == expected


def test_route_manifest_is_private_until_docs_enabled_and_remains_curated(client, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", False)
    assert client.get("/v1/platform/route-manifest").status_code == 404

    monkeypatch.setattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", True)
    response = client.get("/v1/platform/route-manifest")

    assert response.status_code == 200
    routes = response.json()["routes"]
    assert routes
    assert all(route["public_openapi"] is True for route in routes)
    rendered = json.dumps(routes)
    assert "/platform/developer/" not in rendered
    assert "/internal/" not in rendered
    assert "/platform-admin" not in rendered
    assert "/auth/" not in rendered


def test_disabled_developer_control_plane_has_no_platform_admin_bypass(client, db, monkeypatch):
    user, _org_row, _workspace, _project, _service_account, _key, _plaintext = _project_and_key(db)
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", user.email)
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", False)
    token = create_access_token({"sub": user.id})

    response = client.get(
        "/v1/platform/developer/projects",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("verification_status", "expected_status"),
    [
        ("approved", 200),
        ("approved_legacy", 200),
        ("pending", 401),
        ("rejected", 401),
        ("blocked", 401),
        ("suspended", 401),
        ("verification_required", 401),
        ("unrecognized_status", 401),
    ],
)
def test_platform_key_authentication_enforces_current_organization_status(
    client,
    db,
    monkeypatch,
    verification_status,
    expected_status,
):
    _user, organization, _workspace, _project, _service_account, _key, plaintext = _project_and_key(db)
    organization.verification_status = verification_status
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")

    response = client.get(
        "/v1/platform/me",
        headers={"Authorization": f"Bearer {plaintext}"},
    )

    assert response.status_code == expected_status


def test_organization_status_change_immediately_invalidates_existing_platform_key(
    client,
    db,
    monkeypatch,
):
    _user, organization, _workspace, _project, _service_account, _key, plaintext = _project_and_key(db)
    organization.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    headers = {"Authorization": f"Bearer {plaintext}"}

    assert client.get("/v1/platform/me", headers=headers).status_code == 200
    organization.verification_status = "suspended"
    db.commit()
    assert client.get("/v1/platform/me", headers=headers).status_code == 401


@pytest.mark.parametrize("verification_status", ["approved", "approved_legacy"])
def test_approved_organization_can_use_explicitly_enabled_developer_control_plane(
    client,
    db,
    monkeypatch,
    verification_status,
):
    user, organization, _workspace, _project, _service_account, _key, _plaintext = _project_and_key(db)
    organization.verification_status = verification_status
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    token = create_access_token({"sub": user.id})

    response = client.get(
        "/v1/platform/developer/projects",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_unapproved_organization_cannot_create_platform_control_plane_resources(
    client,
    db,
    monkeypatch,
):
    user, organization, workspace, project, service_account, _key, _plaintext = _project_and_key(db)
    organization.verification_status = "pending"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", True)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}
    counts_before = (
        db.query(ApiProject).count(),
        db.query(ApiServiceAccount).count(),
        db.query(PlatformApiKey).count(),
        db.query(PlatformWebhookEndpoint).count(),
    )

    responses = [
        client.post(
            "/v1/platform/developer/projects",
            headers=headers,
            json={
                "name": "Denied project",
                "slug": "denied-project",
                "environment": "test",
                "workspace_id": workspace.id,
            },
        ),
        client.post(
            f"/v1/platform/developer/projects/{project.id}/service-accounts",
            headers=headers,
            json={
                "name": "Denied service account",
                "scopes": ["projects:read"],
                "workspace_id": workspace.id,
            },
        ),
        client.post(
            f"/v1/platform/developer/service-accounts/{service_account.id}/keys",
            headers=headers,
            json={"name": "Denied key", "scopes": ["projects:read"]},
        ),
        client.post(
            "/v1/platform/developer/webhooks",
            headers=headers,
            json={
                "api_project_id": project.id,
                "url": "https://hooks.example.com/agroai",
                "subscribed_event_types": ["sync.completed"],
            },
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert counts_before == (
        db.query(ApiProject).count(),
        db.query(ApiServiceAccount).count(),
        db.query(PlatformApiKey).count(),
        db.query(PlatformWebhookEndpoint).count(),
    )


def test_platform_key_creation_service_rejects_unapproved_organization(db):
    user, organization, _workspace, project, service_account, _key, _plaintext = _project_and_key(db)
    organization.verification_status = "rejected"
    db.commit()

    with pytest.raises(ValueError, match="organization is not approved"):
        create_platform_key(
            db,
            project=project,
            service_account=service_account,
            name="denied",
            scopes=["projects:read"],
            created_by_user_id=user.id,
        )


def test_pre_platform_root_route_order_is_preserved_and_platform_routes_are_additive():
    baseline_paths = [
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/v1/readiness",
        "/health",
        "/v1/health",
        "/v1/runtime/ai-status",
        "/v1/auth/email-delivery/status",
    ]
    actual_paths = [getattr(route, "path", "") for route in app.routes]

    assert actual_paths[: len(baseline_paths)] == baseline_paths
    assert "/v1/platform/me" in actual_paths
    assert "/v1/auth/login" in actual_paths
    assert "/v1/orgs" in actual_paths
    assert "/v1/connectors/connect" in actual_paths


def test_full_openapi_operation_surface_has_no_method_path_collisions():
    schema = app.openapi()
    operations = [
        (method.upper(), path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}
    ]

    assert len(operations) == len(set(operations))
    assert any(path.startswith("/v1/platform/") for _method, path in operations)


def test_rate_limiter_memory_backend_fails_closed_in_production(monkeypatch):
    *_items, key, plaintext = (None, None, None, None, None, None, "unused")
    from app.platform_api.principal import PlatformPrincipal

    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "production")
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id="org",
        api_project_id="project",
        api_key_id="key",
        environment="live",
    )

    with pytest.raises(RuntimeError):
        check_rate_limit(principal, route_id="test")


def test_rate_limiter_fail_open_override_cannot_activate_in_production(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_FAIL_OPEN", True)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id="org",
        api_project_id="project",
        api_key_id="key",
        environment="live",
    )

    with pytest.raises(RuntimeError):
        check_rate_limit(principal, route_id="platform.me")


def test_rate_limiter_unavailable_is_a_fail_closed_503(monkeypatch):
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id="org",
        api_project_id="project",
        api_key_id="key",
        environment="live",
        request_id="req-unavailable",
    )

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("app.platform_api.rate_limits.check_rate_limit", unavailable)
    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(principal, route_id="platform.me")

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "rate_limiter_unavailable"
    assert exc.value.detail["request_id"] == "req-unavailable"


def test_platform_health_is_not_ready_when_enabled_without_redis(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(settings, "PLATFORM_API_REDIS_URL", "")
    monkeypatch.setattr(settings, "REDIS_URL", "")

    health = platform_health()

    assert health["status"] == "not_ready"
    assert health["rate_limiter"] == {"ready": False, "backend": "redis", "reason": "redis_url_missing"}


def test_key_expiration_revocation_project_and_service_account_disable(db):
    *_items, project, service_account, key, plaintext = _project_and_key(db)

    key.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert verify_platform_key(db, plaintext) is None

    *_items2, project2, service_account2, key2, plaintext2 = _project_and_key(db)
    key2.revoked_at = datetime.utcnow()
    db.commit()
    assert verify_platform_key(db, plaintext2) is None

    *_items3, project3, service_account3, key3, plaintext3 = _project_and_key(db)
    project3.status = "disabled"
    db.commit()
    assert verify_platform_key(db, plaintext3) is None

    project3.status = "active"
    service_account3.status = "disabled"
    db.commit()
    assert verify_platform_key(db, plaintext3) is None


def test_key_rotation_overlap_and_old_key_expiry(db):
    user, _org_row, _workspace, _project, _service_account, old_key, old_plaintext = _project_and_key(db)

    new_key, new_plaintext = rotate_platform_key(db, old_key=old_key, overlap_minutes=5, rotated_by_user_id=user.id)
    db.commit()

    assert verify_platform_key(db, old_plaintext).key.id == old_key.id
    assert verify_platform_key(db, new_plaintext).key.id == new_key.id

    old_key.overlap_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    assert verify_platform_key(db, old_plaintext) is None
    assert verify_platform_key(db, new_plaintext).key.id == new_key.id


def test_workspace_and_service_account_project_isolation(db):
    user, org, workspace = _org(db)
    other_user, other_org, other_workspace = _org(db)
    project = ApiProject(
        organization_id=org.id,
        workspace_id=workspace.id,
        name="A",
        slug="a",
        environment="test",
        status="active",
        created_by_user_id=user.id,
    )
    db.add(project)
    db.flush()
    service_account = ApiServiceAccount(
        organization_id=org.id,
        api_project_id=project.id,
        name="sa",
        status="active",
        scopes=["projects:read"],
        created_by_user_id=user.id,
    )
    db.add(service_account)
    db.flush()

    with pytest.raises(ValueError):
        create_platform_key(
            db,
            project=project,
            service_account=service_account,
            name="bad workspace",
            scopes=["projects:read"],
            created_by_user_id=user.id,
            workspace_id=other_workspace.id,
        )

    other_project = ApiProject(
        organization_id=other_org.id,
        name="B",
        slug="b",
        environment="test",
        status="active",
        created_by_user_id=other_user.id,
    )
    db.add(other_project)
    db.flush()
    with pytest.raises(ValueError):
        create_platform_key(
            db,
            project=other_project,
            service_account=service_account,
            name="bad project",
            scopes=["projects:read"],
            created_by_user_id=user.id,
        )


def test_scopes_provider_and_resource_restrictions_are_server_derived(client, db, monkeypatch):
    user, org, workspace = _org(db)
    project = ApiProject(
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Restricted",
        slug="restricted",
        environment="test",
        status="active",
        created_by_user_id=user.id,
    )
    db.add(project)
    db.flush()
    service_account = ApiServiceAccount(
        organization_id=org.id,
        api_project_id=project.id,
        workspace_id=workspace.id,
        name="restricted-sa",
        status="active",
        scopes=["projects:read"],
        created_by_user_id=user.id,
    )
    db.add(service_account)
    db.flush()
    _key, plaintext = create_platform_key(
        db,
        project=project,
        service_account=service_account,
        name="restricted",
        scopes=["projects:read"],
        created_by_user_id=user.id,
        provider_restrictions={"allow": ["earthdaily"]},
        resource_restrictions={"field_ids": ["field-1"]},
    )
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")

    response = client.get(
        "/v1/platform/me",
        headers={
            "Authorization": f"Bearer {plaintext}",
            "X-Organization-Id": "forged-org",
            "X-Workspace-Id": "forged-workspace",
        },
    )

    assert response.status_code == 200
    principal = response.json()["principal"]
    assert principal["organization_id"] == org.id
    assert principal["workspace_id"] == workspace.id
    assert principal["provider_restrictions"] == {"allow": ["earthdaily"]}
    assert principal["resource_restrictions"] == {"field_ids": ["field-1"]}


def test_key_without_required_scope_is_denied(client, db, monkeypatch):
    *_items, plaintext = _project_and_key(db, scopes=["projects:read"])
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")

    response = client.get("/v1/platform/providers", headers={"Authorization": f"Bearer {plaintext}"})

    assert response.status_code == 403
    assert response.json()["code"] == "scope_denied"


def test_idempotency_replay_and_payload_conflict(db):
    principal = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org-i", api_project_id="project-i", request_id="req-1")
    first, replayed = begin_idempotent_operation(db, principal=principal, operation="sync", idempotency_key="idem-1", payload={"a": 1})
    assert replayed is False
    complete_idempotent_operation(first, response_status=202, response_json={"job_id": "job-1"})
    db.commit()

    second, replayed = begin_idempotent_operation(db, principal=principal, operation="sync", idempotency_key="idem-1", payload={"a": 1})
    assert second.id == first.id
    assert replayed is True

    with pytest.raises(HTTPException) as exc:
        begin_idempotent_operation(db, principal=principal, operation="sync", idempotency_key="idem-1", payload={"a": 2})
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "idempotency_conflict"


def test_rate_limit_dimensions_costs_and_429_headers(monkeypatch):
    _MEMORY_BUCKETS.clear()
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    principal = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org", api_project_id="project", api_key_id="key", environment="test")
    other_key = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org", api_project_id="project", api_key_id="key-2", environment="test")

    first = check_rate_limit(principal, route_id="weighted", cost=59)
    assert first.allowed is True
    assert first.remaining == 1
    assert check_rate_limit(other_key, route_id="weighted", cost=1).allowed is True

    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(principal, route_id="weighted", cost=2)
    assert exc.value.status_code == 429
    assert exc.value.headers["RateLimit-Limit"] == "60"
    assert exc.value.headers["RateLimit-Remaining"] == "0"
    assert "Retry-After" in exc.value.headers


def test_rate_limit_uses_server_owned_weighted_route_costs(monkeypatch):
    _MEMORY_BUCKETS.clear()
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_BURST_LIMIT", 3)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_SUSTAINED_LIMIT", 10)
    monkeypatch.setattr(settings, "APP_ENV", "test")
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id="org-weighted",
        api_project_id="project-weighted",
        api_key_id="key-weighted",
        environment="test",
    )

    validation = check_rate_limit(principal, route_id="platform.provider.validate")
    read = check_rate_limit(principal, route_id="platform.me")
    denied = check_rate_limit(principal, route_id="platform.providers")

    assert validation.allowed is True
    assert validation.remaining == 1
    assert read.allowed is True
    assert read.remaining == 0
    assert denied.allowed is False


def test_redis_rate_limiter_shares_state_across_instances_and_dimensions():
    fake = SharedFakeRedis()
    limiter_a = RedisRateLimiter(client=fake)
    limiter_b = RedisRateLimiter(client=fake)
    principal = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org", api_project_id="project", api_key_id="key", environment="test")

    first = limiter_a.check(principal, cost=59)
    second = limiter_b.check(principal, cost=2)

    assert first.allowed is True
    assert second.allowed is False
    assert second.limit == 60
    assert second.remaining == 0
    assert second.retry_after > 0


def test_redis_rate_limiter_isolates_organizations_projects_keys_and_environments():
    fake = SharedFakeRedis()
    limiter = RedisRateLimiter(client=fake)
    base = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org", api_project_id="project", api_key_id="key", environment="test")
    other_org = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org-2", api_project_id="project-2", api_key_id="key-2", environment="test")
    live_same_ids = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org", api_project_id="project", api_key_id="key", environment="live")

    assert limiter.check(base, cost=60).allowed is True
    assert limiter.check(base, cost=1).allowed is False
    assert limiter.check(other_org, cost=60).allowed is True
    assert limiter.check(live_same_ids, cost=600).allowed is True


def test_redis_rate_limiter_failure_is_not_allowed_by_default():
    fake = SharedFakeRedis()
    fake.fail = True
    limiter = RedisRateLimiter(client=fake)
    principal = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org", api_project_id="project", api_key_id="key", environment="live")

    with pytest.raises(RuntimeError):
        limiter.check(principal, cost=1)


def test_redis_rate_limiter_retry_is_idempotent_after_ambiguous_write():
    fake = AmbiguousWriteFakeRedis()
    limiter = RedisRateLimiter(client=fake, max_retries=1)
    principal = PlatformPrincipal(authentication_type="platform_api_key", organization_id="org", api_project_id="project", api_key_id="key", environment="test")

    decision = limiter.check(principal, cost=59, operation_id="one-logical-check")

    assert decision.allowed is True
    assert decision.remaining == 1
    assert set(fake.values.values()) == {59}


def test_live_and_test_key_prefixes_differ(db):
    *_test_items, test_plaintext = _project_and_key(db, environment="test")
    *_live_items, live_plaintext = _project_and_key(db, environment="live")

    assert test_plaintext.startswith("agro_test_")
    assert live_plaintext.startswith("agro_live_")


def test_webhook_secret_signature_and_url_ssrf_protection(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    secret, digest, prefix = generate_webhook_secret()
    assert secret.startswith("whsec_")
    assert digest != secret
    assert prefix == secret[:14]
    signature = webhook_signature(secret, timestamp="1700000000", event_id="evt_1", payload=b'{"ok":true}')
    assert signature == webhook_signature(secret, timestamp="1700000000", event_id="evt_1", payload=b'{"ok":true}')
    assert validate_webhook_url("https://hooks.example.com/agroai") == "https://hooks.example.com/agroai"
    for unsafe in ("http://hooks.example.com", "https://user:pass@hooks.example.com", "https://localhost/hook", "https://internal.local/hook"):
        with pytest.raises(ValueError):
            validate_webhook_url(unsafe)


def test_platform_credential_vault_authorized_provider_job_round_trip(db, monkeypatch):
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", _vault_key())
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v-test")
    user, org, workspace, project, service_account, key, _plaintext = _project_and_key(db, scopes=["connectors:sync"])
    connection = _connector_connection(db, org=org, workspace=workspace, provider="earthdaily")
    row = store_platform_connector_secret(
        db,
        organization_id=org.id,
        api_project_id=project.id,
        connection=connection,
        provider="earthdaily",
        secret_type="provider_credentials",
        payload={"access_token": "secret-token"},
    )
    db.commit()
    principal = _platform_principal_for(org, workspace, project, service_account, key, scopes={"connectors:sync"})
    context = CredentialVaultContext(
        principal=principal,
        provider_job_authorized=True,
        connection_id=connection.id,
        provider="earthdaily",
        secret_type="provider_credentials",
    )

    metadata = inspect_platform_connector_secret(db, organization_id=org.id, connection_id=connection.id)
    loaded = retrieve_platform_connector_secret(db, context=context)

    assert loaded == {"access_token": "secret-token"}
    assert row.ciphertext_b64 != "secret-token"
    assert "ciphertext" not in metadata
    assert "nonce" not in metadata
    assert "secret-token" not in str(metadata)


def test_platform_credential_vault_denies_wrong_ownership_contexts(db, monkeypatch):
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", _vault_key())
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v-test")
    user, org, workspace, project, service_account, key, _plaintext = _project_and_key(db, scopes=["connectors:sync"])
    _other_user, other_org, other_workspace, other_project, other_sa, other_key, _other_plaintext = _project_and_key(db, scopes=["connectors:sync"])
    connection = _connector_connection(db, org=org, workspace=workspace, provider="earthdaily")
    store_platform_connector_secret(
        db,
        organization_id=org.id,
        api_project_id=project.id,
        connection=connection,
        provider="earthdaily",
        secret_type="provider_credentials",
        payload={"access_token": "secret-token"},
    )
    db.commit()

    good_principal = _platform_principal_for(org, workspace, project, service_account, key, scopes={"connectors:sync"})
    other_org_principal = _platform_principal_for(other_org, other_workspace, other_project, other_sa, other_key, scopes={"connectors:sync"})
    no_sync_scope = _platform_principal_for(org, workspace, project, service_account, key, scopes={"connectors:read"})
    wrong_project = replace(good_principal, api_project_id=other_project.id)
    wrong_service_account = replace(good_principal, service_account_id=other_sa.id)
    legacy_tenant_principal = replace(good_principal, authentication_type="portal_user")
    cases = [
        CredentialVaultContext(principal=good_principal, provider_job_authorized=False, connection_id=connection.id, provider="earthdaily"),
        CredentialVaultContext(principal=other_org_principal, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily"),
        CredentialVaultContext(principal=good_principal, provider_job_authorized=True, connection_id="wrong-connection", provider="earthdaily"),
        CredentialVaultContext(principal=good_principal, provider_job_authorized=True, connection_id=connection.id, provider="valley_irrigation"),
        CredentialVaultContext(principal=good_principal, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily", secret_type="webhook_secret"),
        CredentialVaultContext(principal=no_sync_scope, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily"),
        CredentialVaultContext(principal=wrong_project, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily"),
        CredentialVaultContext(principal=wrong_service_account, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily"),
        CredentialVaultContext(principal=legacy_tenant_principal, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily"),
    ]

    for context in cases:
        with pytest.raises(PermissionError):
            retrieve_platform_connector_secret(db, context=context)


def test_platform_credential_vault_store_denies_cross_project_and_workspace_custody(db, monkeypatch):
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", _vault_key())
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v-test")
    user, org, workspace, project, _service_account, _key, _plaintext = _project_and_key(db, scopes=["connectors:sync"])
    _other_user, _other_org, _other_workspace, other_project, _other_sa, _other_key, _other_plaintext = _project_and_key(
        db,
        scopes=["connectors:sync"],
    )
    connection = _connector_connection(db, org=org, workspace=workspace, provider="earthdaily")

    with pytest.raises(ValueError, match="api project ownership mismatch"):
        store_platform_connector_secret(
            db,
            organization_id=org.id,
            api_project_id=other_project.id,
            connection=connection,
            provider="earthdaily",
            payload={"access_token": "must-not-be-written"},
        )

    other_workspace = Workspace(organization_id=org.id, name="Other Platform Workspace", mode="evaluation")
    db.add(other_workspace)
    db.flush()
    other_workspace_project = ApiProject(
        organization_id=org.id,
        workspace_id=other_workspace.id,
        name="Other workspace project",
        slug=f"other-workspace-{uuid.uuid4().hex[:8]}",
        environment="test",
        status="active",
        default_rate_limit_policy={},
        created_by_user_id=user.id,
    )
    db.add(other_workspace_project)
    db.flush()

    with pytest.raises(ValueError, match="api project workspace mismatch"):
        store_platform_connector_secret(
            db,
            organization_id=org.id,
            api_project_id=other_workspace_project.id,
            connection=connection,
            provider="earthdaily",
            payload={"access_token": "must-not-be-written"},
        )

    row = store_platform_connector_secret(
        db,
        organization_id=org.id,
        api_project_id=project.id,
        connection=connection,
        provider="earthdaily",
        payload={"access_token": "encrypted"},
    )
    assert row.tenant_id == org.id


def test_platform_credential_vault_rotation_revocation_and_provider_restriction(db, monkeypatch):
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", _vault_key())
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v-test")
    user, org, workspace, project, service_account, key, _plaintext = _project_and_key(db, scopes=["connectors:sync"])
    connection = _connector_connection(db, org=org, workspace=workspace, provider="earthdaily")
    store_platform_connector_secret(db, organization_id=org.id, api_project_id=project.id, connection=connection, provider="earthdaily", payload={"access_token": "old"})
    db.commit()
    rotate_platform_connector_secret(db, organization_id=org.id, api_project_id=project.id, connection=connection, provider="earthdaily", payload={"access_token": "new"})
    db.commit()
    principal = _platform_principal_for(
        org,
        workspace,
        project,
        service_account,
        key,
        scopes={"connectors:sync"},
        provider_restrictions={"allow": ["earthdaily"]},
    )
    context = CredentialVaultContext(principal=principal, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily")

    assert retrieve_platform_connector_secret(db, context=context) == {"access_token": "new"}
    restricted = _platform_principal_for(
        org,
        workspace,
        project,
        service_account,
        key,
        scopes={"connectors:sync"},
        provider_restrictions={"allow": ["valley_irrigation"]},
    )
    with pytest.raises(PermissionError):
        retrieve_platform_connector_secret(db, context=CredentialVaultContext(principal=restricted, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily"))

    assert revoke_platform_connector_secret(db, organization_id=org.id, connection_id=connection.id) is True
    db.commit()
    with pytest.raises(LookupError):
        retrieve_platform_connector_secret(db, context=context)


def test_platform_credential_vault_requires_explicit_versioned_keyring_in_production(db, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "PLATFORM_API_KEY_PEPPER", "explicit-test-pepper")
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", _vault_key())
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v-test")
    monkeypatch.delenv("CONNECTOR_CREDENTIAL_KEYS_JSON", raising=False)
    _user, org, workspace, project, _service_account, _key, _plaintext = _project_and_key(db, scopes=["connectors:sync"])
    connection = _connector_connection(db, org=org, workspace=workspace, provider="earthdaily")

    with pytest.raises(RuntimeError, match="CONNECTOR_CREDENTIAL_KEYS_JSON"):
        store_platform_connector_secret(
            db,
            organization_id=org.id,
            api_project_id=project.id,
            connection=connection,
            provider="earthdaily",
            payload={"access_token": "must-not-be-written"},
        )

    monkeypatch.setenv("CONNECTOR_CREDENTIAL_KEYS_JSON", json.dumps({"v-test": _vault_key()}))
    row = store_platform_connector_secret(
        db,
        organization_id=org.id,
        api_project_id=project.id,
        connection=connection,
        provider="earthdaily",
        payload={"access_token": "encrypted"},
    )
    assert row.key_version == "v-test"


def test_platform_credential_vault_never_logs_plaintext(db, monkeypatch, caplog):
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", _vault_key())
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v-test")
    _user, org, workspace, project, service_account, key, _plaintext = _project_and_key(db, scopes=["connectors:sync"])
    connection = _connector_connection(db, org=org, workspace=workspace, provider="earthdaily")
    secret = "plaintext-must-never-appear-in-logs"
    store_platform_connector_secret(
        db,
        organization_id=org.id,
        api_project_id=project.id,
        connection=connection,
        provider="earthdaily",
        payload={"access_token": secret},
    )
    principal = _platform_principal_for(org, workspace, project, service_account, key, scopes={"connectors:sync"})
    retrieve_platform_connector_secret(
        db,
        context=CredentialVaultContext(
            principal=principal,
            provider_job_authorized=True,
            connection_id=connection.id,
            provider="earthdaily",
        ),
    )

    assert secret not in caplog.text


def test_provider_base_url_ssrf_and_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "PROVIDER_BASE_URL_ALLOWLIST", "api.partner.example")
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    assert validate_provider_base_url("https://api.partner.example/v1") == "https://api.partner.example/v1"
    for unsafe in ("http://api.partner.example", "https://user:pass@api.partner.example", "https://other.example", "https://127.0.0.1"):
        with pytest.raises(ValueError):
            validate_provider_base_url(unsafe)


def test_earthdaily_normalization_preserves_provenance_quality_and_unknown_fields():
    adapter = get_provider_adapter("earthdaily")
    normalized = adapter.normalize_record(
        {
            "scene_id": "scene-1",
            "field_id": "field-1",
            "acquired_at": "2026-07-01T00:00:00Z",
            "quality_flags": ["cloud"],
            "vegetation_index": 0.72,
            "provider_specific": "kept",
        }
    )

    assert normalized["provider"] == "earthdaily"
    assert normalized["external_id"] == "scene-1"
    assert normalized["quality_flags"] == ["cloud"]
    assert normalized["provenance"]["contract_status"] == "awaiting_partner_contract"
    assert normalized["provider_extensions"] == {"provider_specific": "kept"}


def test_valley_normalization_and_write_capability_disabled():
    adapter = get_provider_adapter("valley_irrigation")
    normalized = adapter.normalize_record(
        {
            "equipment_id": "pivot-1",
            "field_id": "field-1",
            "timestamp": "2026-07-01T00:00:00Z",
            "position": 42,
            "flow": 1200,
            "alarm_code": "LOW_PRESSURE",
            "unknown": "kept",
        }
    )
    metadata = adapter.metadata()

    assert normalized["provider"] == "valley_irrigation"
    assert normalized["canonical_type"] == "alarm"
    assert normalized["alarm"]["code"] == "LOW_PRESSURE"
    assert normalized["provenance"]["write_capability"] == "disabled"
    assert normalized["provider_extensions"] == {"unknown": "kept"}
    assert any(capability.name == "physical_command_execution" and capability.status == "disabled" for capability in metadata.capabilities)


def test_valley_physical_write_safety_gates_default_to_denied(db, monkeypatch):
    user, org, workspace = _org(db)
    project = ApiProject(
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Live",
        slug="live",
        environment="live",
        status="active",
        created_by_user_id=user.id,
    )
    db.add(project)
    db.flush()
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id=org.id,
        workspace_id=workspace.id,
        api_project_id=project.id,
        scopes={"actions:execute"},
        environment="live",
    )
    monkeypatch.setattr(settings, "VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED", False)

    result = evaluate_physical_action_safety(
        db,
        principal=principal,
        request=PhysicalActionSafetyInput(
            provider="valley_irrigation",
            command_type="irrigation_start",
            resource_id="pivot-1",
            connection_id="connection-1",
            approval_confirmed=True,
            equipment_state_observed_at=datetime.utcnow(),
            provider_write_capability=True,
            commercial_entitlement_verified=True,
        ),
    )

    assert result["allowed"] is False
    assert result["physical_execution_enabled"] is False
    assert "global_write_disabled" in result["blockers"]


def test_valley_physical_write_scope_environment_approval_staleness_and_ai_gates(db, monkeypatch):
    user, org, workspace = _org(db)
    project = ApiProject(
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Test",
        slug="test",
        environment="test",
        status="active",
        created_by_user_id=user.id,
    )
    db.add(project)
    db.flush()
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id=org.id,
        workspace_id=workspace.id,
        api_project_id=project.id,
        scopes={"actions:plan"},
        environment="test",
    )
    monkeypatch.setattr(settings, "VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED", True)

    result = evaluate_physical_action_safety(
        db,
        principal=principal,
        request=PhysicalActionSafetyInput(
            provider="valley_irrigation",
            command_type="irrigation_start",
            resource_id="pivot-1",
            approval_confirmed=False,
            equipment_state_observed_at=datetime.utcnow() - timedelta(hours=1),
            provider_write_capability=False,
            commercial_entitlement_verified=False,
            ai_recommendation_only=True,
        ),
    )

    assert result["allowed"] is False
    assert {
        "live_environment_required",
        "actions_execute_scope_required",
        "explicit_customer_approval_required",
        "equipment_state_stale",
        "provider_write_capability_unconfirmed",
        "commercial_entitlement_required",
        "ai_recommendation_cannot_authorize_execution",
    }.issubset(set(result["blockers"]))


def test_valley_physical_write_configured_kill_switches_are_enforced(db, monkeypatch):
    user, org, workspace = _org(db)
    project = ApiProject(
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Live Controls",
        slug="live-controls",
        environment="live",
        status="active",
        created_by_user_id=user.id,
    )
    db.add(project)
    db.flush()
    db.add_all(
        [
            ActionSafetyConfiguration(organization_id=org.id, command_type="*", disabled=True),
            ActionSafetyConfiguration(organization_id=org.id, api_project_id=project.id, command_type="*", disabled=True),
            ActionSafetyConfiguration(organization_id=org.id, connection_id="connection-1", command_type="*", disabled=True),
            ActionSafetyConfiguration(organization_id=org.id, resource_id="pivot-1", command_type="irrigation_start", disabled=True),
        ]
    )
    db.commit()
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id=org.id,
        workspace_id=workspace.id,
        api_project_id=project.id,
        scopes={"actions:execute"},
        environment="live",
    )
    monkeypatch.setattr(settings, "VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED", True)

    result = evaluate_physical_action_safety(
        db,
        principal=principal,
        request=PhysicalActionSafetyInput(
            provider="valley_irrigation",
            command_type="irrigation_start",
            resource_id="pivot-1",
            connection_id="connection-1",
            approval_confirmed=True,
            equipment_state_observed_at=datetime.utcnow(),
            provider_write_capability=True,
            commercial_entitlement_verified=True,
        ),
    )

    assert result["allowed"] is False
    assert {
        "organization_write_disabled",
        "project_write_disabled",
        "connection_write_disabled",
        "resource_write_disabled",
    }.issubset(set(result["blockers"]))


def test_risky_feature_flags_default_safely():
    assert settings.PLATFORM_API_ENABLED is False
    assert settings.PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED is False
    assert settings.PLATFORM_API_TEST_PROJECTS_ENABLED is False
    assert settings.PLATFORM_API_LIVE_PROJECTS_ENABLED is False
    assert settings.PLATFORM_API_WEBHOOK_DELIVERY_ENABLED is False
    assert settings.PLATFORM_API_PUBLIC_DOCS_ENABLED is False
    assert settings.PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED is False
    assert settings.EARTHDAILY_ADAPTER_ENABLED is False
    assert settings.VALLEY_IRRIGATION_ADAPTER_ENABLED is False
    assert settings.VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED is False
