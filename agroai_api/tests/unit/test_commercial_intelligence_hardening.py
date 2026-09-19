from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import commercial_intelligence as legacy
from app.api.v1 import commercial_intelligence_hardened as hardened
from app.api.v1 import commercial_intelligence_input_guard as input_guard
from app.api.v1 import commercial_intelligence_key_guard as key_guard
from app.models.intelligence_commerce import CommercialIntelligenceRun, IntelligenceWallet, IntelligenceWalletLedger
from app.models.platform_api import ApiProject
from app.models.saas import ManagedEntity, Organization, User, Workspace
from app.platform_api.principal import PlatformPrincipal


def test_hardened_composition_replaces_money_moving_runtime() -> None:
    # Final call chain is credential guard -> hardened commercial executor.
    assert input_guard._original_execute_paid_intelligence is hardened._execute_paid_intelligence
    assert legacy._execute_paid_intelligence is input_guard._guarded_execute_paid_intelligence
    assert legacy._context is hardened._validate_and_build_context
    assert legacy._sync_pending_topups is hardened._sync_pending_topups
    assert legacy.create_platform_key is key_guard._bounded_create_platform_key


def test_customer_debit_occurs_only_after_model_result() -> None:
    source = inspect.getsource(hardened._execute_paid_intelligence)
    model_call = source.index("await legacy._run_ai")
    debit = source.index("locked_wallet.balance_cents -= price_cents")
    charge = source.index('kind="intelligence_charge"')
    assert model_call < debit < charge
    assert "context = _validate_and_build_context" in source[:model_call]


def test_workspace_boundary_is_server_authoritative() -> None:
    source = inspect.getsource(hardened._validate_and_build_context)
    assert "requested_workspace != key_workspace" in source
    assert "Workspace.organization_id == principal.organization_id" in source
    assert "project.organization_id != principal.organization_id" in source
    assert "project_workspace" in source
    assert "field.workspace_id != resolved_workspace" in source
    assert "key_workspace or project_workspace or requested_workspace" in source


def test_tax_reconciliation_uses_checkout_subtotal() -> None:
    source = inspect.getsource(hardened._sync_pending_topups)
    assert 'checkout.get("amount_subtotal")' in source
    assert "amount_subtotal != int(locked.amount_cents)" in source
    assert "amount_total < amount_subtotal" in source


def test_topup_reconciliation_locks_authoritative_row_before_credit() -> None:
    source = inspect.getsource(hardened._sync_pending_topups)
    scalar_candidates = source.index("IntelligenceWalletLedger.external_reference")
    row_lock = source.index(".with_for_update()")
    status_check = source.index('locked.status != "pending"')
    wallet_credit = source.index("wallet.balance_cents +=")
    assert scalar_candidates < row_lock < status_check < wallet_credit
    assert ".populate_existing()" in source
    assert "db.commit()" in source


def test_stale_run_recovery_cannot_leave_legacy_debit_posted() -> None:
    source = inspect.getsource(hardened._recover_if_stale)
    refund_source = inspect.getsource(hardened._refund_legacy_stranded_charge)
    assert "_refund_legacy_stranded_charge" in source
    assert 'charge.status = "reversed"' in refund_source
    assert 'kind="intelligence_refund"' in refund_source


def test_bootstrap_key_creation_is_bounded() -> None:
    source = inspect.getsource(key_guard._bounded_create_platform_key)
    assert "require_active_enrollment" in source
    assert 'resource_name="keys"' in source
    assert "current_count=active_count" in source
    assert "COMMERCIAL_ADVISORY_KEY_LIMIT" in source


def test_concurrent_idempotency_insert_is_resolved_without_second_run() -> None:
    source = inspect.getsource(hardened._execute_paid_intelligence)
    assert "except IntegrityError" in source
    assert "db.rollback()" in source
    assert "concurrent.request_hash != request_hash" in source
    assert '"intelligence_run_in_progress"' in source


