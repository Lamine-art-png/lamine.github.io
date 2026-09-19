"""Production hardening for the prepaid AGRO-AI Intelligence surface.

This module deliberately patches the commercial surface at the composition
boundary so the public contract remains small while money movement, workspace
isolation, Stripe reconciliation, and crash recovery obey stronger invariants.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import stripe
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1 import commercial_intelligence as legacy
from app.models.intelligence_commerce import CommercialIntelligenceRun, IntelligenceWalletLedger
from app.models.operational_records import EvidenceRecord
from app.models.platform_api import ApiProject, PlatformApiKey
from app.models.saas import ManagedEntity, Workspace
from app.platform_api.principal import PlatformPrincipal
from app.schemas.ai import EvidenceContext, ToolCitation


router = legacy.router
_STALE_RUN_AFTER = timedelta(minutes=10)

# Keep original helpers before replacing the module globals used by FastAPI
# endpoint functions.
_original_context = legacy._context


def _validate_and_build_context(
    db: Session,
    principal: PlatformPrincipal,
    payload: legacy.IntelligenceRequest,
) -> EvidenceContext:
    """Resolve tenant, project, field, and workspace authorization before any customer money moves."""
    if not principal.organization_id or not principal.api_project_id:
        raise HTTPException(status_code=401, detail={"code": "invalid_principal"})

    project = db.get(ApiProject, principal.api_project_id)
    if project is None or project.organization_id != principal.organization_id or project.status != "active":
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found"})

    key_workspace = principal.workspace_id
    requested_workspace = payload.workspace_id
    project_workspace = project.workspace_id

    if key_workspace and requested_workspace and requested_workspace != key_workspace:
        raise HTTPException(status_code=403, detail={"code": "workspace_restricted"})
    if project_workspace and key_workspace and project_workspace != key_workspace:
        raise HTTPException(status_code=403, detail={"code": "workspace_restricted"})
    if project_workspace and requested_workspace and project_workspace != requested_workspace:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found"})

    def owned_workspace(workspace_id: str | None) -> Workspace | None:
        if not workspace_id:
            return None
        return (
            db.query(Workspace)
            .filter(
                Workspace.id == workspace_id,
                Workspace.organization_id == principal.organization_id,
            )
            .first()
        )

    for workspace_id in (key_workspace, project_workspace, requested_workspace):
        if workspace_id and owned_workspace(workspace_id) is None:
            # Do not disclose whether a foreign-tenant workspace exists.
            raise HTTPException(status_code=404, detail={"code": "workspace_not_found"})

    field: ManagedEntity | None = None
    if payload.field_id:
        field = (
            db.query(ManagedEntity)
            .filter(
                ManagedEntity.id == payload.field_id,
                ManagedEntity.organization_id == principal.organization_id,
                ManagedEntity.entity_type == "platform_field",
            )
            .first()
        )
        if field is None:
            raise HTTPException(status_code=404, detail={"code": "field_not_found"})
        metadata = dict(field.metadata_json or {})
        field_project_id = str(metadata.get("api_project_id") or "")
        if field_project_id and field_project_id != principal.api_project_id:
            raise HTTPException(status_code=404, detail={"code": "field_not_found"})
        if field.workspace_id and owned_workspace(field.workspace_id) is None:
            raise HTTPException(status_code=404, detail={"code": "field_not_found"})

    resolved_workspace = key_workspace or project_workspace or requested_workspace or (field.workspace_id if field else None)
    if field is not None and field.workspace_id and resolved_workspace and field.workspace_id != resolved_workspace:
        raise HTTPException(status_code=404, detail={"code": "field_not_found"})

    normalized = payload.model_copy(update={"workspace_id": resolved_workspace})
    return _original_context(db, principal, normalized)

def _sync_pending_topups(db: Session, organization_id: str) -> None:
    """Reconcile Stripe top-ups exactly once; tax is paid but never wallet value."""
    secret = str(getattr(legacy.settings, "PLATFORM_API_STRIPE_SECRET_KEY", "") or "").strip()
    if not secret or not bool(getattr(legacy.settings, "PLATFORM_API_BILLING_ENABLED", False)):
        return
    stripe.api_key = secret

    # Read only scalar candidates here. Do not identity-load pending ORM rows
    # before the authoritative FOR UPDATE read below; that avoids stale state
    # surviving in SQLAlchemy's identity map across concurrent reconciliation.
    candidates = (
        db.query(
            IntelligenceWalletLedger.id,
            IntelligenceWalletLedger.external_reference,
        )
        .filter(
            IntelligenceWalletLedger.organization_id == organization_id,
            IntelligenceWalletLedger.kind == "topup",
            IntelligenceWalletLedger.status == "pending",
            IntelligenceWalletLedger.external_reference.isnot(None),
        )
        .order_by(IntelligenceWalletLedger.created_at.asc())
        .limit(20)
        .all()
    )

    for ledger_id, external_reference in candidates:
        try:
            checkout = stripe.checkout.Session.retrieve(external_reference)
        except stripe.error.StripeError:
            db.rollback()
            continue

        # This is the authoritative eligibility read. populate_existing forces
        # state refresh even if this Session ever acquired the row elsewhere.
        locked = (
            db.query(IntelligenceWalletLedger)
            .filter(
                IntelligenceWalletLedger.id == ledger_id,
                IntelligenceWalletLedger.organization_id == organization_id,
                IntelligenceWalletLedger.kind == "topup",
            )
            .with_for_update()
            .populate_existing()
            .first()
        )
        if locked is None or locked.status != "pending":
            db.rollback()
            continue

        payment_status = str(checkout.get("payment_status") or "")
        checkout_status = str(checkout.get("status") or "")
        amount_subtotal = int(checkout.get("amount_subtotal") or 0)
        amount_total = int(checkout.get("amount_total") or 0)
        currency = str(checkout.get("currency") or "").lower()
        metadata = dict(checkout.get("metadata") or {})

        if checkout_status == "expired" and payment_status != "paid":
            locked.status = "expired"
            db.commit()
            continue
        if payment_status != "paid":
            db.rollback()
            continue

        # Stripe amount_total includes automatic tax. Wallet value is strictly
        # the purchased intelligence subtotal.
        if (
            amount_subtotal != int(locked.amount_cents)
            or amount_total < amount_subtotal
            or currency != "usd"
        ):
            locked.status = "review_required"
            locked.metadata_json = {
                **dict(locked.metadata_json or {}),
                "reconciliation_error": "subtotal_total_or_currency_mismatch",
                "stripe_amount_subtotal": amount_subtotal,
                "stripe_amount_total": amount_total,
            }
            db.commit()
            continue

        if metadata.get("organization_id") != organization_id or metadata.get("wallet_ledger_id") != locked.id:
            locked.status = "review_required"
            locked.metadata_json = {
                **dict(locked.metadata_json or {}),
                "reconciliation_error": "metadata_mismatch",
            }
            db.commit()
            continue

        wallet = legacy._wallet(db, organization_id, lock=True)
        wallet.balance_cents += int(locked.amount_cents)
        wallet.lifetime_funded_cents += int(locked.amount_cents)
        wallet.updated_at = datetime.utcnow()
        locked.status = "posted"
        locked.posted_at = datetime.utcnow()
        db.commit()
"""Production hardening for the prepaid AGRO-AI Intelligence surface.

