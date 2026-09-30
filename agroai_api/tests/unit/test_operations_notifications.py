"""Customer support requests must reach the AGRO-AI operations inbox, safely."""
from datetime import datetime

import pytest

from app.models.saas import SaaSRequest, User


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    state = {"result": {"ok": True, "provider": "resend", "status_code": 200}}
    monkeypatch.setattr("app.services.operations_notifications.send_email", lambda **kw: sent.append(kw) or dict(state["result"]))
    return sent, state


def _login(client, db, email):
    client.post("/v1/auth/register", json={"email": email, "password": "strong-password", "name": "Ops User", "organization_name": "Ops Farms", "workspace_name": "Ops WS", "crop": "Almonds", "region": "California"})
    user = db.query(User).filter(User.email == email).first()
    user.email_verification_status, user.email_verified_at = "verified", datetime.utcnow()
    db.commit()
    token = client.post("/v1/auth/login", json={"email": email, "password": "strong-password"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_authenticated_support_ticket_is_emailed_to_operations_and_escaped(client, db, outbox):
    sent, _ = outbox
    headers = _login(client, db, "ops-ticket@example.com")
    response = client.post("/v1/support/ticket", headers=headers, json={"category": "support", "subject": "Pump <b>down</b>", "message": "<script>alert(1)</script> help"})
    assert response.status_code == 200
    row = db.get(SaaSRequest, response.json()["request_id"])
    assert row.notification_status == "emailed" and response.json()["notification_status"] == "emailed"
    assert len(sent) == 1 and sent[0]["to_email"] == "contact@agroai-pilot.com"
    assert "<script>" not in sent[0]["html_body"] and "&lt;script&gt;" in sent[0]["html_body"]
    assert row.id in sent[0]["text_body"] and "ops-ticket@example.com" in sent[0]["text_body"]


def test_provider_failure_keeps_request_and_records_status(client, db, outbox):
    sent, state = outbox
    state["result"] = {"ok": False, "provider": "resend", "reason": "provider_rejected: domain not verified"}
    headers = _login(client, db, "ops-fail@example.com")
    response = client.post("/v1/support/ticket", headers=headers, json={"category": "support", "subject": "Help", "message": "Need help"})
    assert response.status_code == 200 and response.json()["status"] == "received"
    row = db.get(SaaSRequest, response.json()["request_id"])
    assert row.message == "Need help" and row.notification_status.startswith("email_failed:provider_rejected")


def test_public_ticket_uses_same_safe_delivery(client, db, outbox):
    sent, state = outbox
    state["result"] = {"ok": False, "provider": "none", "reason": "email_provider_not_configured"}
    response = client.post("/v1/support/ticket-public", json={"subject": "Question", "message": "<img src=x onerror=alert(1)>", "email": "visitor@example.com"})
    assert response.status_code == 200
    assert response.json()["notification_status"] == "email_not_configured"
    assert "<img" not in sent[0]["html_body"]


def test_sales_contact_is_emailed_exactly_once(client, db, outbox):
    sent, _ = outbox
    response = client.post("/v1/sales/contact", json={"subject": "Team plan", "message": "Pricing follow-up", "email": "buyer@example.com", "source_page": "pricing"})
    assert response.status_code == 200
    assert response.json()["notification_status"] == "emailed"
    assert len(sent) == 1
