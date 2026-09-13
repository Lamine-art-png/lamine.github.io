from __future__ import annotations

import inspect

from app.api.v1 import commercial_intelligence as legacy
from app.api.v1 import commercial_intelligence_hardened as hardened
from app.api.v1 import commercial_intelligence_key_guard as key_guard


def test_hardened_composition_replaces_money_moving_runtime() -> None:
    assert legacy._execute_paid_intelligence is hardened._execute_paid_intelligence
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
    assert "field.workspace_id != key_workspace" in source
    assert "key_workspace or requested_workspace" in source


def test_tax_reconciliation_uses_checkout_subtotal() -> None:
    source = inspect.getsource(hardened._sync_pending_topups)
    assert 'checkout.get("amount_subtotal")' in source
    assert "amount_subtotal != int(item.amount_cents)" in source
    assert "amount_total < amount_subtotal" in source


def test_stale_run_recovery_cannot_leave_legacy_debit_posted() -> None:
    source = inspect.getsource(hardened._recover_if_stale)
    refund_source = inspect.getsource(hardened._refund_legacy_stranded_charge)
    assert "_refund_legacy_stranded_charge" in source
    assert 'charge.status = "reversed"' in refund_source
    assert 'kind="intelligence_refund"' in refund_source


def test_bootstrap_key_creation_reuses_governing_limit() -> None:
    source = inspect.getsource(key_guard._bounded_create_platform_key)
    assert "require_active_enrollment" in source
    assert 'resource_name="keys"' in source
    assert "current_count=active_count" in source
