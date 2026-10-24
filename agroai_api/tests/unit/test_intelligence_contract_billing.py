"""Paid-invoice wallet credits, reconciliation, admission sync and cost telemetry."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
import stripe
from fastapi import HTTPException

from app.api.v1 import commercial_intelligence_hardened as hardened
from app.api.v1.intelligence_contract_billing import verify_invoice_for_credit
from app.core.config import settings
from app.models.intelligence_commerce import IntelligenceWallet, IntelligenceWalletLedger
from app.models.saas import SecurityAuditEvent
from tests.unit.test_platform_admin import _account, _headers

ROUTE = "/v1/platform-admin/intelligence/invoice-credits"
INVOICE = "in_1TestPilotInvoice01"


def _invoice(org_id: str, **overrides):
    invoice = {
        "id": INVOICE, "customer": "cus_pilot_customer", "status": "paid", "currency": "usd", "livemode": False,
        "amount_paid": 500_000, "total_taxes": [],
        "metadata": {"agroai_organization_id": org_id, "agroai_intelligence_credit_cents": "250000"},
    }
    invoice.update(overrides)
    return invoice


@pytest.fixture
def stripe_test_mode(monkeypatch):
    monkeypatch.setattr(settings, "INTELLIGENCE_INVOICE_CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_MODE", "test")
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_SECRET_KEY", "sk_test_local")


@pytest.mark.parametrize(("override", "code"), [
    ({"customer": "cus_someone_else"}, "invoice_customer_mismatch"),
    ({"status": "open"}, "invoice_not_paid"),
    ({"status": "draft"}, "invoice_not_paid"),
    ({"currency": "inr"}, "invoice_currency_unsupported"),
    ({"livemode": True}, "invoice_mode_mismatch"),
    ({"metadata": {"agroai_intelligence_credit_cents": "250000"}}, "invoice_metadata_missing"),
    ({"metadata": {"agroai_organization_id": "org-1", "agroai_intelligence_credit_cents": "lots"}}, "invoice_metadata_missing"),
    ({"metadata": {"agroai_organization_id": "org-1", "agroai_intelligence_credit_cents": "999"}}, "invoice_credit_mismatch"),
    ({"amount_paid": 200_000}, "invoice_credit_exceeds_payment"),
    ({"total_taxes": [{"amount": 300_000}]}, "invoice_credit_exceeds_payment"),
])
def test_invoice_verification_refuses_every_mismatch(stripe_test_mode, override, code):
    organization = SimpleNamespace(id="org-1", stripe_customer_id="cus_pilot_customer")
    with pytest.raises(HTTPException) as refused:
        verify_invoice_for_credit(_invoice("org-1", **override), organization, 250_000)
    assert refused.value.detail["code"] == code


def test_invoice_verification_requires_mapped_stripe_customer(stripe_test_mode):
    unmapped = SimpleNamespace(id="org-1", stripe_customer_id=None)
    with pytest.raises(HTTPException) as refused:
        verify_invoice_for_credit(_invoice("org-1"), unmapped, 250_000)
    assert refused.value.detail["code"] == "invoice_customer_mismatch"
    mapped = SimpleNamespace(id="org-1", stripe_customer_id="cus_pilot_customer")
    assert verify_invoice_for_credit(_invoice("org-1", customer={"id": "cus_pilot_customer"}), mapped, 250_000) == 250_000


def _setup(db, monkeypatch):
    founder, founder_org, _ = _account(db, email="founder@example.com", name="Founder", org_name="Founder Org")
    _customer, customer_org, _ = _account(db, email="dev@customer.example", name="Customer Dev", org_name="Pilot Customer")
    customer_org.stripe_customer_id = "cus_pilot_customer"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", founder.email)
    return founder, founder_org, customer_org


def test_paid_invoice_credits_wallet_once_and_reconciles(client, db, monkeypatch, stripe_test_mode):
    founder, founder_org, customer_org = _setup(db, monkeypatch)
    calls = []
    monkeypatch.setattr(stripe.Invoice, "retrieve", lambda invoice_id: calls.append(invoice_id) or _invoice(customer_org.id))
    body = {"organization_id": customer_org.id, "stripe_invoice_id": INVOICE, "expected_credit_cents": 250_000}

    first = client.post(ROUTE, headers=_headers(founder, founder_org), json=body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "credited" and first.json()["balance_cents"] == 250_000
    assert first.headers["cache-control"].startswith("no-store")
    replay = client.post(ROUTE, headers=_headers(founder, founder_org), json=body)
    assert replay.status_code == 200 and replay.json()["status"] == "already_credited"
    assert calls == [INVOICE]  # replay never re-reads Stripe or re-credits

    db.expire_all()
    wallet = db.query(IntelligenceWallet).filter_by(organization_id=customer_org.id).one()
    assert wallet.balance_cents == 250_000 and wallet.lifetime_funded_cents == 250_000
    ledger = db.query(IntelligenceWalletLedger).filter_by(organization_id=customer_org.id).all()
    assert len(ledger) == 1 and ledger[0].kind == "topup" and ledger[0].status == "posted" and ledger[0].external_reference == INVOICE
    assert db.query(SecurityAuditEvent).filter_by(event_type="intelligence_invoice_credit", outcome="posted").count() == 1

    recon = client.get("/v1/platform-admin/intelligence/reconciliation", params={"organization_id": customer_org.id},
                       headers=_headers(founder, founder_org))
    assert recon.status_code == 200
    assert recon.json()["checks"] == {"balance_matches_posted_ledger": True, "completed_runs_match_ledger_charges": True}


def test_invoice_credit_refusals_leave_wallet_untouched(client, db, monkeypatch, stripe_test_mode):
    founder, founder_org, customer_org = _setup(db, monkeypatch)
    headers = _headers(founder, founder_org)
    body = {"organization_id": customer_org.id, "stripe_invoice_id": INVOICE, "expected_credit_cents": 250_000}

    monkeypatch.setattr(stripe.Invoice, "retrieve", lambda _id: _invoice(customer_org.id, status="open"))
    unpaid = client.post(ROUTE, headers=headers, json=body)
    assert unpaid.status_code == 422 and unpaid.json()["detail"]["code"] == "invoice_not_paid"

    def unreachable(_id):
        raise stripe.error.APIConnectionError("down")
    monkeypatch.setattr(stripe.Invoice, "retrieve", unreachable)
    assert client.post(ROUTE, headers=headers, json=body).status_code == 503

    def missing(_id):
        raise stripe.error.InvalidRequestError("No such invoice", "id")
    monkeypatch.setattr(stripe.Invoice, "retrieve", missing)
    assert client.post(ROUTE, headers=headers, json=body).status_code == 404

    assert client.post(ROUTE, headers=headers, json={**body, "stripe_invoice_id": "cs_test_checkout"}).status_code == 422
    assert client.post(ROUTE, headers=headers, json={**body, "expected_credit_cents": -5}).status_code == 422
    assert db.query(IntelligenceWalletLedger).filter_by(organization_id=customer_org.id).count() == 0
    assert db.query(SecurityAuditEvent).filter_by(event_type="intelligence_invoice_credit", outcome="refused").count() == 1


def test_invoice_credit_is_admin_only_and_disabled_by_default(client, db, monkeypatch, stripe_test_mode):
    founder, founder_org, customer_org = _setup(db, monkeypatch)
    customer_owner, owner_org, _ = _account(db, email="owner@customer2.example", name="Owner", org_name="Other Customer")
    monkeypatch.setattr(stripe.Invoice, "retrieve", lambda _id: _invoice(customer_org.id))
    body = {"organization_id": customer_org.id, "stripe_invoice_id": INVOICE, "expected_credit_cents": 250_000}
    assert client.post(ROUTE, headers=_headers(customer_owner, owner_org), json=body).status_code == 403
    assert client.post(ROUTE, json=body).status_code in {401, 403}
    monkeypatch.setattr(settings, "INTELLIGENCE_INVOICE_CREDITS_ENABLED", False)
    assert client.post(ROUTE, headers=_headers(founder, founder_org), json=body).status_code == 404
    assert db.query(IntelligenceWalletLedger).count() == 0


def test_invoice_cannot_fund_two_organizations(client, db, monkeypatch, stripe_test_mode):
    founder, founder_org, customer_org = _setup(db, monkeypatch)
    _second_owner, second_org, _ = _account(db, email="b@customer3.example", name="B", org_name="Second Customer")
    second_org.stripe_customer_id = "cus_pilot_customer"
    db.commit()
    monkeypatch.setattr(stripe.Invoice, "retrieve", lambda _id: _invoice(customer_org.id))
    headers = _headers(founder, founder_org)
    ok = client.post(ROUTE, headers=headers, json={"organization_id": customer_org.id, "stripe_invoice_id": INVOICE, "expected_credit_cents": 250_000})
    assert ok.status_code == 200
    reuse = client.post(ROUTE, headers=headers, json={"organization_id": second_org.id, "stripe_invoice_id": INVOICE, "expected_credit_cents": 250_000})
    assert reuse.status_code == 409 and reuse.json()["detail"]["code"] == "invoice_already_used"


def test_admission_reconciles_pending_topups_only_on_shortfall_and_before_refusing():
    source = inspect.getsource(hardened._admit_paid_run)
    shortfall = source.index("if int(wallet.balance_cents) < price_cents:")
    sync = source.index("_sync_pending_topups(db, principal.organization_id)")
    refusal = source.index("insufficient_intelligence_balance")
    assert shortfall < sync < refusal
    assert source.count("_sync_pending_topups(") == 1


def test_provider_usage_telemetry_keeps_only_numeric_counters():
    result = SimpleNamespace(raw={"usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500, "cost": 0.0021,
                                            "note": "x", "cached": True}})
    assert hardened._provider_usage(result) == {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500, "cost": 0.0021}
    assert hardened._provider_usage(SimpleNamespace(raw=None)) == {}
    assert hardened._provider_usage(SimpleNamespace()) == {}
    source = inspect.getsource(hardened._complete_paid_run)
    assert '"provider_usage": _provider_usage(model_result)' in source
