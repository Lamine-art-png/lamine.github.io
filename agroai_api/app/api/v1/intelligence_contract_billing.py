"""Contract (manually invoiced) funding and reconciliation for Intelligence wallets.

A signed pilot or enterprise order is invoiced in Stripe by AGRO-AI staff. Once
Stripe reports that invoice as paid, a platform admin posts the agreed credit
to the customer's existing Intelligence wallet. The credit is verified against
the live Stripe invoice (customer, status, currency, mode, amount and explicit
AGRO-AI metadata) and is idempotent per invoice. Consumption then uses the
existing per-run wallet debit and ledger; there is no second billing system.

Invoice metadata required on the Stripe invoice:
  agroai_organization_id          = the AGRO-AI organization id
  agroai_intelligence_credit_cents = integer wallet credit, <= amount paid excluding tax
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform_admin
from app.api.v1 import commercial_intelligence as legacy
from app.core.config import settings
from app.db.base import get_db
from app.models.intelligence_commerce import CommercialIntelligenceRun, IntelligenceWalletLedger
from app.models.saas import Organization
from app.platform_api.stripe_mode import platform_stripe_configuration_error, platform_stripe_livemode_matches
from app.services.security_audit import record_security_event

router = APIRouter(prefix="/platform-admin/intelligence", tags=["platform-admin"])

_INVOICE_ID = re.compile(r"^in_[A-Za-z0-9]{8,64}$")
MAX_INVOICE_CREDIT_CENTS = 10_000_000


class InvoiceCreditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(min_length=1, max_length=64)
    stripe_invoice_id: str
    expected_credit_cents: int = Field(gt=0, le=MAX_INVOICE_CREDIT_CENTS)

    @field_validator("stripe_invoice_id")
    @classmethod
    def invoice_id(cls, value: str) -> str:
        if not _INVOICE_ID.fullmatch(value):
            raise ValueError("stripe_invoice_id must be a Stripe invoice id (in_...)")
        return value


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"


def _refuse(code: str, message: str, status_code: int = 422) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _stripe_client() -> None:
    if not bool(getattr(settings, "INTELLIGENCE_INVOICE_CREDITS_ENABLED", False)):
        raise HTTPException(status_code=404, detail={"code": "invoice_credits_disabled"})
    secret = str(getattr(settings, "PLATFORM_API_STRIPE_SECRET_KEY", "") or "").strip()
    if not secret:
        raise _refuse("stripe_not_configured", "Stripe is not configured.", 503)
    error = platform_stripe_configuration_error(mode=settings.PLATFORM_API_STRIPE_MODE, secret_key=secret)
    if error:
        raise _refuse(error, "Stripe configuration is inconsistent.", 503)
    stripe.api_key = secret


def _invoice_tax_cents(invoice: Any) -> int:
    taxes = invoice.get("total_taxes") or invoice.get("total_tax_amounts") or []
    if taxes:
        return sum(int(item.get("amount") or 0) for item in taxes)
    return int(invoice.get("tax") or 0)


def verify_invoice_for_credit(invoice: Any, organization: Organization, expected_credit_cents: int) -> int:
    """Return the verified credit in cents or raise a machine-readable refusal."""
    customer = invoice.get("customer")
    customer_id = customer.get("id") if isinstance(customer, dict) else customer
    if not organization.stripe_customer_id or customer_id != organization.stripe_customer_id:
        raise _refuse("invoice_customer_mismatch", "The invoice belongs to a different Stripe customer than this organization.")
    if invoice.get("status") != "paid":
        raise _refuse("invoice_not_paid", "Stripe does not report this invoice as paid.")
    if str(invoice.get("currency") or "").lower() != "usd":
        raise _refuse("invoice_currency_unsupported", "Intelligence wallets are funded in USD only.")
    if not platform_stripe_livemode_matches(mode=settings.PLATFORM_API_STRIPE_MODE, livemode=bool(invoice.get("livemode"))):
        raise _refuse("invoice_mode_mismatch", "The invoice mode does not match the configured Stripe mode.")
    metadata = dict(invoice.get("metadata") or {})
    if metadata.get("agroai_organization_id") != organization.id:
        raise _refuse("invoice_metadata_missing", "The invoice must carry agroai_organization_id for this organization.")
    try:
        credit = int(str(metadata.get("agroai_intelligence_credit_cents") or ""))
    except ValueError:
        raise _refuse("invoice_metadata_missing", "The invoice must carry an integer agroai_intelligence_credit_cents.") from None
    if credit <= 0 or credit != expected_credit_cents:
        raise _refuse("invoice_credit_mismatch", "The requested credit does not match the invoice's agreed credit.")
    paid_excluding_tax = int(invoice.get("amount_paid") or 0) - _invoice_tax_cents(invoice)
    if credit > paid_excluding_tax:
        raise _refuse("invoice_credit_exceeds_payment", "The credit exceeds the amount paid excluding tax.")
    return credit


def _existing_credit(db: Session, invoice_id: str) -> IntelligenceWalletLedger | None:
    return db.query(IntelligenceWalletLedger).filter(IntelligenceWalletLedger.external_reference == invoice_id).first()


def _already(row: IntelligenceWalletLedger, organization_id: str) -> dict[str, Any]:
    if row.organization_id != organization_id or row.kind != "topup":
        raise _refuse("invoice_already_used", "This invoice is already linked to another ledger entry.", 409)
    return {"status": "already_credited", "ledger_id": row.id, "credit_cents": int(row.amount_cents)}


@router.post("/invoice-credits")
def credit_wallet_from_paid_invoice(
    payload: InvoiceCreditRequest,
    response: Response,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _no_store(response)
    _stripe_client()
    organization = db.get(Organization, payload.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail={"code": "organization_not_found"})
    existing = _existing_credit(db, payload.stripe_invoice_id)
    if existing is not None:
        return _already(existing, organization.id)
    try:
        invoice = stripe.Invoice.retrieve(payload.stripe_invoice_id)
    except stripe.error.InvalidRequestError as exc:
        raise _refuse("invoice_not_found", "Stripe has no invoice with this id in the configured mode.", 404) from exc
    except stripe.error.StripeError as exc:
        raise _refuse("stripe_unavailable", "Stripe could not be reached; retry later.", 503) from exc
    try:
        credit = verify_invoice_for_credit(invoice, organization, payload.expected_credit_cents)
    except HTTPException as refusal:
        record_security_event(db, event_type="intelligence_invoice_credit", outcome="refused", organization_id=organization.id,
                              user_id=ctx.user.id, metadata={"invoice_id": payload.stripe_invoice_id, "code": refusal.detail["code"]})
        db.commit()
        raise
    wallet = legacy._wallet(db, organization.id, lock=True)
    ledger = IntelligenceWalletLedger(
        organization_id=organization.id,
        wallet_id=wallet.id,
        kind="topup",
        status="posted",
        amount_cents=credit,
        idempotency_key=f"invoice:{payload.stripe_invoice_id}",
        external_reference=payload.stripe_invoice_id,
        metadata_json={
            "funding_source": "stripe_invoice",
            "amount_paid_cents": int(invoice.get("amount_paid") or 0),
            "credited_by_user_id": ctx.user.id,
        },
        posted_at=datetime.utcnow(),
    )
    try:
        with db.begin_nested():
            db.add(ledger)
            db.flush()
    except IntegrityError:
        db.rollback()
        existing = _existing_credit(db, payload.stripe_invoice_id)
        if existing is None:
            raise
        return _already(existing, organization.id)
    wallet.balance_cents += credit
    wallet.lifetime_funded_cents += credit
    wallet.updated_at = datetime.utcnow()
    record_security_event(db, event_type="intelligence_invoice_credit", outcome="posted", organization_id=organization.id,
                          user_id=ctx.user.id, metadata={"invoice_id": payload.stripe_invoice_id, "credit_cents": credit})
    db.commit()
    return {"status": "credited", "ledger_id": ledger.id, "credit_cents": credit, "balance_cents": int(wallet.balance_cents)}


@router.get("/reconciliation")
def intelligence_reconciliation(
    response: Response,
    organization_id: str = Query(min_length=1, max_length=64),
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Wallet balance vs. ledger vs. completed runs, plus provider usage for margin review."""
    _no_store(response)
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail={"code": "organization_not_found"})
    wallet = legacy._wallet(db, organization_id)
    sums = (
        db.query(IntelligenceWalletLedger.kind, IntelligenceWalletLedger.status, func.count(), func.coalesce(func.sum(IntelligenceWalletLedger.amount_cents), 0))
        .filter(IntelligenceWalletLedger.organization_id == organization_id)
        .group_by(IntelligenceWalletLedger.kind, IntelligenceWalletLedger.status)
        .all()
    )
    ledger = [{"kind": kind, "status": status, "count": int(count), "amount_cents": int(total)} for kind, status, count, total in sums]
    # A reversed charge is paired with a posted refund, so both count toward the balance.
    posted = sum(row["amount_cents"] for row in ledger if row["status"] in {"posted", "reversed"})
    runs = (
        db.query(func.count(), func.coalesce(func.sum(CommercialIntelligenceRun.charge_cents), 0))
        .filter(CommercialIntelligenceRun.organization_id == organization_id, CommercialIntelligenceRun.status == "completed")
        .one()
    )
    usage: dict[str, float] = {}
    charges = (
        db.query(IntelligenceWalletLedger.metadata_json)
        .filter(IntelligenceWalletLedger.organization_id == organization_id, IntelligenceWalletLedger.kind == "intelligence_charge")
        .all()
    )
    for (metadata,) in charges:
        for key, value in ((metadata or {}).get("provider_usage") or {}).items():
            usage[key] = usage.get(key, 0) + value
    charged_from_ledger = -sum(row["amount_cents"] for row in ledger if row["kind"] == "intelligence_charge" and row["status"] == "posted")
    return {
        "organization_id": organization_id,
        "stripe_customer_id_present": bool(organization.stripe_customer_id),
        "wallet": {"balance_cents": int(wallet.balance_cents), "lifetime_funded_cents": int(wallet.lifetime_funded_cents),
                   "lifetime_spent_cents": int(wallet.lifetime_spent_cents)},
        "ledger": ledger,
        "completed_runs": {"count": int(runs[0]), "charged_cents": int(runs[1])},
        "provider_usage_totals": usage,
        "checks": {
            "balance_matches_posted_ledger": int(wallet.balance_cents) == posted,
            "completed_runs_match_ledger_charges": int(runs[1]) == charged_from_ledger,
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
