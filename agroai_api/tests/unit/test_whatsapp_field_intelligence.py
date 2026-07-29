from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime

import pytest

from app.core.config import settings
from app.core.security import create_access_token
from app.models.field_intelligence import FieldCaptureSession, FieldObservation
from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.models.whatsapp import (
    WhatsAppContactBinding,
    WhatsAppInboundEvent,
    WhatsAppOutboundMessage,
)
from app.services import field_intelligence as field_svc
from app.services import whatsapp_field_intelligence as wa_svc
from app.services.whatsapp_crypto import decrypt_wa_id, encrypt_wa_id, wa_id_hash


@pytest.fixture(autouse=True)
def whatsapp_runtime(monkeypatch):
    values = {
        "WHATSAPP_ENABLED": True,
        "WHATSAPP_APP_SECRET": "whatsapp-test-secret",
        "WHATSAPP_VERIFY_TOKEN": "whatsapp-verify-token",
        "WHATSAPP_GRAPH_API_VERSION": "v99.0",
        "WHATSAPP_SERVICE_WINDOW_HOURS": 24,
        "WHATSAPP_MAX_ATTEMPTS": 3,
    }
    originals = {name: getattr(settings, name, None) for name in values}
    for name, value in values.items():
        object.__setattr__(settings, name, value)
        monkeypatch.setenv(name, str(value).lower() if isinstance(value, bool) else str(value))
    yield
    for name, value in originals.items():
        object.__setattr__(settings, name, value)


def _setup(db, *, phone_number_id: str = "123456789", confirmation_mode: str = "silent"):
    user = User(
        id="wa-user",
        email="whatsapp@example.com",
        name="WhatsApp Operator",
        password_hash="test",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    org = Organization(
        id="wa-org",
        name="WhatsApp Farms",
        slug="wa-org",
        owner_user_id=user.id,
        plan="pro",
        subscription_status="active",
        verification_status="approved",
    )
    membership = OrganizationMembership(
        id="wa-membership",
        organization_id=org.id,
        user_id=user.id,
        role="owner",
        status="active",
    )
    workspace = Workspace(
        id="wa-workspace",
        organization_id=org.id,
        name="Field Operations",
        crop="Almonds",
        region="California",
        mode="live",
    )
    connection = ConnectorConnection(
        id="wa-connection",
        tenant_id=org.id,
        workspace_id=workspace.id,
        provider="whatsapp",
        display_name="WhatsApp Field Intelligence",
        status="active",
        mode="cloud_api",
        required_plan="professional",
        config_json={
            "phone_number_id": phone_number_id,
            "waba_id": "987654321",
            "confirmation_mode": confirmation_mode,
        },
    )
    db.add_all([user, org, membership, workspace, connection])
    db.commit()
    token = create_access_token({
        "sub": user.id,
        "tenant_id": org.id,
        "org_id": org.id,
        "role": "owner",
    })
    return user, org, workspace, connection, {"Authorization": f"Bearer {token}"}


def _payload(
    *,
    phone_number_id: str = "123456789",
    sender: str = "15551234567",
    message_id: str = "wamid.test-1",
    text: str = "Aphids found on the north edge of Block A.",
) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "987654321",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": phone_number_id},
                    "contacts": [{"wa_id": sender, "profile": {"name": "Sensitive Name"}}],
                    "messages": [{
                        "from": sender,
                        "id": message_id,
                        "timestamp": "1784779200",
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
            }],
        }],
    }


def _signed_post(client, payload: dict, *, secret: str = "whatsapp-test-secret"):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/v1/whatsapp/webhook",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"},
    )


def _authorize_binding(db, user: User, workspace: Workspace) -> WhatsAppContactBinding:
    binding = db.query(WhatsAppContactBinding).one()
    binding.user_id = user.id
    binding.workspace_id = workspace.id
    binding.status = "active"
    binding.consent_status = "granted"
    binding.consent_granted_at = datetime.utcnow()
    binding.context_json = {"field_name": "North Ranch", "block_name": "Block A", "crop": "Almonds"}
    db.commit()
    return binding


def test_webhook_challenge_requires_exact_verify_token(client):
    denied = client.get(
        "/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"},
    )
    assert denied.status_code == 403

    accepted = client.get(
        "/v1/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "whatsapp-verify-token",
            "hub.challenge": "42",
        },
    )
    assert accepted.status_code == 200
    assert accepted.text == "42"