This module deliberately patches the commercial surface at the composition
boundary so the public contract remains small while money movement, workspace
isolation, Stripe reconciliation, and crash recovery obey stronger invariants.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import stripe
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1 import commercial_intelligence as legacy
from app.models.intelligence_commerce import CommercialIntelligenceRun, IntelligenceWalletLedger
from app.models.operational_records import EvidenceRecord
from app.models.platform_api import ApiProject, PlatformApiKey
from app.models.saas import ManagedEntity, Workspace
from app.platform_api.principal import PlatformPrincipal
from app.schemas.ai import EvidenceContext, ToolCitation


router = legacy.router
_STALE_RUN_AFTER = timedelta(minutes=10)

# Keep original helpers before replacing the module globals used by FastAPI
# endpoint functions.
_original_context = legacy._context


def _validate_and_build_context(
    db: Session,
    principal: PlatformPrincipal,
    payload: legacy.IntelligenceRequest,
) -> EvidenceContext:
    """Resolve tenant, project, field, and workspace authorization before any customer money moves."""
    if not principal.organization_id or not principal.api_project_id:
        raise HTTPException(status_code=401, detail={"code": "invalid_principal"})

    project = db.get(ApiProject, principal.api_project_id)
    if project is None or project.organization_id != principal.organization_id or project.status != "active":
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found"})

    key_workspace = principal.workspace_id
    requested_workspace = payload.workspace_id
    project_workspace = project.workspace_id

    if key_workspace and requested_workspace and requested_workspace != key_workspace:
        raise HTTPException(status_code=403, detail={"code": "workspace_restricted"})
    if project_workspace and key_workspace and project_workspace != key_workspace:
        raise HTTPException(status_code=403, detail={"code": "workspace_restricted"})
    if project_workspace and requested_workspace and project_workspace != requested_workspace:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found"})

    def owned_workspace(workspace_id: str | None) -> Workspace | None:
        if not workspace_id:
            return None
        return (
            db.query(Workspace)
            .filter(
                Workspace.id == workspace_id,
                Workspace.organization_id == principal.organization_id,
            )
            .first()
        )

    for workspace_id in (key_workspace, project_workspace, requested_workspace):
        if workspace_id and owned_workspace(workspace_id) is None:
            # Do not disclose whether a foreign-tenant workspace exists.
            raise HTTPException(status_code=404, detail={"code": "workspace_not_found"})

    field: ManagedEntity | None = None
    if payload.field_id:
        field = (
            db.query(ManagedEntity)
            .filter(
                ManagedEntity.id == payload.field_id,
                ManagedEntity.organization_id == principal.organization_id,
                ManagedEntity.entity_type == "platform_field",
            )
            .first()
        )
        if field is None:
            raise HTTPException(status_code=404, detail={"code": "field_not_found"})
        metadata = dict(field.metadata_json or {})
        field_project_id = str(metadata.get("api_project_id") or "")
        if field_project_id and field_project_id != principal.api_project_id:
            raise HTTPException(status_code=404, detail={"code": "field_not_found"})
        if field.workspace_id and owned_workspace(field.workspace_id) is None:
            raise HTTPException(status_code=404, detail={"code": "field_not_found"})

    resolved_workspace = key_workspace or project_workspace or requested_workspace or (field.workspace_id if field else None)
    if field is not None and field.workspace_id and resolved_workspace and field.workspace_id != resolved_workspace:
        raise HTTPException(status_code=404, detail={"code": "field_not_found"})

    normalized = payload.model_copy(update={"workspace_id": resolved_workspace})
    return _original_context(db, principal, normalized)
