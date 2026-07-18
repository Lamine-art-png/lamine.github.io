from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.platform_api import ServiceAccountCreate, create_service_account
from app.core.config import settings
from app.db.base import Base
from app.models.platform_api import (
    ApiProject,
    ApiServiceAccount,
    PlatformWebhookAuditEvent,
    PlatformWebhookDeliveryAttempt,
    PlatformWebhookEndpoint,
    PlatformWebhookOutbox,
)
from app.models.saas import Workspace
from app.platform_api.idempotency import begin_idempotent_operation, complete_idempotent_operation, request_hash
from app.platform_api.keys import create_platform_key, rotate_platform_key, verify_platform_key
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.webhook_delivery import _post_pinned, emit_webhook_event, process_webhook_delivery
from app.platform_api.webhooks import (
    audit_webhook_event,
    disable_webhook_endpoint,
    generate_webhook_secret,
    resolve_webhook_destination,
    revoke_webhook_endpoint,
    retrieve_webhook_secret_for_delivery,
    retrieve_webhook_secrets_for_delivery,
    rotate_webhook_secret,
    store_webhook_secret,
)
from tests.unit.test_platform_api_foundation import _org, _project_and_key


def _webhook_keyring() -> str:
    return json.dumps(
        {"wh-v1": base64.urlsafe_b64encode(b"w" * 32).decode("ascii").rstrip("=")}
    )