def test_invalid_signature_rejected_before_payload_persistence(client, db):
    _setup(db)
    raw = json.dumps(_payload()).encode("utf-8")
    response = client.post(
        "/v1/whatsapp/webhook",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert response.status_code == 401
    assert db.query(WhatsAppInboundEvent).count() == 0
    assert db.query(WhatsAppContactBinding).count() == 0


def test_webhook_is_idempotent_and_never_persists_raw_sender_identity(client, db):
    _setup(db)
    first = _signed_post(client, _payload())
    second = _signed_post(client, _payload())

    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 1
    assert second.status_code == 200, second.text
    assert second.json()["duplicates"] == 1
    assert db.query(WhatsAppInboundEvent).count() == 1
    assert db.query(WhatsAppContactBinding).count() == 1

    event = db.query(WhatsAppInboundEvent).one()
    binding = db.query(WhatsAppContactBinding).one()
    assert "15551234567" not in json.dumps(event.redacted_payload_json)
    assert "Sensitive Name" not in json.dumps(event.redacted_payload_json)
    assert binding.masked_wa_id == "••••4567"
    assert binding.wa_id_hash == wa_id_hash("15551234567")
    assert "15551234567" not in binding.wa_id_ciphertext_b64


def test_duplicate_inside_multi_message_delivery_does_not_roll_back_unique_event(client, db):
    _setup(db)
    assert _signed_post(client, _payload(message_id="wamid.existing")).status_code == 200

    delivery = _payload(message_id="wamid.existing")
    messages = delivery["entry"][0]["changes"][0]["value"]["messages"]
    messages.append({
        "from": "15551234567",
        "id": "wamid.unique",
        "timestamp": "1784779201",
        "type": "text",
        "text": {"body": "A second independent observation."},
    })
    result = _signed_post(client, delivery)

    assert result.status_code == 200, result.text
    assert result.json()["accepted"] == 1
    assert result.json()["duplicates"] == 1
    assert db.query(WhatsAppInboundEvent).count() == 2


def test_unknown_sender_is_quarantined_and_cannot_create_field_evidence(client, db):
    _setup(db)
    assert _signed_post(client, _payload()).status_code == 200

    result = wa_svc.run_whatsapp_ingress_jobs(db)
    event = db.query(WhatsAppInboundEvent).one()

    assert result["processed"] == 1
    assert event.status == "quarantined"
    assert "authorized" in (event.last_error or "")
    assert db.query(FieldCaptureSession).count() == 0
    assert db.query(FieldObservation).count() == 0


def test_authorized_text_message_enters_canonical_field_intelligence_pipeline(client, db):
    user, _, workspace, _, _ = _setup(db)
    assert _signed_post(client, _payload()).status_code == 200
    _authorize_binding(db, user, workspace)

    ingress = wa_svc.run_whatsapp_ingress_jobs(db)
    event = db.query(WhatsAppInboundEvent).one()
    capture = db.get(FieldCaptureSession, event.capture_session_id)
    observation = db.get(FieldObservation, event.observation_id)

    assert ingress["processed"] == 1
    assert event.status == "completed"
    assert capture is not None
    assert observation is not None
    assert capture.metadata_json["surface"] == "whatsapp"
    assert capture.field_name == "North Ranch"
    assert capture.block_name == "Block A"
    assert capture.user_id == user.id
    assert observation.status == "staged"

    processed = field_svc.run_field_intelligence_jobs(db, limit=10, worker_id="test-fi-worker")
    db.refresh(observation)
    assert processed["processed"] == 1
    assert observation.status in {"completed", "needs_review"}
    assert observation.transcript == "Aphids found on the north edge of Block A."


def test_stop_revokes_consent_but_confirmation_can_still_be_sent(client, db, monkeypatch):
    user, _, workspace, _, _ = _setup(db, confirmation_mode="receipt")
    assert _signed_post(client, _payload(text="STOP", message_id="wamid.stop")).status_code == 200
    binding = _authorize_binding(db, user, workspace)
    monkeypatch.setattr(wa_svc, "send_text", lambda *args, **kwargs: "wamid.control-reply")

    ingress = wa_svc.run_whatsapp_ingress_jobs(db)
    db.refresh(binding)
    outbound = db.query(WhatsAppOutboundMessage).one()

    assert ingress["processed"] == 1
    assert binding.status == "disabled"
    assert binding.consent_status == "revoked"
    assert outbound.idempotency_key.startswith("wa-stop-")

    result = wa_svc.run_whatsapp_outbox(db)
    db.refresh(outbound)
    assert result["sent"] == 1
    assert outbound.status == "sent"
    assert outbound.meta_message_id == "wamid.control-reply"


def test_delivery_status_never_regresses_from_read_to_delivered(client, db):
    user, _, workspace, connection, _ = _setup(db)
    assert _signed_post(client, _payload()).status_code == 200
    binding = _authorize_binding(db, user, workspace)
    row = WhatsAppOutboundMessage(
        id="outbound-read",
        tenant_id=binding.tenant_id,
        workspace_id=binding.workspace_id,
        connector_connection_id=connection.id,
        contact_binding_id=binding.id,
        idempotency_key="outbound-read-idempotency",
        message_kind="text",
        body_text="Already read",
        meta_message_id="wamid.outbound-read",
        status="read",
        parameters_json=[],
    )
    db.add(row)
    db.commit()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "987654321", "changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": "123456789"},
            "statuses": [{
                "id": "wamid.outbound-read",
                "status": "delivered",
                "timestamp": "1784779300",
                "recipient_id": "15551234567",
            }],
        }}]}],
    }
    response = _signed_post(client, payload)
    db.refresh(row)
    assert response.status_code == 200
    assert row.status == "read"


def test_whatsapp_identifier_encryption_is_bound_to_tenant_and_binding():
    ciphertext, nonce, version = encrypt_wa_id(
        "15551234567", tenant_id="tenant-a", binding_id="binding-a"
    )
    assert decrypt_wa_id(
        ciphertext,
        nonce,
        tenant_id="tenant-a",
        binding_id="binding-a",
        key_version=version,
    ) == "15551234567"
    with pytest.raises(Exception):
        decrypt_wa_id(
            ciphertext,
            nonce,
            tenant_id="tenant-b",
            binding_id="binding-a",
            key_version=version,
        )
