from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import commercial_intelligence_hardened as hardened
from app.models.intelligence_commerce import IntelligenceWallet, IntelligenceWalletLedger
from app.models.saas import Organization, User


POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="PLATFORM_API_POSTGRES_TEST_URL is not configured",
)


def test_paid_checkout_is_credited_exactly_once_under_concurrent_sync(monkeypatch):
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    seed = Session()
    suffix = uuid.uuid4().hex

    user = User(
        email=f"intelligence-wallet-{suffix}@example.com",
        password_hash="x",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    seed.add(user)
    seed.flush()
    organization = Organization(
        name="Intelligence wallet concurrency",
        slug=f"intelligence-wallet-{suffix}",
        owner_user_id=user.id,
        plan="enterprise",
        subscription_status="active",
    )
    seed.add(organization)
    seed.flush()
    wallet = IntelligenceWallet(
        organization_id=organization.id,
        currency="usd",
        balance_cents=0,
        lifetime_funded_cents=0,
        lifetime_spent_cents=0,
    )
    seed.add(wallet)
    seed.flush()
    ledger = IntelligenceWalletLedger(
        organization_id=organization.id,
        wallet_id=wallet.id,
        kind="topup",
        status="pending",
        amount_cents=1000,
        idempotency_key=f"checkout:{suffix}",
        external_reference=f"cs_test_{suffix}",
        metadata_json={},
    )
    seed.add(ledger)
    seed.commit()

    monkeypatch.setattr(hardened.legacy.settings, "PLATFORM_API_BILLING_ENABLED", True)
    monkeypatch.setattr(
        hardened.legacy.settings,
        "PLATFORM_API_STRIPE_SECRET_KEY",
        "sk_test_concurrency_only",
    )

    retrieve_barrier = threading.Barrier(2)

    def fake_retrieve(session_id: str):
        assert session_id == ledger.external_reference
        # Guarantee both independent DB sessions observed the pending candidate
        # before either reaches the row-level lock.
        retrieve_barrier.wait(timeout=10)
        return {
            "id": session_id,
            "payment_status": "paid",
            "status": "complete",
            "amount_subtotal": 1000,
            # Tax must never become wallet value.
            "amount_total": 1080,
            "currency": "usd",
            "metadata": {
                "organization_id": organization.id,
                "wallet_ledger_id": ledger.id,
            },
        }

    monkeypatch.setattr(hardened.stripe.checkout.Session, "retrieve", fake_retrieve)

    def reconcile() -> None:
        db = Session()
        try:
            hardened._sync_pending_topups(db, organization.id)
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reconcile) for _ in range(2)]
            for future in futures:
                future.result(timeout=20)

        verify = Session()
        try:
            stored_wallet = verify.get(IntelligenceWallet, wallet.id)
            stored_ledger = verify.get(IntelligenceWalletLedger, ledger.id)
            assert stored_wallet is not None
            assert stored_ledger is not None
            assert stored_wallet.balance_cents == 1000
            assert stored_wallet.lifetime_funded_cents == 1000
            assert stored_ledger.status == "posted"
            assert stored_ledger.posted_at is not None
            assert (
                verify.query(IntelligenceWalletLedger)
                .filter(
                    IntelligenceWalletLedger.organization_id == organization.id,
                    IntelligenceWalletLedger.external_reference == ledger.external_reference,
                    IntelligenceWalletLedger.status == "posted",
                )
                .count()
                == 1
            )
        finally:
            verify.close()
    finally:
        cleanup = Session()
        try:
            cleanup.query(IntelligenceWalletLedger).filter(
                IntelligenceWalletLedger.organization_id == organization.id
            ).delete(synchronize_session=False)
            cleanup.query(IntelligenceWallet).filter(
                IntelligenceWallet.organization_id == organization.id
            ).delete(synchronize_session=False)
            cleanup.query(Organization).filter(
                Organization.id == organization.id
            ).delete(synchronize_session=False)
            cleanup.query(User).filter(User.id == user.id).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()
            seed.close()
            engine.dispose()