def _configure_platform(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")


def test_service_account_route_rejects_foreign_and_cross_project_workspaces(db):
    user, org, project_workspace, project, _service_account, _key, _plaintext = _project_and_key(db)
    _other_user, _other_org, foreign_workspace = _org(db)
    sibling_workspace = Workspace(organization_id=org.id, name="Sibling", mode="evaluation")
    db.add(sibling_workspace)
    db.commit()
    ctx = SimpleNamespace(organization=org, user=user)

    for workspace_id in (foreign_workspace.id, sibling_workspace.id):
        with pytest.raises(HTTPException) as exc:
            create_service_account(
                project.id,
                ServiceAccountCreate(
                    name=f"rejected-{workspace_id[:8]}",
                    scopes=["projects:read"],
                    workspace_id=workspace_id,
                ),
                ctx=ctx,
                db=db,
            )
        assert exc.value.status_code == 404

    created = create_service_account(
        project.id,
        ServiceAccountCreate(
            name="accepted",
            scopes=["projects:read"],
            workspace_id=project_workspace.id,
        ),
        ctx=ctx,
        db=db,
    )
    assert created["service_account"]["workspace_id"] == project_workspace.id


def test_key_lineage_rejects_corrupt_cross_organization_and_cross_project_records(db):
    _user, _org_row, _workspace, project, service_account, key, plaintext = _project_and_key(db)
    _other_user, _other_org, other_workspace, other_project, _other_sa, _other_key, _other_plaintext = _project_and_key(db)

    service_account.workspace_id = other_workspace.id
    db.commit()
    assert verify_platform_key(db, plaintext) is None

    service_account.workspace_id = project.workspace_id
    key.api_project_id = other_project.id
    db.commit()
    assert verify_platform_key(db, plaintext) is None


def test_cidr_allowlist_ipv4_ipv6_spoofing_and_fail_closed(client, db, monkeypatch):
    user, _org_row, _workspace, project, service_account, _key, _plaintext = _project_and_key(
        db,
        scopes=["projects:read"],
    )
    key, plaintext = create_platform_key(
        db,
        project=project,
        service_account=service_account,
        name="cidr-bound",
        scopes=["projects:read"],
        created_by_user_id=user.id,
        cidr_allowlist=["198.51.100.7/24", "2001:4860:4860::8888/32"],
    )
    db.commit()
    assert key.cidr_allowlist_json == ["198.51.100.0/24", "2001:4860::/32"]
    _configure_platform(monkeypatch)
    monkeypatch.setattr(settings, "PLATFORM_API_EDGE_AUTH_SECRET", "edge-secret")

    permitted_v4 = client.get(
        "/v1/platform/me",
        headers={
            "authorization": f"Bearer {plaintext}",
            "x-agroai-edge-auth": "edge-secret",
            "x-agroai-edge-client-ip": "198.51.100.42",
        },
    )
    permitted_v6 = client.get(
        "/v1/platform/me",
        headers={
            "authorization": f"Bearer {plaintext}",
            "x-agroai-edge-auth": "edge-secret",
            "x-agroai-edge-client-ip": "2001:4860:4860::8844",
        },
    )
    denied = client.get(
        "/v1/platform/me",
        headers={
            "authorization": f"Bearer {plaintext}",
            "x-agroai-edge-auth": "edge-secret",
            "x-agroai-edge-client-ip": "8.8.8.8",
        },
    )
    spoofed = client.get(
        "/v1/platform/me",
        headers={
            "authorization": f"Bearer {plaintext}",
            "x-forwarded-for": "198.51.100.42",
        },
    )
    missing_proxy = client.get("/v1/platform/me", headers={"authorization": f"Bearer {plaintext}"})

    assert permitted_v4.status_code == 200
    assert permitted_v6.status_code == 200
    assert denied.status_code == spoofed.status_code == missing_proxy.status_code == 401
    assert denied.json()["code"] == "client_ip_not_allowed"


def test_malformed_cidr_is_rejected_before_key_creation(db):
    user, _org_row, _workspace, project, service_account, _key, _plaintext = _project_and_key(db)
    with pytest.raises(ValueError, match="invalid CIDR"):
        create_platform_key(
            db,
            project=project,
            service_account=service_account,
            name="bad-cidr",
            scopes=["projects:read"],
            created_by_user_id=user.id,
            cidr_allowlist=["999.1.1.1/33"],
        )


@pytest.mark.parametrize("invalid_state", ["revoked", "expired", "disabled", "overlap", "project", "service_account"])
def test_invalid_key_lifecycle_cannot_rotate(db, invalid_state):
    user, _org_row, _workspace, project, service_account, key, _plaintext = _project_and_key(db)
    if invalid_state == "revoked":
        key.status = "revoked"
        key.revoked_at = datetime.utcnow()
    elif invalid_state == "expired":
        key.expires_at = datetime.utcnow() - timedelta(seconds=1)
    elif invalid_state == "disabled":
        key.status = "disabled"
    elif invalid_state == "overlap":
        key.overlap_expires_at = datetime.utcnow() + timedelta(minutes=5)
    elif invalid_state == "project":
        project.status = "disabled"
    else:
        service_account.status = "disabled"
    db.commit()

    with pytest.raises(ValueError):
        rotate_platform_key(db, old_key=key, overlap_minutes=5, rotated_by_user_id=user.id)
    assert (
        db.query(type(key))
        .filter(type(key).rotate_after_key_id == key.id)
        .count()
        == 0
    )


def test_idempotency_in_progress_conflict_expiry_and_scoped_hash(db):
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id="org-atomic",
        api_project_id="project-atomic",
        request_id="req-a",
    )
    row, replay = begin_idempotent_operation(
        db,
        principal=principal,
        operation="physical-operation",
        idempotency_key="same-key",
        payload={"resource": "field-1"},
    )
    assert replay is False
    db.commit()
    with pytest.raises(HTTPException) as exc:
        begin_idempotent_operation(
            db,
            principal=principal,
            operation="physical-operation",
            idempotency_key="same-key",
            payload={"resource": "field-1"},
        )
    assert exc.value.detail["code"] == "operation_in_progress"

    original_digest = row.request_hash
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    reclaimed, replay = begin_idempotent_operation(
        db,
        principal=principal,
        operation="physical-operation",
        idempotency_key="same-key",
        payload={"resource": "field-2"},
    )
    assert replay is False
    assert reclaimed.id == row.id
    assert reclaimed.request_hash != original_digest
    assert request_hash({"same": True}, scope="org-a|project-a|operation") != request_hash(
        {"same": True},
        scope="org-b|project-a|operation",
    )
    assert request_hash({"same": True}, scope="org-a|project-a|operation") != request_hash(
        {"same": True},
        scope="org-a|project-b|operation",
    )


def test_two_independent_sessions_execute_identical_idempotent_operation_once(tmp_path):
    database = tmp_path / "idempotency-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    barrier = threading.Barrier(2)
    executions = 0
    lock = threading.Lock()

    def run(request_id: str) -> str:
        nonlocal executions
        db = Session()
        principal = PlatformPrincipal(
            authentication_type="platform_api_key",
            organization_id="org-concurrent",
            api_project_id="project-concurrent",
            request_id=request_id,
        )
        try:
            barrier.wait()
            try:
                row, replay = begin_idempotent_operation(
                    db,
                    principal=principal,
                    operation="provider-write",
                    idempotency_key="concurrent-key",
                    payload={"same": True},
                )
            except HTTPException as exc:
                return exc.detail["code"]
            if replay:
                return "replayed"
            with lock:
                executions += 1
            time.sleep(0.1)
            complete_idempotent_operation(row, response_status=200, response_json={"ok": True})
            db.commit()
            return "executed"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ("req-1", "req-2")))
    assert executions == 1
    assert sorted(results) == ["executed", "replayed"]
    engine.dispose()