def _tenant_context(db):
    owner_a = User(email="commercial-a@example.test", password_hash="x")
    owner_b = User(email="commercial-b@example.test", password_hash="x")
    db.add_all([owner_a, owner_b])
    db.flush()
    org_a = Organization(name="Commercial A", slug="commercial-a", owner_user_id=owner_a.id)
    org_b = Organization(name="Commercial B", slug="commercial-b", owner_user_id=owner_b.id)
    db.add_all([org_a, org_b])
    db.flush()
    ws_a = Workspace(organization_id=org_a.id, name="A")
    ws_a_other = Workspace(organization_id=org_a.id, name="A other")
    ws_b = Workspace(organization_id=org_b.id, name="B")
    db.add_all([ws_a, ws_a_other, ws_b])
    db.flush()
    project = ApiProject(
        organization_id=org_a.id,
        workspace_id=None,
        name="Intelligence",
        slug="intelligence",
        environment="live",
        status="active",
        default_rate_limit_policy={},
        created_by_user_id=owner_a.id,
    )
    db.add(project)
    db.flush()
    principal = PlatformPrincipal(
        authentication_type="portal_user",
        organization_id=org_a.id,
        api_project_id=project.id,
        scopes=frozenset({"intelligence:run"}),
        environment="live",
        request_id="tenant-test",
    )
    return org_a, org_b, ws_a, ws_a_other, ws_b, project, principal


def test_foreign_workspace_is_rejected_without_persistable_context(db) -> None:
    _org_a, _org_b, _ws_a, _ws_a_other, ws_b, _project, principal = _tenant_context(db)
    payload = legacy.IntelligenceRequest(
        task="answer",
        question="What needs attention?",
        input={"crop": "almond"},
        workspace_id=ws_b.id,
    )
    with pytest.raises(HTTPException) as excinfo:
        hardened._validate_and_build_context(db, principal, payload)
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "workspace_not_found"


def test_field_workspace_mismatch_is_rejected(db) -> None:
    org_a, _org_b, ws_a, ws_a_other, _ws_b, project, principal = _tenant_context(db)
    field = ManagedEntity(
        organization_id=org_a.id,
        workspace_id=ws_a.id,
        entity_type="platform_field",
        external_id="field-one",
        display_name="Field One",
        status="active",
        metadata_json={"api_project_id": project.id, "crop": "almond"},
    )
    db.add(field)
    db.flush()
    payload = legacy.IntelligenceRequest(
        task="field_diagnosis",
        question="What needs attention?",
        input={"crop": "almond"},
        workspace_id=ws_a_other.id,
        field_id=field.id,
    )
    with pytest.raises(HTTPException) as excinfo:
        hardened._validate_and_build_context(db, principal, payload)
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "field_not_found"


def test_same_org_workspace_is_canonicalized_into_context(db) -> None:
    _org_a, _org_b, ws_a, _ws_a_other, _ws_b, _project, principal = _tenant_context(db)
    payload = legacy.IntelligenceRequest(
        task="answer",
        question="Summarize this field context.",
        input={"crop": "almond"},
        workspace_id=ws_a.id,
    )
    context = hardened._validate_and_build_context(db, principal, payload)
    assert context.workspace_id == ws_a.id


def _fund_wallet(db, organization_id: str, cents: int = 100) -> IntelligenceWallet:
    wallet = IntelligenceWallet(
        organization_id=organization_id,
        currency="usd",
        balance_cents=cents,
        lifetime_funded_cents=cents,
        lifetime_spent_cents=0,
    )
    db.add(wallet)
    db.commit()
    return wallet