def _sync_pending_topups(db: Session, organization_id: str) -> None:
    """Credit only the purchased subtotal; tax is paid but never wallet value."""
    secret = str(getattr(legacy.settings, "PLATFORM_API_STRIPE_SECRET_KEY", "") or "").strip()
    if not secret or not bool(getattr(legacy.settings, "PLATFORM_API_BILLING_ENABLED", False)):
        return
    stripe.api_key = secret
    pending = (
        db.query(IntelligenceWalletLedger)
        .filter(
            IntelligenceWalletLedger.organization_id == organization_id,
            IntelligenceWalletLedger.kind == "topup",
            IntelligenceWalletLedger.status == "pending",
            IntelligenceWalletLedger.external_reference.isnot(None),
        )
        .order_by(IntelligenceWalletLedger.created_at.asc())
        .limit(20)
        .all()
    )
    for item in pending:
        try:
            checkout = stripe.checkout.Session.retrieve(item.external_reference)
        except stripe.error.StripeError:
            continue
        payment_status = str(checkout.get("payment_status") or "")
        checkout_status = str(checkout.get("status") or "")
        amount_subtotal = int(checkout.get("amount_subtotal") or 0)
        amount_total = int(checkout.get("amount_total") or 0)
        currency = str(checkout.get("currency") or "").lower()
        metadata = dict(checkout.get("metadata") or {})
        if checkout_status == "expired" and payment_status != "paid":
            item.status = "expired"
            continue
        if payment_status != "paid":
            continue
        # Stripe amount_total includes automatic tax. The wallet represents the
        # purchased intelligence balance, so reconcile against amount_subtotal.
        if (
            amount_subtotal != int(item.amount_cents)
            or amount_total < amount_subtotal
            or currency != "usd"
        ):
            item.status = "review_required"
            item.metadata_json = {
                **dict(item.metadata_json or {}),
                "reconciliation_error": "subtotal_total_or_currency_mismatch",
                "stripe_amount_subtotal": amount_subtotal,
                "stripe_amount_total": amount_total,
            }
            continue
        if metadata.get("organization_id") != organization_id or metadata.get("wallet_ledger_id") != item.id:
            item.status = "review_required"
            item.metadata_json = {**dict(item.metadata_json or {}), "reconciliation_error": "metadata_mismatch"}
            continue
        locked = (
            db.query(IntelligenceWalletLedger)
            .filter(IntelligenceWalletLedger.id == item.id)
            .with_for_update()
            .first()
        )
        if locked is None or locked.status != "pending":
            continue
        wallet = legacy._wallet(db, organization_id, lock=True)
        wallet.balance_cents += int(locked.amount_cents)
        wallet.lifetime_funded_cents += int(locked.amount_cents)
        wallet.updated_at = datetime.utcnow()
        locked.status = "posted"
        locked.posted_at = datetime.utcnow()
    db.commit()

