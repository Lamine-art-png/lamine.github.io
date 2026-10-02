from __future__ import annotations

import asyncio
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import commercial_intelligence as legacy
from app.api.v1 import commercial_intelligence_hardened as hardened
from app.models.intelligence_commerce import CommercialIntelligenceRun, IntelligenceWallet, IntelligenceWalletLedger
from app.models.platform_api import ApiProject
from app.models.saas import Organization, User
from app.platform_api.principal import PlatformPrincipal


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



def test_concurrent_identical_idempotent_runs_execute_and_charge_once(monkeypatch):
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    seed = Session()
    suffix = uuid.uuid4().hex

    user = User(
        email=f"intelligence-idempotency-{suffix}@example.com",
        password_hash="x",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    seed.add(user)
    seed.flush()
    organization = Organization(
        name="Intelligence idempotency concurrency",
        slug=f"intelligence-idempotency-{suffix}",
        owner_user_id=user.id,
        plan="enterprise",
        subscription_status="active",
    )
    seed.add(organization)
    seed.flush()
    project = ApiProject(
        organization_id=organization.id,
        workspace_id=None,
        name="Intelligence",
        slug="intelligence",
        environment="live",
        status="active",
        default_rate_limit_policy={},
        created_by_user_id=user.id,
    )
    wallet = IntelligenceWallet(
        organization_id=organization.id,
        currency="usd",
        balance_cents=100,
        lifetime_funded_cents=100,
        lifetime_spent_cents=0,
    )
    seed.add_all([project, wallet])
    seed.commit()

    payload = legacy.IntelligenceRequest(
        task="answer",
        question="What needs attention in this almond block?",
        input={"crop": "almond", "soil_moisture_pct": 23.4},
    )
    principal = PlatformPrincipal(
        authentication_type="portal_user",
        organization_id=organization.id,
        api_project_id=project.id,
        user_id=user.id,
        scopes=frozenset({"intelligence:run"}),
        environment="live",
        request_id=f"idem-{suffix}",
    )
    provider_started = threading.Event()
    release_provider = threading.Event()
    provider_calls = 0
    provider_calls_lock = threading.Lock()

    async def model_ok(**_kwargs):
        nonlocal provider_calls
        with provider_calls_lock:
            provider_calls += 1
        provider_started.set()
        assert release_provider.wait(timeout=15)
        return (
            {"answer": "Review the irrigation evidence.", "confidence": "medium"},
            SimpleNamespace(status="ok", demo_fallback=False, provider="test-provider", model="test-model"),
        )

    monkeypatch.setattr(legacy, "_run_ai", model_ok)

    def execute():
        db = Session()
        try:
            return asyncio.run(
                hardened._execute_paid_intelligence(
                    payload=payload,
                    idempotency_key=f"same-{suffix}",
                    principal=principal,
                    db=db,
                )
            )
        except HTTPException as exc:
            return exc
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(execute)
            assert provider_started.wait(timeout=15)
            second = pool.submit(execute)
            second_result = second.result(timeout=15)
            assert isinstance(second_result, HTTPException)
            assert second_result.status_code == 409
            assert second_result.detail["code"] == "intelligence_run_in_progress"
            release_provider.set()
            first_result = first.result(timeout=20)

        assert isinstance(first_result, dict)
        assert provider_calls == 1

        verify = Session()
        try:
            stored_wallet = verify.get(IntelligenceWallet, wallet.id)
            assert stored_wallet is not None
            assert stored_wallet.balance_cents == 100 - legacy.TASK_CATALOG["answer"]["price_cents"]
            assert stored_wallet.lifetime_spent_cents == legacy.TASK_CATALOG["answer"]["price_cents"]
            runs = (
                verify.query(CommercialIntelligenceRun)
                .filter(
                    CommercialIntelligenceRun.organization_id == organization.id,
                    CommercialIntelligenceRun.api_project_id == project.id,
                    CommercialIntelligenceRun.idempotency_key == f"same-{suffix}",
                )
                .all()
            )
            assert len(runs) == 1
            assert runs[0].status == "completed"
            assert (
                verify.query(IntelligenceWalletLedger)
                .filter(
                    IntelligenceWalletLedger.organization_id == organization.id,
                    IntelligenceWalletLedger.kind == "intelligence_charge",
                    IntelligenceWalletLedger.status == "posted",
                    IntelligenceWalletLedger.intelligence_run_id == runs[0].id,
                )
                .count()
                == 1
            )
        finally:
            verify.close()
    finally:
        release_provider.set()
        cleanup = Session()
        try:
            cleanup.query(IntelligenceWalletLedger).filter(
                IntelligenceWalletLedger.organization_id == organization.id
            ).delete(synchronize_session=False)
            cleanup.query(CommercialIntelligenceRun).filter(
                CommercialIntelligenceRun.organization_id == organization.id
            ).delete(synchronize_session=False)
            cleanup.query(IntelligenceWallet).filter(
                IntelligenceWallet.organization_id == organization.id
            ).delete(synchronize_session=False)
            cleanup.query(ApiProject).filter(
                ApiProject.organization_id == organization.id
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


def _seed_paid_org(Session, *, balance_cents: int | None, label: str):
    seed = Session()
    try:
        suffix = uuid.uuid4().hex
        user = User(
            email=f"intelligence-{label}-{suffix}@example.com",
            password_hash="x",
            email_verification_status="verified",
            email_verified_at=datetime.utcnow(),
        )
        seed.add(user)
        seed.flush()
        organization = Organization(
            name=f"Intelligence {label}",
            slug=f"intelligence-{label}-{suffix}",
            owner_user_id=user.id,
            plan="enterprise",
            subscription_status="active",
        )
        seed.add(organization)
        seed.flush()
        project = ApiProject(
            organization_id=organization.id,
            workspace_id=None,
            name="Intelligence",
            slug="intelligence",
            environment="live",
            status="active",
            default_rate_limit_policy={},
            created_by_user_id=user.id,
        )
        seed.add(project)
        if balance_cents is not None:
            seed.add(
                IntelligenceWallet(
                    organization_id=organization.id,
                    currency="usd",
                    balance_cents=balance_cents,
                    lifetime_funded_cents=balance_cents,
                    lifetime_spent_cents=0,
                )
            )
        seed.commit()
        principal = PlatformPrincipal(
            authentication_type="portal_user",
            organization_id=organization.id,
            api_project_id=project.id,
            user_id=user.id,
            scopes=frozenset({"intelligence:run"}),
            environment="live",
            request_id=f"{label}-{suffix}",
        )
        return user.id, organization.id, project.id, principal
    finally:
        seed.close()


def _cleanup_org(Session, organization_id: str, user_id: str) -> None:
    cleanup = Session()
    try:
        for model in (IntelligenceWalletLedger, CommercialIntelligenceRun, IntelligenceWallet, ApiProject):
            cleanup.query(model).filter(model.organization_id == organization_id).delete(synchronize_session=False)
        cleanup.query(Organization).filter(Organization.id == organization_id).delete(synchronize_session=False)
        cleanup.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        cleanup.commit()
    finally:
        cleanup.close()


def test_concurrent_distinct_runs_cannot_overdraw_the_wallet(monkeypatch):
    """Both runs pass the pre-inference balance check; only one may be paid.

    expire_on_commit=False keeps the pre-check's wallet in the identity map, so
    this also proves the locked debit re-reads the row it locked instead of
    relying on a session setting to discard stale balances.
    """
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    price = legacy.TASK_CATALOG["irrigation_plan"]["price_cents"]
    user_id, organization_id, _project_id, principal = _seed_paid_org(Session, balance_cents=price, label="overdraw")
    both_inferring = threading.Barrier(2)

    async def model_ok(**_kwargs):
        # Each request has already passed its balance pre-check.
        both_inferring.wait(timeout=15)
        return (
            {"recommendation": "Irrigate 18 mm tonight.", "confidence": "medium"},
            SimpleNamespace(status="ok", demo_fallback=False, provider="test-provider", model="test-model"),
        )

    monkeypatch.setattr(legacy, "_run_ai", model_ok)
    payload = legacy.IntelligenceRequest(task="irrigation_plan", question="Plan irrigation", input={"crop": "almond"})

    def execute(key: str):
        db = Session()
        try:
            return asyncio.run(
                hardened._execute_paid_intelligence(payload=payload, idempotency_key=key, principal=principal, db=db)
            )
        except HTTPException as exc:
            return exc
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute, ["overdraw-a", "overdraw-b"], timeout=30))
        paid = [item for item in results if isinstance(item, dict)]
        refused = [item for item in results if isinstance(item, HTTPException)]
        assert len(paid) == 1 and len(refused) == 1, results
        assert refused[0].status_code == 402
        assert refused[0].detail["code"] == "insufficient_intelligence_balance"

        verify = Session()
        try:
            wallet = verify.query(IntelligenceWallet).filter_by(organization_id=organization_id).one()
            assert wallet.balance_cents == 0
            assert wallet.lifetime_spent_cents == price
            charges = verify.query(IntelligenceWalletLedger).filter_by(
                organization_id=organization_id, kind="intelligence_charge"
            ).all()
            assert [row.amount_cents for row in charges] == [-price]
            statuses = sorted(
                row.status for row in verify.query(CommercialIntelligenceRun).filter_by(organization_id=organization_id)
            )
            assert statuses == ["completed", "failed"]
        finally:
            verify.close()
    finally:
        _cleanup_org(Session, organization_id, user_id)
        engine.dispose()