@pytest.mark.asyncio
async def test_successful_intelligence_charges_once_and_replays_without_provider_rerun(db, monkeypatch) -> None:
    org_a, _org_b, _ws_a, _ws_a_other, _ws_b, _project, principal = _tenant_context(db)
    wallet = _fund_wallet(db, org_a.id)
    calls = 0

    async def model_ok(**_kwargs):
        nonlocal calls
        calls += 1
        return (
            {"answer": "Review the irrigation evidence.", "confidence": "medium"},
            SimpleNamespace(status="ok", demo_fallback=False, provider="test-provider", model="test-model"),
        )

    monkeypatch.setattr(legacy, "_run_ai", model_ok)
    payload = legacy.IntelligenceRequest(
        task="answer",
        question="What needs attention?",
        input={"crop": "almond"},
    )
    first = await hardened._execute_paid_intelligence(
        payload=payload,
        idempotency_key="success-once",
        principal=principal,
        db=db,
    )
    replay = await hardened._execute_paid_intelligence(
        payload=payload,
        idempotency_key="success-once",
        principal=principal,
        db=db,
    )
    db.refresh(wallet)
    assert calls == 1
    assert first == replay
    assert first["billing"]["charged_cents"] == legacy.TASK_CATALOG["answer"]["price_cents"]
    assert wallet.balance_cents == 100 - legacy.TASK_CATALOG["answer"]["price_cents"]
    assert wallet.lifetime_spent_cents == legacy.TASK_CATALOG["answer"]["price_cents"]
    assert (
        db.query(IntelligenceWalletLedger)
        .filter(
            IntelligenceWalletLedger.organization_id == org_a.id,
            IntelligenceWalletLedger.kind == "intelligence_charge",
            IntelligenceWalletLedger.status == "posted",
        )
        .count()
        == 1
    )


@pytest.mark.asyncio
async def test_degraded_intelligence_is_persisted_without_charge(db, monkeypatch) -> None:
    org_a, _org_b, _ws_a, _ws_a_other, _ws_b, _project, principal = _tenant_context(db)
    wallet = _fund_wallet(db, org_a.id)

    async def degraded(**_kwargs):
        return (
            {"answer": "Provider fallback is unavailable.", "_safe_mode": True},
            SimpleNamespace(status="ok", demo_fallback=False, provider="safe", model="safe"),
        )

    monkeypatch.setattr(legacy, "_run_ai", degraded)
    payload = legacy.IntelligenceRequest(task="answer", question="What changed?", input={"crop": "almond"})
    result = await hardened._execute_paid_intelligence(
        payload=payload,
        idempotency_key="degraded-zero",
        principal=principal,
        db=db,
    )
    db.refresh(wallet)
    run = db.query(CommercialIntelligenceRun).filter(
        CommercialIntelligenceRun.idempotency_key == "degraded-zero"
    ).one()
    assert result["status"] == "degraded"
    assert result["billing"]["charged_cents"] == 0
    assert wallet.balance_cents == 100
    assert wallet.lifetime_spent_cents == 0
    assert run.status == "degraded"
    assert db.query(IntelligenceWalletLedger).filter(
        IntelligenceWalletLedger.intelligence_run_id == run.id
    ).count() == 0