def _create_encrypted_endpoint(db, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_SECRET_KEYS_JSON", _webhook_keyring())
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_SECRET_ACTIVE_KEY_VERSION", "wh-v1")
    _user, org, _workspace, project, _service_account, _key, _plaintext = _project_and_key(db)
    plaintext, digest, prefix = generate_webhook_secret()
    endpoint = PlatformWebhookEndpoint(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        api_project_id=project.id,
        url="https://hooks.example.com/agroai",
        subscribed_event_types=["action.approval_required"],
        status="active",
        signing_secret_hash=digest,
        signing_secret_prefix=prefix,
        signing_secret_version="v1",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    store_webhook_secret(endpoint, plaintext)
    db.add(endpoint)
    audit_webhook_event(
        db,
        endpoint=endpoint,
        action="created",
        actor_type="portal_user",
        actor_id="user-1",
    )
    db.commit()
    return org, project, endpoint, plaintext


def test_webhook_secret_encryption_retrieval_rotation_revocation_and_audit(db, monkeypatch, caplog):
    org, project, endpoint, plaintext = _create_encrypted_endpoint(db, monkeypatch)
    assert plaintext not in endpoint.signing_secret_ciphertext_b64
    assert endpoint.signing_secret_key_version == "wh-v1"

    loaded = retrieve_webhook_secret_for_delivery(
        db,
        endpoint_id=endpoint.id,
        organization_id=org.id,
        api_project_id=project.id,
        worker_id="worker-1",
    )
    assert loaded == plaintext
    replacement = rotate_webhook_secret(
        db,
        endpoint=endpoint,
        actor_id="user-1",
        overlap_minutes=5,
    )
    db.commit()
    assert replacement != plaintext
    assert endpoint.previous_secret_ciphertext_b64
    assert endpoint.previous_secret_expires_at > datetime.utcnow()
    assert retrieve_webhook_secrets_for_delivery(
        db,
        endpoint_id=endpoint.id,
        organization_id=org.id,
        api_project_id=project.id,
        worker_id="worker-overlap",
    ) == [replacement, plaintext]
    disable_webhook_endpoint(db, endpoint=endpoint, actor_id="user-1")
    db.commit()
    with pytest.raises(PermissionError):
        retrieve_webhook_secret_for_delivery(
            db,
            endpoint_id=endpoint.id,
            organization_id=org.id,
            api_project_id=project.id,
            worker_id="worker-2",
        )
    actions = {
        action
        for (action,) in db.query(PlatformWebhookAuditEvent.action)
        .filter(PlatformWebhookAuditEvent.endpoint_id == endpoint.id)
        .all()
    }
    assert {"created", "secret_retrieved", "secret_rotated", "disabled"}.issubset(actions)
    assert plaintext not in caplog.text
    assert replacement not in caplog.text

    _org2, _project2, revoked_endpoint, _secret2 = _create_encrypted_endpoint(db, monkeypatch)
    revoke_webhook_endpoint(db, endpoint=revoked_endpoint, actor_id="user-1")
    db.commit()
    assert (
        db.query(PlatformWebhookAuditEvent)
        .filter(
            PlatformWebhookAuditEvent.endpoint_id == revoked_endpoint.id,
            PlatformWebhookAuditEvent.action == "revoked",
        )
        .count()
        == 1
    )


def test_webhook_vault_rejects_api_key_pepper_reuse(monkeypatch):
    reused = b"p" * 32
    monkeypatch.setattr(settings, "PLATFORM_API_KEY_PEPPER", reused.decode("ascii"))
    monkeypatch.setattr(
        settings,
        "PLATFORM_API_WEBHOOK_SECRET_KEYS_JSON",
        json.dumps({"wh-v1": base64.urlsafe_b64encode(reused).decode("ascii").rstrip("=")}),
    )
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_SECRET_ACTIVE_KEY_VERSION", "wh-v1")
    with pytest.raises(RuntimeError, match="must not reuse"):
        from app.platform_api.webhooks import webhook_secret_keyring

        webhook_secret_keyring()


def test_webhook_delivery_is_signed_pinned_bounded_and_idempotent(db, monkeypatch):
    org, project, endpoint, _plaintext = _create_encrypted_endpoint(db, monkeypatch)
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_MAX_RESPONSE_BYTES", 16)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    event = emit_webhook_event(
        db,
        organization_id=org.id,
        api_project_id=project.id,
        event_type="action.approval_required",
        payload={"resource_id": "field-1"},
    )
    db.commit()
    outbox = db.query(PlatformWebhookOutbox).filter_by(event_id=event.id, endpoint_id=endpoint.id).one()
    outbox.status = "queued"
    db.commit()
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["host"] = request.headers["host"]
        observed["signature"] = request.headers["x-agroai-webhook-signature"]
        observed["timestamp"] = request.headers["x-agroai-webhook-timestamp"]
        observed["event_id"] = request.headers["x-agroai-event-id"]
        return httpx.Response(200, content=b"x" * 100)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = process_webhook_delivery(
        db,
        outbox_id=outbox.id,
        organization_id=org.id,
        worker_id="worker-delivery",
        client=client,
    )
    duplicate = process_webhook_delivery(
        db,
        outbox_id=outbox.id,
        organization_id=org.id,
        worker_id="worker-delivery",
        client=client,
    )
    client.close()

    assert result == "succeeded"
    assert duplicate == "delivered"
    assert observed["url"].startswith("https://93.184.216.34/")
    assert observed["host"] == "hooks.example.com"
    assert observed["signature"].startswith("v1=")
    assert observed["timestamp"].isdigit()
    assert observed["event_id"] == event.id
    attempt = db.query(PlatformWebhookDeliveryAttempt).filter_by(event_id=event.id, endpoint_id=endpoint.id).one()
    assert attempt.response_excerpt == "x" * 16
    assert db.query(PlatformWebhookDeliveryAttempt).filter_by(event_id=event.id, endpoint_id=endpoint.id).count() == 1


def test_webhook_delivery_disabled_never_calls_network(db, monkeypatch):
    org, project, endpoint, _plaintext = _create_encrypted_endpoint(db, monkeypatch)
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED", False)
    event = emit_webhook_event(
        db,
        organization_id=org.id,
        api_project_id=project.id,
        event_type="action.approval_required",
        payload={},
    )
    db.commit()
    outbox = db.query(PlatformWebhookOutbox).filter_by(event_id=event.id).one()
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert process_webhook_delivery(
        db,
        outbox_id=outbox.id,
        organization_id=org.id,
        worker_id="worker-disabled",
        client=client,
    ) == "disabled"
    client.close()
    assert calls == 0


def test_webhook_delivery_exponential_retry_reaches_final_failure(db, monkeypatch):
    org, project, endpoint, _plaintext = _create_encrypted_endpoint(db, monkeypatch)
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    event = emit_webhook_event(
        db,
        organization_id=org.id,
        api_project_id=project.id,
        event_type="action.approval_required",
        payload={},
    )
    db.commit()
    outbox = db.query(PlatformWebhookOutbox).filter_by(event_id=event.id).one()
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(503, text="retry")))

    outbox.status = "queued"
    db.commit()
    assert process_webhook_delivery(
        db,
        outbox_id=outbox.id,
        organization_id=org.id,
        worker_id="retry-worker",
        client=client,
    ) == "retrying"
    db.refresh(outbox)
    assert outbox.next_attempt_at > datetime.utcnow()
    outbox.status = "queued"
    db.commit()
    assert process_webhook_delivery(
        db,
        outbox_id=outbox.id,
        organization_id=org.id,
        worker_id="retry-worker",
        client=client,
    ) == "failed"
    client.close()
    assert db.query(PlatformWebhookDeliveryAttempt).filter_by(event_id=event.id).count() == 2
    db.refresh(outbox)
    assert outbox.status == "failed"
    assert outbox.next_attempt_at is None


