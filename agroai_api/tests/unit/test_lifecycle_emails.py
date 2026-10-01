"""Lifecycle onboarding email: enrollment, event-aware sequencing, localization,
preferences, idempotency and failure handling."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.lifecycle_email import LifecycleEmailEnrollment, LifecycleEmailSend
from app.models.operational_records import DataSource
from app.models.saas import Organization, OrganizationMembership, UsageEvent, User, UserPreference
from app.services import lifecycle_email_i18n, lifecycle_emails
from app.services.email_delivery import send_email as _real_send_email
from app.services.email_verification import create_verification_token

PASSWORD = "Harvest-Ledger-Pump-2026"
ADDRESS = "AGRO-AI Inc., 100 Test Road, Davis, CA 95616, USA"


class _NoClose:
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


@pytest.fixture()
def lc(monkeypatch, db, tmp_path):
    monkeypatch.setattr(settings, "LIFECYCLE_EMAILS_ENABLED", True)
    monkeypatch.setattr(settings, "LIFECYCLE_EMAIL_POSTAL_ADDRESS", ADDRESS)
    monkeypatch.setattr(lifecycle_emails, "_session_factory", lambda: _NoClose(db))
    sent: list[dict] = []
    state = {"result": {"ok": True, "provider": "resend", "status_code": 200, "provider_response": '{"id":"msg-1"}'}, "translator_calls": []}

    def sender(**kwargs):
        sent.append(kwargs)
        return dict(state["result"])

    async def translator(locale, chunk):
        state["translator_calls"].append(locale)
        if state.get("translator_down"):
            raise RuntimeError("provider unavailable")
        return {key: f"[{locale}] {value}" for key, value in chunk.items()}

    monkeypatch.setattr("app.services.email_delivery.send_email", sender)
    monkeypatch.setattr(lifecycle_email_i18n, "_translate_chunk", translator)
    monkeypatch.setattr(lifecycle_email_i18n, "CATALOG_DIR", tmp_path / "catalogs")
    lifecycle_email_i18n._RUNTIME_CACHE.clear()
    lifecycle_email_i18n._static_catalog.cache_clear()
    yield SimpleNamespace(sent=sent, state=state, catalogs=tmp_path / "catalogs")
    lifecycle_email_i18n._static_catalog.cache_clear()
    lifecycle_email_i18n._RUNTIME_CACHE.clear()


def _signup(client, db, email, *, locale="en", name="Maria Silva", verify=True):
    response = client.post("/v1/auth/register", json={
        "email": email, "password": PASSWORD, "name": name, "organization_name": f"{name} Farms",
        "workspace_name": "Main", "crop": "Almonds", "region": "California", "locale": locale,
    })
    assert response.status_code == 201, response.text
    user = db.query(User).filter_by(email=email).one()
    if verify:
        token = create_verification_token(db, user)
        db.commit()
        confirmed = client.post("/v1/auth/email-verification/confirm", json={"token": token})
        assert confirmed.status_code == 200, confirmed.text
    db.refresh(user)
    org = db.query(OrganizationMembership).filter_by(user_id=user.id).one().organization
    return user, org


def _run(db, user, *, days, hours=1):
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    return lifecycle_emails.process_enrollment(db, enrollment, now=enrollment.enrolled_at + timedelta(days=days, hours=hours))


def _steps(lc):
    return [message["tags"][1]["value"] for message in lc.sent]


def _row(db, user, step):
    return db.query(LifecycleEmailSend).filter_by(user_id=user.id, step=step).one_or_none()


def test_new_free_customer_is_enrolled_on_verification_and_welcomed(client, db, lc):
    user, org = _signup(client, db, "welcome@example.com")
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    assert enrollment.source == "email_verified" and enrollment.status == "active"
    assert _steps(lc) == ["welcome"]
    message = lc.sent[0]
    assert message["to_email"] == "welcome@example.com" and message["subject"] == "Welcome to AGRO-AI"
    assert message["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "/v1/email/lifecycle/unsubscribe?u=" in message["headers"]["List-Unsubscribe"]
    assert ADDRESS in message["html_body"] and ADDRESS in message["text_body"]
    assert "/onboarding?lang=en" in message["html_body"] and "Maria Silva Farms" in message["html_body"]
    row = _row(db, user, "welcome")
    assert (row.status, row.locale, row.plan_at_send, row.provider_message_id) == ("sent", "en", "free", "msg-1")


def test_unverified_accounts_are_not_enrolled(client, db, lc):
    user, _ = _signup(client, db, "unverified@example.com", verify=False)
    assert db.get(LifecycleEmailEnrollment, user.id) is None and lc.sent == []


def test_completed_actions_suppress_reminders(client, db, lc):
    user, org = _signup(client, db, "events@example.com")
    org.plan, org.subscription_status = "professional", "active"
    db.add(DataSource(tenant_id=org.id, provider="manual_csv", source_type="upload", filename="irrigation.csv"))
    db.commit()
    assert _run(db, user, days=1) == "waiting"  # connect_data skipped, ask not due yet
    assert _row(db, user, "connect_data").reason == "already_connected_data"
    assert _run(db, user, days=3) == "sent"
    assert _steps(lc) == ["welcome", "ask"] and _row(db, user, "ask").variant == "with_data"
    assert "Answers draw on the records you have connected" in lc.sent[-1]["text_body"]


def test_free_customer_full_sequence_and_conversion_uses_real_plan_numbers(client, db, lc):
    user, org = _signup(client, db, "free@example.com")
    for day in (1, 3, 5, 7, 10, 12, 14):
        _run(db, user, days=day)
    # Ask AGRO-AI is not part of Free: no email invites a Free customer to it.
    assert _steps(lc) == ["welcome", "connect_data", "field", "market", "connectors", "plans"]
    assert _row(db, user, "ask").reason == "not_in_plan"
    assert _row(db, user, "team").reason == "plan_without_team_invites"
    plans = lc.sent[-1]
    assert "Ask AGRO-AI: 500 questions a month" in plans["text_body"]
    assert "500 evidence uploads a month instead of 15" in plans["text_body"]
    assert "has used" not in plans["text_body"]  # no usage claim without real usage
    assert "Live connections are included from the Professional plan" in lc.sent[4]["text_body"]


def test_upgrade_messaging_only_reflects_real_usage(client, db, lc):
    user, org = _signup(client, db, "usage@example.com")
    now = datetime.utcnow()
    db.add(UsageEvent(organization_id=org.id, user_id=user.id, event_type="evidence_upload", metric="evidence_upload", quantity=13, state="committed", created_at=now))
    db.commit()
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    enrollment.enrolled_at = now - timedelta(days=14, hours=1)
    for step in ("connect_data", "ask", "field", "market", "connectors", "team"):
        db.add(LifecycleEmailSend(user_id=user.id, organization_id=org.id, step=step, status="skipped", reason="test", scheduled_for=now))
    enrollment.last_sent_at = None
    db.commit()
    assert lifecycle_emails.process_enrollment(db, enrollment, now=now) == "sent"
    assert _row(db, user, "plans").variant == "usage"
    assert "has used 13 of its 15 evidence uploads" in lc.sent[-1]["text_body"]


def test_paid_customer_never_gets_free_upgrade_email(client, db, lc):
    user, org = _signup(client, db, "paid@example.com")
    org.plan, org.subscription_status = "team", "active"
    db.commit()
    for day in (1, 3, 5, 7, 10, 12, 14):
        _run(db, user, days=day)
    assert "plans" not in _steps(lc) and _row(db, user, "plans").reason == "paid_plan"
    assert "team" in _steps(lc)  # Team plan includes invitations
    connectors = next(m for m in lc.sent if m["tags"][1]["value"] == "connectors")
    assert "Your plan includes live connections" in connectors["text_body"]


def test_customer_who_upgrades_midway_stops_conversion(client, db, lc):
    user, org = _signup(client, db, "midway@example.com")
    for day in (1, 3, 5, 7, 10):
        _run(db, user, days=day)
    org.plan, org.subscription_status = "professional", "active"
    db.commit()
    _run(db, user, days=12)
    _run(db, user, days=14)
    assert "plans" not in _steps(lc) and _row(db, user, "plans").reason == "paid_plan"


def test_customer_who_completes_everything_quickly_gets_no_reminders(client, db, lc):
    from app.models.field_intelligence import FieldObservation
    from app.models.market_intelligence import MarketPosition
    from app.models.operational_records import ChatConversation, ConnectorConnection

    user, org = _signup(client, db, "fast@example.com")
    org.plan, org.subscription_status = "professional", "active"
    db.add(ConnectorConnection(tenant_id=org.id, provider="wiseconn", display_name="WiseConn", status="connected", mode="api_credentials"))
    db.add(ChatConversation(tenant_id=org.id, user_id=user.id, title="Irrigation"))
    db.commit()
    created = {"tenant_id": org.id, "user_id": user.id}
    db.add(FieldObservation(**{k: v for k, v in created.items() if hasattr(FieldObservation, k)}, **_required(FieldObservation)))
    db.add(MarketPosition(organization_id=org.id, **_required(MarketPosition)))
    db.commit()
    user.last_login_at = datetime.utcnow() + timedelta(days=20)
    db.commit()
    for day in (1, 3, 5, 7, 10, 12, 14, 21):
        _run(db, user, days=day)
    assert _steps(lc) == ["welcome"]
    reasons = {row.step: row.reason for row in db.query(LifecycleEmailSend).filter_by(user_id=user.id)}
    assert reasons["connect_data"] == "already_connected_data" and reasons["ask"] == "already_asked"
    assert reasons["field"] == "already_used_field_intelligence" and reasons["market"] == "already_used_market_intelligence"
    assert reasons["plans"] == "paid_plan" and reasons["reactivation"] == "fully_activated"
    assert db.get(LifecycleEmailEnrollment, user.id).status == "completed"


def _required(model):
    """Minimal non-null values for required columns of an activity model."""
    values = {}
    for column in model.__table__.columns:
        if column.nullable or column.default is not None or column.server_default is not None or column.primary_key or column.foreign_keys:
            continue
        try:
            python_type = column.type.python_type
        except NotImplementedError:
            python_type = str
        if python_type is bool:
            values[column.name] = False
        elif python_type in {int, float} or python_type.__name__ == "Decimal":
            values[column.name] = 1
        else:
            values[column.name] = "test"
    return values


def test_inactive_customer_gets_reactivation_pointing_at_the_next_unfinished_step(client, db, lc):
    user, org = _signup(client, db, "inactive@example.com")
    now = datetime.utcnow()
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    enrollment.enrolled_at, enrollment.last_sent_at = now - timedelta(days=21, hours=1), now - timedelta(days=7)
    user.last_login_at = now - timedelta(days=20)
    for step in ("connect_data", "ask", "field", "market", "connectors", "team", "plans"):
        db.add(LifecycleEmailSend(user_id=user.id, organization_id=org.id, step=step, status="sent", sent_at=now - timedelta(days=8), scheduled_for=now))
    db.commit()
    assert lifecycle_emails.process_enrollment(db, enrollment, now=now) == "sent"
    assert _row(db, user, "reactivation").variant == "connect_data"
    assert "/integrations?lang=en" in lc.sent[-1]["html_body"]
    assert lc.sent[-1]["subject"] == "Pick up where you left off in AGRO-AI"


def test_unsubscribe_requires_confirmation_and_stops_only_lifecycle(client, db, lc):
    user, org = _signup(client, db, "unsub@example.com")
    db.add(UserPreference(user_id=user.id, locale="en", notifications_json=json.dumps({"report_delivery": True})) if db.get(UserPreference, user.id) is None else db.get(UserPreference, user.id))
    db.commit()
    before = db.get(UserPreference, user.id).notifications_json
    token = lifecycle_emails.unsubscribe_token(user.id)
    page = client.get(f"/v1/email/lifecycle/unsubscribe?u={user.id}&t={token}")
    assert page.status_code == 200 and "Confirm" in page.text
    assert db.get(LifecycleEmailEnrollment, user.id).unsubscribed_at is None  # GET (link scanners) never unsubscribes
    assert client.post(f"/v1/email/lifecycle/unsubscribe?u={user.id}&t=forged").status_code == 200
    assert db.get(LifecycleEmailEnrollment, user.id).unsubscribed_at is None
    one_click = client.post(f"/v1/email/lifecycle/unsubscribe?u={user.id}&t={token}", content=b"List-Unsubscribe=One-Click")
    assert one_click.status_code == 200 and one_click.json()["status"] == "unsubscribed"
    db.expire_all()
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    assert enrollment.status == "stopped" and enrollment.stop_reason == "unsubscribed"
    assert db.get(UserPreference, user.id).notifications_json == before  # transactional preferences untouched
    _run(db, user, days=1)
    assert _steps(lc) == ["welcome"]


def test_deactivated_and_deleted_accounts_stop(client, db, lc):
    user, _ = _signup(client, db, "deactivated@example.com")
    user.account_status = "suspended_pending_appeal"
    db.commit()
    assert _run(db, user, days=1) == "stopped"
    assert db.get(LifecycleEmailEnrollment, user.id).stop_reason == "account_inactive"
    enrollment = lifecycle_emails.enroll_user(db, "ghost-user", None, source="test")
    assert lifecycle_emails.process_enrollment(db, enrollment) == "stopped"
    assert enrollment.stop_reason == "user_deleted"


def test_non_english_customer_receives_localized_email_with_no_english_fallback(client, db, lc):
    user, _ = _signup(client, db, "pt@example.com", locale="pt-BR")
    message = lc.sent[0]
    assert message["subject"] == "[pt-BR] Welcome to AGRO-AI"
    assert '<html lang="pt-BR"' in message["html_body"] and "lang=pt-BR" in message["html_body"]
    assert "[pt-BR] Stop onboarding emails" in message["html_body"] and "[pt-BR] Continue setup" in message["html_body"]
    assert _row(db, user, "welcome").locale == "pt-BR"


def test_language_is_resolved_at_send_time(client, db, lc):
    user, _ = _signup(client, db, "switch@example.com", locale="en")
    assert lc.sent[0]["subject"] == "Welcome to AGRO-AI"
    preference = db.get(UserPreference, user.id)
    preference.locale = "ja"
    db.commit()
    _run(db, user, days=1)
    assert lc.sent[-1]["subject"].startswith("[ja] ") and _row(db, user, "connect_data").locale == "ja"


def test_rtl_locale_renders_right_to_left(client, db, lc):
    _signup(client, db, "ar@example.com", locale="ar")
    assert 'dir="rtl"' in lc.sent[0]["html_body"]


def test_deterministic_catalog_is_preferred_over_runtime_translation(client, db, lc):
    source = lifecycle_email_i18n.source_envelope()
    catalog = {key: f"DE {value}" for key, value in source["catalog"].items()}
    lc.catalogs.mkdir(parents=True, exist_ok=True)
    (lc.catalogs / "de.json").write_text(json.dumps({
        "schemaVersion": 1, "locale": "de", "sourceVersion": source["version"], "status": "complete-generated",
        "sourceFingerprint": lifecycle_email_i18n.fingerprint(source["catalog"]), "catalog": catalog,
    }))
    lifecycle_email_i18n._static_catalog.cache_clear()
    _signup(client, db, "de@example.com", locale="de")
    assert lc.sent[0]["subject"] == "DE Welcome to AGRO-AI"
    assert "de" not in lc.state["translator_calls"]


def test_supported_locale_is_deferred_never_sent_in_english(client, db, lc):
    lc.state["translator_down"] = True
    user, _ = _signup(client, db, "fr@example.com", locale="fr-FR")
    assert lc.sent == []
    row = _row(db, user, "welcome")
    assert row.status == "deferred_localization" and row.next_attempt_at is not None
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    lifecycle_emails.process_enrollment(db, enrollment, now=row.created_at + timedelta(hours=2))
    assert lc.sent == []
    lifecycle_emails.process_enrollment(db, enrollment, now=row.created_at + timedelta(days=3, hours=2))
    db.refresh(row)
    assert lc.sent == [] and (row.status, row.reason) == ("skipped", "localization_unavailable")
    lc.state["translator_down"] = False
    lifecycle_emails.process_enrollment(db, enrollment, now=enrollment.enrolled_at + timedelta(days=3, hours=3))
    assert all(message["subject"].startswith("[fr-FR] ") for message in lc.sent)


def test_unknown_or_invalid_locale_falls_back_to_english():
    assert lifecycle_email_i18n.resolve_locale("xx-YY") == "en"
    assert lifecycle_email_i18n.resolve_locale("not a locale") == "en"
    assert lifecycle_email_i18n.resolve_locale(None, "auto") == "en"
    assert lifecycle_email_i18n.resolve_locale("auto", "pt-BR") == "pt-BR"
    assert lifecycle_email_i18n.resolve_locale("pt") == "pt-BR"
    assert lifecycle_email_i18n.resolve_locale("de-DE") == "de"


def test_temporary_provider_failure_retries_once_successfully(client, db, lc):
    lc.state["result"] = {"ok": False, "provider": "resend", "status_code": 503, "reason": "provider_unavailable: try later"}
    user, _ = _signup(client, db, "retry@example.com")
    row = _row(db, user, "welcome")
    assert row.status == "retry" and row.attempts == 1 and row.reason == "provider_unavailable"
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    assert lifecycle_emails.process_enrollment(db, enrollment, now=row.created_at + timedelta(minutes=5)) == "waiting_retry"
    lc.state["result"] = {"ok": True, "provider": "resend", "status_code": 200, "provider_response": '{"id":"msg-2"}'}
    assert lifecycle_emails.process_enrollment(db, enrollment, now=row.created_at + timedelta(hours=1)) == "sent"
    db.refresh(row)
    assert (row.status, row.attempts, row.provider_message_id) == ("sent", 2, "msg-2")
    assert len(lc.sent) == 2  # one failed attempt, one delivery; never a duplicate delivery


def test_restarts_and_duplicate_scheduling_never_resend(client, db, lc):
    user, org = _signup(client, db, "dupe@example.com")
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    for _ in range(3):  # repeated scheduler passes / redeploys at the same moment
        lifecycle_emails.process_enrollment(db, enrollment, now=enrollment.enrolled_at + timedelta(minutes=30))
    assert _steps(lc) == ["welcome"]
    lifecycle_emails.enroll_user(db, user.id, org.id, source="email_verified")  # duplicate enrollment is a no-op
    assert db.query(LifecycleEmailEnrollment).filter_by(user_id=user.id).count() == 1
    # Another worker already claimed connect_data: this worker must not send it.
    claimed_at = enrollment.enrolled_at + timedelta(days=1, hours=1)
    db.add(LifecycleEmailSend(user_id=user.id, organization_id=org.id, step="connect_data", status="sending", scheduled_for=claimed_at, updated_at=claimed_at))
    db.commit()
    assert lifecycle_emails.process_enrollment(db, enrollment, now=claimed_at + timedelta(minutes=1)) == "in_flight"
    assert _steps(lc).count("connect_data") == 0
    # A send interrupted mid-flight is never retried (it may have been delivered).
    lifecycle_emails.process_enrollment(db, enrollment, now=claimed_at + timedelta(hours=2))
    stale = _row(db, user, "connect_data")
    db.refresh(stale)
    assert stale.status == "interrupted" and _steps(lc).count("connect_data") == 0


def test_overdue_steps_expire_instead_of_bursting(client, db, lc, monkeypatch):
    monkeypatch.setattr(settings, "LIFECYCLE_EMAILS_ENABLED", False)  # e.g. enabled weeks after signup
    user, _ = _signup(client, db, "late@example.com")
    assert lc.sent == []
    monkeypatch.setattr(settings, "LIFECYCLE_EMAILS_ENABLED", True)
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    lifecycle_emails.process_enrollment(db, enrollment, now=enrollment.enrolled_at + timedelta(days=30))
    assert lc.sent == []
    assert {row.reason for row in db.query(LifecycleEmailSend).filter_by(user_id=user.id)} == {"expired"}


def test_sending_is_held_when_disabled_or_without_postal_address(db, lc, monkeypatch):
    monkeypatch.setattr(settings, "LIFECYCLE_EMAIL_POSTAL_ADDRESS", "")
    assert lifecycle_emails.process_due(db) == {"status": "held", "reason": "postal_address_not_configured"}
    monkeypatch.setattr(settings, "LIFECYCLE_EMAILS_ENABLED", False)
    assert lifecycle_emails.process_due(db) == {"status": "held", "reason": "disabled"}


def test_existing_accounts_are_never_enrolled_automatically(client, db, lc, monkeypatch):
    monkeypatch.setattr(settings, "LIFECYCLE_EMAILS_ENABLED", False)
    user, _ = _signup(client, db, "existing@example.com", verify=False)
    user.email_verification_status, user.email_verified_at = "verified", datetime.utcnow()
    db.commit()
    monkeypatch.setattr(settings, "LIFECYCLE_EMAILS_ENABLED", True)
    assert lifecycle_emails.process_due(db)["processed"] == 0
    assert lc.sent == []


def _signed(secret: str, body: bytes) -> dict:
    msg_id, ts = "msg_test", str(int(time.time()))
    key = base64.b64decode(secret.split("_", 1)[1])
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}", "content-type": "application/json"}


def test_provider_events_record_engagement_and_bounces_stop_the_sequence(client, db, lc, monkeypatch):
    secret = "whsec_" + base64.b64encode(b"lifecycle-test-secret").decode()
    monkeypatch.setattr(settings, "RESEND_WEBHOOK_SECRET", secret)
    user, _ = _signup(client, db, "bounce@example.com")
    opened = json.dumps({"type": "email.opened", "data": {"email_id": "msg-1", "to": ["bounce@example.com"]}}).encode()
    assert client.post("/v1/email/provider-events", content=opened, headers=_signed(secret, opened)).status_code == 200
    assert client.post("/v1/email/provider-events", content=opened, headers={**_signed(secret, opened), "svix-signature": "v1,forged"}).status_code == 400
    bounced = json.dumps({"type": "email.bounced", "data": {"email_id": "msg-1", "to": ["bounce@example.com"], "bounce": {"type": "Permanent"}}}).encode()
    assert client.post("/v1/email/provider-events", content=bounced, headers=_signed(secret, bounced)).status_code == 200
    db.expire_all()
    row = _row(db, user, "welcome")
    assert row.opened_at is not None and row.bounced_at is not None
    assert db.get(LifecycleEmailEnrollment, user.id).stop_reason == "address_bounced"


def test_provider_events_fail_closed_without_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "RESEND_WEBHOOK_SECRET", "")
    assert client.post("/v1/email/provider-events", content=b"{}").status_code == 503


def test_admin_view_is_platform_admin_only_and_explains_state(client, db, lc, monkeypatch):
    user, org = _signup(client, db, "debug@example.com")
    login = client.post("/v1/auth/login", json={"email": "debug@example.com", "password": PASSWORD}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get(f"/v1/admin/lifecycle-emails/{user.id}", headers=headers).status_code == 403
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "debug@example.com")
    state = client.get(f"/v1/admin/lifecycle-emails/{user.id}", headers=headers).json()
    assert state["status"] == "active" and state["history"][0]["step"] == "welcome"
    assert state["next"]["step"] == "connect_data" and state["unsubscribed"] is False


def test_activation_after_an_email_is_attributed(client, db, lc):
    user, org = _signup(client, db, "attr@example.com")
    _run(db, user, days=1)
    assert _steps(lc)[-1] == "connect_data"
    sent_at = _row(db, user, "connect_data").sent_at
    db.add(DataSource(tenant_id=org.id, provider="manual_csv", source_type="upload", filename="log.csv", created_at=sent_at + timedelta(hours=3)))
    db.commit()
    _run(db, user, days=2)
    row = _row(db, user, "connect_data")
    assert row.activation_event == "has_data" and row.activated_at == sent_at + timedelta(hours=3)


def test_scheduled_maintenance_isolates_lifecycle_failures(monkeypatch):
    from app.api.v1 import cloudflare_queue

    def boom():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.services.lifecycle_emails.run_scheduled", boom)
    assert cloudflare_queue._run_lifecycle_emails() == {"status": "error", "reason": "RuntimeError"}


@pytest.mark.parametrize("step,variant", [
    ("welcome", None), ("connect_data", None), ("ask", "with_data"), ("ask", "without_data"), ("field", None),
    ("market", None), ("connectors", "free"), ("connectors", "paid"), ("team", None), ("plans", "standard"),
    ("plans", "usage"), ("reactivation", "connect_data"), ("reactivation", "ask"), ("reactivation", "field"),
    ("reactivation", "market"),
])
def test_every_step_renders_completely_from_the_canonical_copy(step, variant, monkeypatch):
    monkeypatch.setattr(settings, "LIFECYCLE_EMAIL_POSTAL_ADDRESS", ADDRESS)
    signals = lifecycle_emails.Signals(plan="free", paid=False, enterprise=False, previous_subscriber=False, non_customer=False,
                                       role="owner", seats=3, uploads_this_month=13, upload_limit=15)
    user = SimpleNamespace(id="user-1", name="Ana", email="ana@example.com")
    org = SimpleNamespace(name="Valley Orchards")
    message = lifecycle_emails.render(step, variant, lifecycle_email_i18n.source_catalog(), locale="en", user=user, org=org, signals=signals)
    for part in ("subject", "preview", "html", "text"):
        assert message[part].strip()
        assert not __import__("re").search(r"\{[a-z_]+\}", message[part]), (part, message[part])
    assert ADDRESS in message["html"] and __import__("html").escape(message["unsubscribe_url"], quote=True) in message["html"]


def test_lifecycle_source_copy_is_well_formed():
    source = lifecycle_email_i18n.source_envelope()
    assert source["schemaVersion"] == 1 and source["version"]
    used = __import__("re").findall(r'c\("([a-z_.0-9]+)"\)|"([a-z_]+\.(?:cta|subject|preview|headline))"', open(lifecycle_emails.__file__).read())
    keys = {a or b for a, b in used}
    assert keys <= set(source["catalog"]), sorted(keys - set(source["catalog"]))


def test_localized_email_uses_the_portals_own_product_and_plan_names(client, db, lc):
    user, org = _signup(client, db, "names@example.com", locale="pt-BR")
    for day in (1, 3, 5, 7, 10, 12, 14):
        _run(db, user, days=day)
    field = next(m for m in lc.sent if m["tags"][1]["value"] == "field")
    plans = next(m for m in lc.sent if m["tags"][1]["value"] == "plans")
    labels = lifecycle_email_i18n.product_labels("pt-BR")
    assert labels["field_name"] != "Field Intelligence"  # the portal localizes it
    assert labels["field_name"] in field["html_body"] and "Field Intelligence" not in field["html_body"]
    assert labels["plan_professional"] in plans["text_body"] and labels["ask_name"] in plans["text_body"]


def test_every_supported_locale_has_a_current_lifecycle_catalog():
    """Copy edits must be re-authored before release (shared/localization/lifecycle-email-catalogs)."""
    from app.services.language_registry import target_ui_locales

    lifecycle_email_i18n._static_catalog.cache_clear()
    missing = [loc for loc in target_ui_locales() if loc not in {"auto", "en"} and lifecycle_email_i18n._static_catalog(loc) is None]
    assert missing == []


def test_lifecycle_email_reaches_sendgrid_with_one_click_unsubscribe_headers(client, db, lc, monkeypatch):
    """End to end through the real send_email: the SendGrid v3 payload carries both RFC 8058 headers."""
    for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "RESEND_API_KEY"):
        monkeypatch.setattr(settings, key, None, raising=False)
    monkeypatch.setattr(settings, "SENDGRID_API_KEY", "SG.test", raising=False)
    monkeypatch.setattr(settings, "FROM_EMAIL", "AGRO-AI <hello@agroai-pilot.com>", raising=False)
    monkeypatch.setattr("app.services.email_delivery.send_email", _real_send_email)
    payloads: list[dict] = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None):
            payloads.append({"url": url, "json": json})
            return SimpleNamespace(status_code=202, text="")

    monkeypatch.setattr("app.services.email_delivery.httpx.Client", Client)
    user, _org = _signup(client, db, "sendgrid@example.com")
    lifecycle = [p for p in payloads if (p["json"].get("custom_args") or {}).get("category") == "lifecycle"]
    transactional = [p for p in payloads if p not in lifecycle]
    (request,) = lifecycle
    assert transactional and all("headers" not in p["json"] for p in transactional)
    assert request["url"] == "https://api.sendgrid.com/v3/mail/send"
    headers = request["json"]["headers"]
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert headers["List-Unsubscribe"].startswith("<") and f"/v1/email/lifecycle/unsubscribe?u={user.id}" in headers["List-Unsubscribe"]
    assert request["json"]["custom_args"] == {"category": "lifecycle", "step": "welcome"}
    assert _row(db, user, "welcome").status == "sent"


def _bulk_enroll(db, prefix, count, enrolled_at):
    users = [User(email=f"{prefix}-{i}@example.test", password_hash="x", email_verification_status="verified") for i in range(count)]
    db.add_all(users)
    db.flush()
    orgs = [Organization(name=f"{prefix} {i}", slug=f"{prefix}-{i}", owner_user_id=user.id) for i, user in enumerate(users)]
    db.add_all(orgs)
    db.flush()
    db.add_all([OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner") for user, org in zip(users, orgs)])
    db.commit()
    return [lifecycle_emails.enroll_user(db, user.id, org.id, source="email_verified", enrolled_at=enrolled_at) for user, org in zip(users, orgs)]


def test_waiting_enrollments_cannot_starve_newer_due_users(db, lc):
    """>200 older active enrollments that are only waiting must not consume the batch."""
    t0 = datetime.utcnow() - timedelta(minutes=5)
    old = _bulk_enroll(db, "old", 250, t0)
    first = lifecycle_emails.process_due(db, now=t0 + timedelta(minutes=5), limit=300)
    assert first["outcomes"] == {"sent": 250}  # all 250 welcomed; next step (connect_data) is a day away
    lc.sent.clear()

    new = _bulk_enroll(db, "new", 30, t0 + timedelta(hours=2))
    result = lifecycle_emails.process_due(db, now=t0 + timedelta(hours=3), limit=200)
    # Only the 30 newer users have work due; the 250 waiting users are not selected at all.
    assert result == {"status": "ok", "processed": 30, "outcomes": {"sent": 30}}
    assert {m["to_email"] for m in lc.sent} == {f"new-{i}@example.test" for i in range(30)}
    assert all(_steps(lc)[i] == "welcome" for i in range(30))
    for enrollment in old:
        db.refresh(enrollment)
        assert enrollment.next_action_at == t0 + timedelta(days=1)  # connect_data due time
    # Once connect_data is due for the old cohort, they progress too (no starvation in either direction).
    lc.sent.clear()
    later = lifecycle_emails.process_due(db, now=t0 + timedelta(days=1, hours=1), limit=200)
    assert later["processed"] == 200
    # The remaining 50 old users, plus the 30 newer users whose connect_data is now due too.
    assert lifecycle_emails.process_due(db, now=t0 + timedelta(days=1, hours=2), limit=200)["processed"] == 80
    assert _steps(lc) == ["connect_data"] * 280
    assert len({m["to_email"] for m in lc.sent}) == len(lc.sent)  # nobody received two emails


def test_due_backlog_larger_than_batch_rotates_fairly(db, lc):
    t0 = datetime.utcnow() - timedelta(minutes=5)
    _bulk_enroll(db, "backlog", 230, t0)
    now = t0 + timedelta(minutes=5)
    seen: list[str] = []
    for _ in range(3):
        lc.sent.clear()
        lifecycle_emails.process_due(db, now=now, limit=100)
        seen.extend(m["to_email"] for m in lc.sent)
    # Every user welcomed exactly once across three bounded batches; nobody twice, nobody skipped.
    assert len(seen) == 230 and len(set(seen)) == 230
    assert lifecycle_emails.process_due(db, now=now, limit=100)["processed"] == 0


def test_next_action_tracks_gap_retry_and_deferred_localization(client, db, lc):
    user, _ = _signup(client, db, "schedule@example.com")
    enrollment = db.get(LifecycleEmailEnrollment, user.id)
    welcome = _row(db, user, "welcome")
    # After welcome: connect_data at +1 day, and never sooner than the 20h gap.
    assert enrollment.next_action_at == max(enrollment.enrolled_at + timedelta(days=1), welcome.sent_at + lifecycle_emails.MIN_GAP)
    # A provider failure schedules the retry time.
    lc.state["result"] = {"ok": False, "provider": "resend", "reason": "provider_unavailable", "status_code": 503}
    due = enrollment.enrolled_at + timedelta(days=1, hours=1)
    assert lifecycle_emails.process_enrollment(db, enrollment, now=due) == "retry"
    row = _row(db, user, "connect_data")
    assert enrollment.next_action_at == row.next_attempt_at > due
    # Retries remain reachable through process_due once due, and then succeed.
    lc.state["result"] = {"ok": True, "provider": "resend", "status_code": 200, "provider_response": '{"id":"msg-r"}'}
    assert lifecycle_emails.process_due(db, now=row.next_attempt_at - timedelta(minutes=1))["processed"] == 0
    assert lifecycle_emails.process_due(db, now=row.next_attempt_at)["outcomes"] == {"sent": 1}
    # Deferred localization is retried at its scheduled time too.
    preference = db.get(UserPreference, user.id)
    preference.locale = "de"
    db.commit()
    lc.state["translator_down"] = True
    ask_due = enrollment.enrolled_at + timedelta(days=5, hours=1)
    lifecycle_emails.process_enrollment(db, enrollment, now=ask_due)
    deferred = [r for r in db.query(LifecycleEmailSend).filter_by(user_id=user.id) if r.status == "deferred_localization"]
    if deferred:  # catalogs are isolated in this fixture, so German relies on runtime translation
        assert enrollment.next_action_at == deferred[0].next_attempt_at
        lc.state["translator_down"] = False
        assert lifecycle_emails.process_due(db, now=deferred[0].next_attempt_at)["outcomes"] == {"sent": 1}


def test_failing_enrollment_backs_off_instead_of_blocking_queue(db, lc, monkeypatch):
    t0 = datetime.utcnow() - timedelta(minutes=5)
    enrollments = _bulk_enroll(db, "err", 3, t0)
    broken = min(e.user_id for e in enrollments)  # first in queue order (ties break on user_id)
    real = lifecycle_emails._advance

    def flaky(db_, enrollment, **kwargs):
        if enrollment.user_id == broken:
            raise RuntimeError("boom")
        return real(db_, enrollment, **kwargs)

    monkeypatch.setattr(lifecycle_emails, "_advance", flaky)
    now = t0 + timedelta(minutes=5)
    result = lifecycle_emails.process_due(db, now=now, limit=1)
    assert result["outcomes"] == {"error": 1}
    assert db.get(LifecycleEmailEnrollment, broken).next_action_at == now + lifecycle_emails.ERROR_BACKOFF
    # The next batch of one moves on to the healthy enrollments.
    assert lifecycle_emails.process_due(db, now=now, limit=1)["outcomes"] == {"sent": 1}
    assert lifecycle_emails.process_due(db, now=now, limit=1)["outcomes"] == {"sent": 1}