@pytest.mark.asyncio
async def test_provider_failure_charges_zero_and_closes_run(db, monkeypatch) -> None:
    org_a, _org_b, _ws_a, _ws_a_other, _ws_b, _project, principal = _tenant_context(db)
    wallet = _fund_wallet(db, org_a.id)

    async def provider_failure(**_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(legacy, "_run_ai", provider_failure)
    payload = legacy.IntelligenceRequest(task="answer", question="What changed?", input={"crop": "almond"})
    with pytest.raises(HTTPException) as excinfo:
        await hardened._execute_paid_intelligence(
            payload=payload,
            idempotency_key="provider-failure-zero",
            principal=principal,
            db=db,
        )
    assert excinfo.value.status_code == 503
    db.refresh(wallet)
    run = db.query(CommercialIntelligenceRun).filter(
        CommercialIntelligenceRun.idempotency_key == "provider-failure-zero"
    ).one()
    assert wallet.balance_cents == 100
    assert wallet.lifetime_spent_cents == 0
    assert run.status == "failed"
    assert db.query(IntelligenceWalletLedger).filter(
        IntelligenceWalletLedger.intelligence_run_id == run.id
    ).count() == 0


@pytest.mark.asyncio
async def test_balance_change_during_inference_fails_without_charge(db, monkeypatch) -> None:
    org_a, _org_b, _ws_a, _ws_a_other, _ws_b, _project, principal = _tenant_context(db)
    wallet = _fund_wallet(db, org_a.id)

    async def consume_balance_elsewhere(**_kwargs):
        locked = legacy._wallet(db, org_a.id, lock=True)
        locked.balance_cents = 0
        db.commit()
        return (
            {"answer": "A valid result was computed."},
            SimpleNamespace(status="ok", demo_fallback=False, provider="test-provider", model="test-model"),
        )

    monkeypatch.setattr(legacy, "_run_ai", consume_balance_elsewhere)
    payload = legacy.IntelligenceRequest(task="answer", question="What changed?", input={"crop": "almond"})
    with pytest.raises(HTTPException) as excinfo:
        await hardened._execute_paid_intelligence(
            payload=payload,
            idempotency_key="balance-changed",
            principal=principal,
            db=db,
        )
    assert excinfo.value.status_code == 402
    db.refresh(wallet)
    run = db.query(CommercialIntelligenceRun).filter(
        CommercialIntelligenceRun.idempotency_key == "balance-changed"
    ).one()
    assert wallet.balance_cents == 0
    assert wallet.lifetime_spent_cents == 0
    assert run.status == "failed"
    assert run.error_code == "insufficient_balance_at_completion"
    assert db.query(IntelligenceWalletLedger).filter(
        IntelligenceWalletLedger.intelligence_run_id == run.id
    ).count() == 0


@pytest.mark.parametrize(
    ("case", "checkout_overrides", "expected_status"),
    [
        ("wrong_org", {"metadata": {"organization_id": "foreign-org"}}, "review_required"),
        ("wrong_ledger", {"metadata": {"wallet_ledger_id": "foreign-ledger"}}, "review_required"),
        ("wrong_currency", {"currency": "eur"}, "review_required"),
        ("wrong_subtotal", {"amount_subtotal": 999}, "review_required"),
        ("expired_unpaid", {"status": "expired", "payment_status": "unpaid"}, "expired"),
        ("complete_unpaid", {"status": "complete", "payment_status": "unpaid"}, "pending"),
    ],
)
def test_topup_reconciliation_rejects_invalid_stripe_state(
    db,
    monkeypatch,
    case: str,
    checkout_overrides: dict,
    expected_status: str,
) -> None:
    org_a, _org_b, _ws_a, _ws_a_other, _ws_b, _project, _principal = _tenant_context(db)
    wallet = _fund_wallet(db, org_a.id, cents=0)
    ledger = IntelligenceWalletLedger(
        organization_id=org_a.id,
        wallet_id=wallet.id,
        kind="topup",
        status="pending",
        amount_cents=1000,
        idempotency_key=f"topup-{case}",
        external_reference=f"cs_{case}",
        metadata_json={},
    )
    db.add(ledger)
    db.commit()

    monkeypatch.setattr(legacy.settings, "PLATFORM_API_BILLING_ENABLED", True)
    monkeypatch.setattr(legacy.settings, "PLATFORM_API_STRIPE_SECRET_KEY", "sk_test_reconciliation")

    checkout = {
        "payment_status": "paid",
        "status": "complete",
        "amount_subtotal": 1000,
        "amount_total": 1080,
        "currency": "usd",
        "metadata": {
            "organization_id": org_a.id,
            "wallet_ledger_id": ledger.id,
        },
    }
    checkout.update(checkout_overrides)
    # Partial metadata overrides deliberately preserve the non-target field.
    if case == "wrong_org":
        checkout["metadata"] = {
            "organization_id": "foreign-org",
            "wallet_ledger_id": ledger.id,
        }
    if case == "wrong_ledger":
        checkout["metadata"] = {
            "organization_id": org_a.id,
            "wallet_ledger_id": "foreign-ledger",
        }

    monkeypatch.setattr(
        hardened.stripe.checkout.Session,
        "retrieve",
        lambda session_id: checkout,
    )
    hardened._sync_pending_topups(db, org_a.id)
    db.refresh(wallet)
    db.refresh(ledger)
    assert ledger.status == expected_status
    assert wallet.balance_cents == 0
    assert wallet.lifetime_funded_cents == 0
