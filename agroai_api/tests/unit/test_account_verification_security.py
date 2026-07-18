from datetime import datetime

from app.core.config import settings
from app.models.saas import (
    Organization,
    OrganizationMembership,
    OrganizationVerificationProfile,
    SecurityAuditEvent,
    User,
)
from app.services.account_verification import VerificationInput, evaluate_organization
from app.services.identity_vault import decrypt_phone


STRONG_APPLICATION = {
    "email": "owner@valleyorchards.com",
    "password": "strong-password-2026",
    "name": "Jane Farmer",
    "organization_name": "Valley Orchards LLC",
    "organization_type": "farm_or_grower",
    "professional_role": "Farm operations manager",
    "phone_number": "+1 415 555 0199",
    "website_url": "https://valleyorchards.com",
    "professional_profile_url": "https://www.linkedin.com/in/jane-farmer",
    "country": "United States",
    "operating_region": "California Central Valley",
    "acres_or_sites": "2,500 acres across four farms",
    "primary_crops": "Almonds and pistachios",
    "intended_use": "We manage irrigated almond and pistachio fields and need AGRO-AI to connect field evidence, improve irrigation decisions, and produce operating reports.",
    "planned_data_sources": "WiseConn, John Deere, PDFs, spreadsheets, and weather records",
    "workspace_name": "Central Valley operations",
    "crop": "Almonds and pistachios",
    "region": "California Central Valley",
}


def _verification_input(**overrides):
    payload = {**STRONG_APPLICATION, **overrides}
    return VerificationInput(
        email=payload["email"],
        name=payload["name"],
        organization_name=payload["organization_name"],
        organization_type=payload["organization_type"],
        professional_role=payload["professional_role"],
        phone_number=payload["phone_number"],
        website_url=payload.get("website_url"),
        professional_profile_url=payload.get("professional_profile_url"),
        country=payload["country"],
        operating_region=payload["operating_region"],
        acres_or_sites=payload["acres_or_sites"],
        primary_crops=payload["primary_crops"],
        intended_use=payload["intended_use"],
        planned_data_sources=payload["planned_data_sources"],
    )


def test_consumer_email_is_accepted_with_strong_evidence():
    decision = evaluate_organization(_verification_input(email="jane.farmer@gmail.com"))
    assert decision.approved is True
    assert decision.domain_classification == "consumer"
    assert decision.status == "preapproved_pending_email"
    assert decision.score >= 82


def test_disposable_and_placeholder_applications_are_rejected():
    disposable = evaluate_organization(_verification_input(email="owner@mailinator.com"))
    placeholder = evaluate_organization(
        _verification_input(
            email="owner@gmail.com",
            organization_name="test",
            intended_use="just trying this for fun",
        )
    )
    assert disposable.approved is False
    assert "disposable_email_domain" in disposable.reason_codes
    assert placeholder.approved is False
    assert "unverifiable_organization_name" in placeholder.reason_codes


def test_strict_registration_encrypts_phone_and_waits_for_email(client, db, monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNT_VERIFICATION_MODE", "enforce")
    response = client.post("/v1/auth/register", json=STRONG_APPLICATION)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["organization_verification"]["status"] == "preapproved_pending_email"
    assert body["organization_verification"]["verification_id"]

    org = db.get(Organization, body["current_organization"]["id"])
    profile = db.query(OrganizationVerificationProfile).filter_by(organization_id=org.id).one()
    assert org.verification_status == "preapproved_pending_email"
    assert profile.phone_ciphertext_b64
    assert STRONG_APPLICATION["phone_number"] not in profile.phone_ciphertext_b64
    assert profile.phone_last4 == "0199"
    assert decrypt_phone(
        ciphertext_b64=profile.phone_ciphertext_b64,
        nonce_b64=profile.phone_nonce_b64,
        organization_id=org.id,
        profile_id=profile.id,
    ) == "+14155550199"

    membership = db.query(OrganizationMembership).filter_by(organization_id=org.id).one()
    assert membership.user.account_status == "pending_email"
    assert db.query(SecurityAuditEvent).filter_by(event_type="registration_verification", outcome="preapproved_pending_email").count() == 1


def test_strict_registration_rejects_weak_consumer_application_without_account(client, db, monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNT_VERIFICATION_MODE", "enforce")
    payload = {
        **STRONG_APPLICATION,
        "email": "casual-user@gmail.com",
        "organization_name": "test",
        "website_url": "",
        "professional_profile_url": "",
        "intended_use": "just curious",
    }
    response = client.post("/v1/auth/register", json=payload)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "organization_verification_rejected"
    assert db.query(User).filter_by(email="casual-user@gmail.com").first() is None
    event = db.query(SecurityAuditEvent).filter_by(event_type="registration_verification", outcome="rejected").one()
    assert event.subject_hash
    assert event.ip_hash
    assert "casual-user@gmail.com" not in str(event.metadata_json)


def test_login_lockout_and_server_side_organization_gate(client, db, monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNT_VERIFICATION_MODE", "disabled")
    monkeypatch.setattr(settings, "AUTH_MAX_FAILED_ATTEMPTS", 5)
    registration = client.post(
        "/v1/auth/register",
        json={
            "email": "lockout@example.com",
            "password": "strong-password",
            "name": "Lockout Owner",
            "organization_name": "Lockout Farms",
            "workspace_name": "Evaluation workspace",
            "crop": "Grapes",
            "region": "California",
        },
    )
    assert registration.status_code == 201, registration.text
    user = db.query(User).filter_by(email="lockout@example.com").one()
    user.email_verification_status = "verified"
    user.email_verified_at = datetime.utcnow()
    db.commit()

    for _ in range(5):
        failed = client.post("/v1/auth/login", json={"email": user.email, "password": "incorrect-password"})
        assert failed.status_code == 401

    locked = client.post("/v1/auth/login", json={"email": user.email, "password": "strong-password"})
    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "account_temporarily_locked"

    user.locked_until = None
    user.failed_login_attempts = 0
    db.commit()
    login = client.post("/v1/auth/login", json={"email": user.email, "password": "strong-password"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    membership = db.query(OrganizationMembership).filter_by(user_id=user.id).one()
    membership.organization.verification_status = "suspended"
    db.commit()
    blocked = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "organization_verification_required"