def test_postgres_rejects_negative_balances_and_wrong_sign_ledger_rows():
    """Money invariants hold even for a code path that skips the balance check."""
    from sqlalchemy.exc import IntegrityError

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, organization_id, _project_id, _principal = _seed_paid_org(Session, balance_cents=10, label="checks")
    try:
        db = Session()
        try:
            wallet = db.query(IntelligenceWallet).filter_by(organization_id=organization_id).one()
            wallet.balance_cents -= 11
            with pytest.raises(IntegrityError, match="ck_intelligence_wallet_balance_nonnegative"):
                db.commit()
            db.rollback()

            wallet = db.query(IntelligenceWallet).filter_by(organization_id=organization_id).one()
            wallet.lifetime_spent_cents = -1
            with pytest.raises(IntegrityError, match="ck_intelligence_wallet_spent_nonnegative"):
                db.commit()
            db.rollback()

            wallet = db.query(IntelligenceWallet).filter_by(organization_id=organization_id).one()
            for kind, amount in (("intelligence_charge", 5), ("topup", -500), ("intelligence_refund", -5), ("topup", 0)):
                db.add(
                    IntelligenceWalletLedger(
                        organization_id=organization_id,
                        wallet_id=wallet.id,
                        kind=kind,
                        status="posted",
                        amount_cents=amount,
                        idempotency_key=f"sign-{kind}-{amount}-{uuid.uuid4().hex}",
                        metadata_json={},
                    )
                )
                with pytest.raises(IntegrityError, match="ck_intelligence_wallet_ledger_amount_sign"):
                    db.commit()
                db.rollback()
                wallet = db.query(IntelligenceWallet).filter_by(organization_id=organization_id).one()

            assert wallet.balance_cents == 10
        finally:
            db.close()
    finally:
        _cleanup_org(Session, organization_id, user_id)
        engine.dispose()