def test_webhook_redirect_is_revalidated_and_private_target_is_denied(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(307, headers={"location": "https://127.0.0.1/metadata"})
        )
    )
    with pytest.raises(ValueError, match="prohibited"):
        _post_pinned(
            "https://hooks.example.com/callback",
            body=b"{}",
            headers={"content-type": "application/json"},
            client=client,
        )
    client.close()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "::",
    ],
)
def test_webhook_ssrf_rejects_prohibited_ipv4_and_ipv6(address):
    with pytest.raises(ValueError, match="prohibited"):
        resolve_webhook_destination(
            "https://hooks.example.com/callback",
            resolver=lambda *args, **kwargs: [(None, None, None, None, (address, 443))],
        )


def test_webhook_ssrf_rejects_unsafe_schemes_credentials_ports_and_dns_failure():
    cases = (
        "http://hooks.example.com",
        "https://user:pass@hooks.example.com",
        "https://hooks.example.com:22",
        "https://localhost/hook",
    )
    for url in cases:
        with pytest.raises(ValueError):
            resolve_webhook_destination(url, resolver=lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match="did not resolve"):
        resolve_webhook_destination("https://hooks.example.com", resolver=lambda *args, **kwargs: [])


def test_provider_and_resource_restrictions_are_enforced_on_operations(client, db, monkeypatch):
    user, _org_row, _workspace, project, service_account, _key, _plaintext = _project_and_key(
        db,
        scopes=["connectors:read", "connectors:write", "actions:plan"],
    )
    key, plaintext = create_platform_key(
        db,
        project=project,
        service_account=service_account,
        name="restricted-operations",
        scopes=["connectors:read", "connectors:write", "actions:plan"],
        created_by_user_id=user.id,
        provider_restrictions={"allow": ["earthdaily"]},
        resource_restrictions={"resource_ids": ["field-1"]},
    )
    db.commit()
    _configure_platform(monkeypatch)

    catalog = client.get("/v1/platform/providers", headers={"authorization": f"Bearer {plaintext}"})
    denied_provider = client.post(
        "/v1/platform/providers/valley_irrigation/validate-credentials",
        headers={"authorization": f"Bearer {plaintext}", "idempotency-key": "provider-denied"},
        json={"provider_id": "valley_irrigation", "credentials": {}},
    )
    denied_resource = client.post(
        "/v1/platform/actions/plan",
        headers={"authorization": f"Bearer {plaintext}", "idempotency-key": "resource-denied"},
        json={"action_type": "inspect", "provider_id": "earthdaily", "resource_id": "field-2"},
    )
    missing_idempotency = client.post(
        "/v1/platform/actions/plan",
        headers={"authorization": f"Bearer {plaintext}"},
        json={"action_type": "inspect", "provider_id": "earthdaily", "resource_id": "field-1"},
    )
    allowed = client.post(
        "/v1/platform/actions/plan",
        headers={"authorization": f"Bearer {plaintext}", "idempotency-key": "resource-allowed"},
        json={"action_type": "inspect", "provider_id": "earthdaily", "resource_id": "field-1"},
    )

    assert catalog.status_code == 200
    assert {provider["provider_id"] for provider in catalog.json()["providers"]} == {"earthdaily"}
    assert denied_provider.status_code == 403
    assert denied_provider.json()["code"] == "provider_restricted"
    assert denied_resource.status_code == 403
    assert denied_resource.json()["code"] == "resource_restricted"
    assert missing_idempotency.status_code == 422
    assert allowed.status_code == 200


