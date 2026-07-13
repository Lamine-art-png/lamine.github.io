from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta

import pytest

from app.core.config import settings
from app.core.security import create_access_token
from fastapi import HTTPException

from app.models.platform_api import ApiProject, ApiServiceAccount, PlatformApiKey
from app.models.platform_api import ActionSafetyConfiguration
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
from app.provider_adapters.security import validate_provider_base_url
from app.provider_adapters.registry import get_provider_adapter, provider_catalog


def _vault_key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("=")


class SharedFakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}
        self.fail = False

    def eval(self, _script, numkeys, *keys_and_args):
        if self.fail:
            raise RuntimeError("redis unavailable")
        keys = list(keys_and_args[:numkeys])
        args = list(keys_and_args[numkeys:])
        cost = int(args[0])
        now = int(args[1])
        allowed = 1
        selected_limit = 0
        selected_reset = 0
        min_remaining = None
        retry_after = 0
        for index, key in enumerate(keys):
            offset = 2 + index * 3
            limit = int(args[offset])
            window_seconds = int(args[offset + 1])
            reset = int(args[offset + 2])
            used = self.values.get(key, 0) + cost
            self.values[key] = used
            if used == cost:
                self.expirations[key] = window_seconds + 5
            remaining = limit - used
            if min_remaining is None or remaining < min_remaining:
                min_remaining = remaining
                selected_limit = limit
                selected_reset = reset
            if used > limit:
                allowed = 0
                retry_after = max(retry_after, reset - now)
        return [allowed, selected_limit, max(0, min_remaining or 0), selected_reset, max(1, retry_after) if not allowed else 0]


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
    assert response.json()["detail"]["code"] == "scope_denied"


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


def test_live_and_test_key_prefixes_differ(db):
    *_test_items, test_plaintext = _project_and_key(db, environment="test")
    *_live_items, live_plaintext = _project_and_key(db, environment="live")

    assert test_plaintext.startswith("agro_test_")
    assert live_plaintext.startswith("agro_live_")


def test_webhook_secret_signature_and_url_ssrf_protection():
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
    cases = [
        CredentialVaultContext(principal=good_principal, provider_job_authorized=False, connection_id=connection.id, provider="earthdaily"),
        CredentialVaultContext(principal=other_org_principal, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily"),
        CredentialVaultContext(principal=good_principal, provider_job_authorized=True, connection_id="wrong-connection", provider="earthdaily"),
        CredentialVaultContext(principal=good_principal, provider_job_authorized=True, connection_id=connection.id, provider="valley_irrigation"),
        CredentialVaultContext(principal=good_principal, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily", secret_type="webhook_secret"),
        CredentialVaultContext(principal=no_sync_scope, provider_job_authorized=True, connection_id=connection.id, provider="earthdaily"),
    ]

    for context in cases:
        with pytest.raises(PermissionError):
            retrieve_platform_connector_secret(db, context=context)


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
    assert settings.PLATFORM_API_TEST_PROJECTS_ENABLED is True
    assert settings.PLATFORM_API_LIVE_PROJECTS_ENABLED is False
    assert settings.PLATFORM_API_WEBHOOK_DELIVERY_ENABLED is False
    assert settings.PLATFORM_API_PUBLIC_DOCS_ENABLED is False
    assert settings.PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED is False
    assert settings.EARTHDAILY_ADAPTER_ENABLED is False
    assert settings.VALLEY_IRRIGATION_ADAPTER_ENABLED is False
    assert settings.VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED is False
