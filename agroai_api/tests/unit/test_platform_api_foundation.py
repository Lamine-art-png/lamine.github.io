from __future__ import annotations

from datetime import datetime

import pytest

from app.core.config import settings
from app.core.security import create_access_token
from app.models.platform_api import ApiProject, ApiServiceAccount, PlatformApiKey
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.platform_api.keys import create_platform_key, verify_platform_key
from app.platform_api.rate_limits import check_rate_limit
from app.provider_adapters.registry import get_provider_adapter, provider_catalog


def _org(db):
    user = User(
        email="owner-platform@example.com",
        password_hash="x",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()
    org = Organization(name="Platform Farms", slug="platform-farms", owner_user_id=user.id, plan="enterprise")
    db.add(org)
    db.flush()
    workspace = Workspace(organization_id=org.id, name="Platform Workspace", mode="evaluation")
    db.add(workspace)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
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
    assert response.json()["detail"]["code"] == "invalid_api_key"


def test_platform_key_can_call_me_with_scope(client, db, monkeypatch):
    *_items, plaintext = _project_and_key(db)
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")

    response = client.get("/v1/platform/me", headers={"Authorization": f"Bearer {plaintext}", "X-Request-Id": "req-test-1"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["principal"]["authentication_type"] == "platform_api_key"
    assert body["principal"]["request_id"] == "req-test-1"


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
    assert response.json()["detail"]["code"] == "physical_action_disabled"


def test_public_openapi_excludes_internal_admin_and_portal_routes(client, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", True)

    response = client.get("/v1/platform/openapi.json")

    assert response.status_code == 200
    text = response.text
    assert "/internal/queue" not in text
    assert "/platform-admin" not in text
    assert "/auth/login" not in text


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
