import hashlib
import hmac
import json
import time

from app.core.config import settings
from app.core.security import verify_token
from app.models.saas import BillingEvent, Organization, OrganizationMembership, UsageEvent


def _register(client, email="owner@example.com", org="Owner Farms"):
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "strong-password",
            "name": "Owner",
            "organization_name": org,
            "workspace_name": "Evaluation workspace",
            "crop": "Grapes",
            "region": "California",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


def _stripe_signature(payload: bytes, secret: str) -> str:
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def test_register_login_me_creates_default_org_and_workspace(client):
    body, headers = _register(client)
    assert body["current_organization"]["role"] == "owner"
    assert body["entitlements"]["max_workspaces"] == 1

    me = client.get("/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "owner@example.com"

    login = client.post("/v1/auth/login", json={"email": "owner@example.com", "password": "strong-password"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert verify_token(token)["sub"] == body["user"]["id"]

    workspaces = client.get("/v1/workspaces", headers=headers)
    assert workspaces.status_code == 200
    assert len(workspaces.json()["workspaces"]) == 1
    assert workspaces.json()["workspaces"][0]["mode"] == "evaluation"


def test_tenant_isolation_hides_other_org_workspace(client):
    one, headers_one = _register(client, "one@example.com", "One Farms")
    two, headers_two = _register(client, "two@example.com", "Two Farms")
    org_one = one["current_organization"]["id"]
    workspace_one = client.get("/v1/workspaces", headers=headers_one).json()["workspaces"][0]["id"]

    assert client.post(f"/v1/orgs/{org_one}/switch", headers=headers_two).status_code == 404
    assert client.get(f"/v1/workspaces/{workspace_one}/assurance/overview", headers=headers_two).status_code == 404
    assert two["current_organization"]["id"] != org_one


def test_tenant_isolation_hides_workspace_subroutes_and_billing(client):
    one, headers_one = _register(client, "route-one@example.com", "Route One Farms")
    _two, headers_two = _register(client, "route-two@example.com", "Route Two Farms")
    org_one = one["current_organization"]["id"]
    workspace_one = client.get("/v1/workspaces", headers=headers_one).json()["workspaces"][0]["id"]

    blocked = [
        ("GET", f"/v1/workspaces/{workspace_one}/assurance/overview"),
        ("GET", f"/v1/workspaces/{workspace_one}/evidence"),
        ("POST", f"/v1/workspaces/{workspace_one}/evidence"),
        ("POST", f"/v1/workspaces/{workspace_one}/agents/run"),
        ("GET", f"/v1/workspaces/{workspace_one}/agents/runs"),
        ("GET", f"/v1/workspaces/{workspace_one}/reports"),
        ("POST", f"/v1/workspaces/{workspace_one}/reports/export"),
        ("POST", f"/v1/workspaces/{workspace_one}/assurance/passports"),
    ]
    for method, path in blocked:
        response = client.request(method, path, headers=headers_two)
        assert response.status_code == 404, path

    billing = client.get(f"/v1/billing/status?organization_id={org_one}", headers=headers_two)
    assert billing.status_code == 404


def test_free_plan_workspace_live_and_export_gates(client):
    body, headers = _register(client)
    org_id = body["current_organization"]["id"]
    extra = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"organization_id": org_id, "name": "Second workspace", "mode": "evaluation"},
    )
    assert extra.status_code == 403
    assert extra.json()["detail"]["code"] == "limit_reached"

    live = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"organization_id": org_id, "name": "Live workspace", "mode": "live"},
    )
    assert live.status_code == 403

    workspace_id = client.get("/v1/workspaces", headers=headers).json()["workspaces"][0]["id"]
    export = client.post(f"/v1/workspaces/{workspace_id}/reports/export", headers=headers)
    assert export.status_code == 402
    assert export.json()["detail"]["code"] == "plan_required"