def test_public_openapi_has_security_schemas_errors_headers_and_truthful_semantics(client, db, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", True)
    openapi_response = client.get("/v1/platform/openapi.json")
    document = openapi_response.json()
    assert openapi_response.headers["X-Request-Id"].startswith("req_")
    assert document["components"]["securitySchemes"]["PlatformApiKey"]["scheme"] == "bearer"
    assert document["servers"] == [{"url": "/v1", "description": "Platform API v1 base path"}]
    assert "StandardError" in document["components"]["schemas"]
    operation = document["paths"]["/platform/actions/plan"]["post"]
    assert operation["security"] == [{"PlatformApiKey": []}]
    assert any(item["name"] == "Idempotency-Key" for item in operation["parameters"])
    assert "requestBody" in operation
    assert "RateLimit-Limit" in operation["responses"]["200"]["headers"]
    assert "200" not in document["paths"]["/platform/actions/execute"]["post"]["responses"]
    assert document["x-agroai-provider-readiness"]["earthdaily"] == "awaiting_partner_contract"
    assert "physical writes disabled" in document["x-agroai-provider-readiness"]["valley_irrigation"]
    rendered = json.dumps(document)
    assert "/internal/" not in rendered
    assert "/platform/developer/" not in rendered

    *_items, plaintext = _project_and_key(db, scopes=["actions:plan"])
    _configure_platform(monkeypatch)
    malformed = client.post(
        "/v1/platform/actions/plan",
        headers={"authorization": f"Bearer {plaintext}"},
        json={"action_type": {"unexpected": "customer-secret-value"}},
    )
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "invalid_request"
    assert "customer-secret-value" not in malformed.text
