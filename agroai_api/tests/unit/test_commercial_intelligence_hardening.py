from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from app.api.v1 import commercial_intelligence as legacy
from app.api.v1 import commercial_intelligence_hardened as hardened
from app.api.v1 import commercial_intelligence_input_guard as input_guard
from app.api.v1 import commercial_intelligence_key_guard as key_guard
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