def test_paid_entitlements_unlock_live_workspace_and_agent_usage(client, db):
    body, headers = _register(client)
    org_id = body["current_organization"]["id"]
    org = db.get(Organization, org_id)
    org.plan = "pro"
    org.subscription_status = "active"
    db.commit()

    created = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"organization_id": org_id, "name": "Live pistachio block", "mode": "live"},
    )
    assert created.status_code == 201, created.text
    workspace_id = created.json()["workspace"]["id"]
    run = client.post(f"/v1/workspaces/{workspace_id}/agents/run", headers=headers)
    assert run.status_code == 200
    evidence = client.post(f"/v1/workspaces/{workspace_id}/evidence", headers=headers)
    assert evidence.status_code == 200
    export = client.post(f"/v1/workspaces/{workspace_id}/reports/export", headers=headers)
    assert export.status_code == 200
    assert db.query(UsageEvent).filter(UsageEvent.event_type == "agent_run").count() == 1


def test_evidence_and_agent_run_gated_by_free_plan(client):
    _body, headers = _register(client)
    workspace_id = client.get("/v1/workspaces", headers=headers).json()["workspaces"][0]["id"]

    upload = client.post(f"/v1/workspaces/{workspace_id}/evidence", headers=headers)
    assert upload.status_code == 402
    assert upload.json()["detail"]["code"] == "plan_required"

    agent = client.post(f"/v1/workspaces/{workspace_id}/agents/run", headers=headers)
    assert agent.status_code == 402
    assert agent.json()["detail"]["code"] == "plan_required"


def test_checkout_and_portal_require_owner_or_admin_and_safe_missing_stripe(client, db):
    owner, owner_headers = _register(client, "owner-billing@example.com", "Billing Farms")
    other, other_headers = _register(client, "other-billing@example.com", "Other Billing Farms")
    org_id = owner["current_organization"]["id"]

    hidden = client.post("/v1/billing/create-checkout-session", headers=other_headers, json={"organization_id": org_id, "plan": "pilot"})
    assert hidden.status_code == 404

    db.add(OrganizationMembership(organization_id=org_id, user_id=other["user"]["id"], role="operator"))
    db.commit()

    forbidden = client.post("/v1/billing/create-checkout-session", headers=other_headers, json={"organization_id": org_id, "plan": "pilot"})
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "owner_or_admin_required"

    missing = client.post("/v1/billing/create-checkout-session", headers=owner_headers, json={"organization_id": org_id, "plan": "pilot"})
    assert missing.status_code in {422, 503}

    org = db.get(Organization, org_id)
    org.stripe_customer_id = "cus_test"
    db.commit()
    portal_forbidden = client.post("/v1/billing/create-portal-session", headers=other_headers, json={"organization_id": org_id})
    assert portal_forbidden.status_code == 403
    assert portal_forbidden.json()["detail"]["code"] == "owner_or_admin_required"


def test_billing_status_returns_entitlements(client):
    body, headers = _register(client)
    org_id = body["current_organization"]["id"]
    status = client.get(f"/v1/billing/status?organization_id={org_id}", headers=headers)
    assert status.status_code == 200
    assert status.json()["entitlements"]["plan"] == "free"


def test_stripe_webhook_idempotency_updates_subscription(client, db, monkeypatch):
    body, _headers = _register(client)
    org_id = body["current_organization"]["id"]
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO", "price_pro")
    event = {
        "id": "evt_123",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "metadata": {"organization_id": org_id},
                "status": "active",
                "current_period_end": 1_820_000_000,
                "items": {"data": [{"price": {"id": "price_pro"}}]},
            }
        },
    }
    raw = json.dumps(event).encode()
    headers = {"Stripe-Signature": _stripe_signature(raw, settings.STRIPE_WEBHOOK_SECRET)}

    first = client.post("/v1/billing/webhook", content=raw, headers=headers)
    second = client.post("/v1/billing/webhook", content=raw, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    assert db.query(BillingEvent).filter(BillingEvent.stripe_event_id == "evt_123").count() == 1
    org = db.get(Organization, org_id)
    assert org.plan == "pro"
    assert org.subscription_status == "active"
    assert org.stripe_subscription_id == "sub_123"


def test_stripe_webhook_rejects_invalid_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    event = {"id": "evt_bad_sig", "object": "event", "type": "invoice.payment_failed", "data": {"object": {}}}
    raw = json.dumps(event).encode()
    response = client.post("/v1/billing/webhook", content=raw, headers={"Stripe-Signature": "t=1,v1=bad"})
    assert response.status_code == 400