def test_concurrent_first_wallet_creation_yields_one_wallet():
    """Two first requests race the one-wallet-per-organization constraint."""
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, organization_id, _project_id, _principal = _seed_paid_org(Session, balance_cents=None, label="first-wallet")
    first_inserted = threading.Event()
    second_started = threading.Event()

    def first():
        db = Session()
        try:
            row = legacy._wallet(db, organization_id, lock=True)
            # Hold the uncommitted insert so the second request cannot see it
            # and must collide with it on the unique constraint.
            first_inserted.set()
            assert second_started.wait(timeout=10)
            threading.Event().wait(0.5)
            db.commit()
            return row.id
        finally:
            db.close()

    def second():
        assert first_inserted.wait(timeout=10)
        db = Session()
        try:
            second_started.set()
            row = legacy._wallet(db, organization_id, lock=True)
            row_id = row.id
            db.commit()
            return row_id
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(first)
            second_future = pool.submit(second)
            first_id = first_future.result(timeout=20)
            second_id = second_future.result(timeout=20)
        assert first_id == second_id
        verify = Session()
        try:
            assert verify.query(IntelligenceWallet).filter_by(organization_id=organization_id).count() == 1
        finally:
            verify.close()
    finally:
        _cleanup_org(Session, organization_id, user_id)
        engine.dispose()
