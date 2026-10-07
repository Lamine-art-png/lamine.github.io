"""Reconcile an event-observed AWS Marketplace license with current purchase state.

A registration token and an EventBridge notification are insufficient to grant
access. The agreement must be active for the expected buyer/product/license, and
the purchased AWS Marketplace dimension must map to an active AGRO-AI Platform
API plan.
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.core.config import settings
from app.models.aws_marketplace import AwsMarketplaceRegistration
from app.models.platform_product import PlatformApiPlan, PlatformApiSubscription


MARKETPLACE_PLAN_DIMENSIONS = frozenset({"developer", "scale"})


def agreement_is_active(client, row: AwsMarketplaceRegistration, product_id: str) -> bool:
    filters = [
        {"name": "AgreementType", "values": ["PurchaseAgreement"]},
        {"name": "PartyType", "values": ["Proposer"]},
        {"name": "LicenseArn", "values": [row.license_arn]},
    ]
    token = None
    while True:
        args = {"catalog": "AWSMarketplace", "filters": filters, "maxResults": 50}
        if token:
            args["nextToken"] = token
        page = client.search_agreements(**args)
        for agreement in page.get("agreementViewSummaries", []):
            if agreement.get("status") != "ACTIVE":
                continue
            if (agreement.get("acceptor") or {}).get("accountId") != row.customer_aws_account_id:
                continue
            resources = (agreement.get("proposalSummary") or {}).get("resources") or []
            if not any(resource.get("id") == product_id and resource.get("type") == "SaaSProduct" for resource in resources):
                continue
            if not any(item.get("licenseArn") == row.license_arn for item in agreement.get("entitlements") or []):
                continue
            entitlement_token = None
            while True:
                entitlement_args = {"agreementId": agreement["agreementId"], "maxResults": 50}
                if entitlement_token:
                    entitlement_args["nextToken"] = entitlement_token
                entitlements = client.get_agreement_entitlements(**entitlement_args)
                if any(
                    item.get("licenseArn") == row.license_arn
                    and item.get("status") == "PROVISIONED"
                    and (item.get("resource") or {}).get("id") == product_id
                    for item in entitlements.get("agreementEntitlements", [])
                ):
                    return True
                entitlement_token = entitlements.get("nextToken")
                if not entitlement_token:
                    break
        token = page.get("nextToken")
        if not token:
            return False


def _naive_utc(value):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _entitlement_value_positive(value) -> bool:
    if not isinstance(value, dict):
        return False
    if "BooleanValue" in value:
        return value.get("BooleanValue") is True
    if "IntegerValue" in value:
        try:
            return int(value.get("IntegerValue")) > 0
        except (TypeError, ValueError):
            return False
    if "DoubleValue" in value:
        try:
            return float(value.get("DoubleValue")) > 0
        except (TypeError, ValueError):
            return False
    if "StringValue" in value:
        raw = str(value.get("StringValue") or "").strip().lower()
        return raw not in {"", "0", "false", "none", "null"}
    return False


def marketplace_plan_entitlement(client, row: AwsMarketplaceRegistration, product_code: str) -> tuple[str | None, datetime | None]:
    """Return the single active AGRO-AI Marketplace plan dimension for a license.

    New AWS Marketplace integrations should prefer CustomerAWSAccountId or
    LicenseArn. We filter by the exact license and still re-check the returned
    buyer/product identity before trusting a dimension.
    """
    if not product_code:
        return None, None
    token = None
    found: dict[str, datetime | None] = {}
    now = datetime.utcnow()
    while True:
        args = {
            "ProductCode": product_code,
            "Filter": {"LICENSE_ARN": [row.license_arn]},
            "MaxResults": 25,
        }
        if token:
            args["NextToken"] = token
        page = client.get_entitlements(**args)
        for item in page.get("Entitlements", []):
            if item.get("LicenseArn") != row.license_arn:
                continue
            returned_account = str(item.get("CustomerAWSAccountId") or "")
            if returned_account and returned_account != row.customer_aws_account_id:
                continue
            returned_product = str(item.get("ProductCode") or "")
            if returned_product and returned_product != product_code:
                continue
            dimension = str(item.get("Dimension") or "").strip().lower()
            if dimension not in MARKETPLACE_PLAN_DIMENSIONS:
                continue
            expires_at = _naive_utc(item.get("ExpirationDate"))
            if expires_at is not None and expires_at <= now:
                continue
            if not _entitlement_value_positive(item.get("Value")):
                continue
            found[dimension] = expires_at
        token = page.get("NextToken")
        if not token:
            break
    if len(found) != 1:
        return None, None
    dimension = next(iter(found))
    return dimension, found[dimension]


def sync_marketplace_subscription(db, row: AwsMarketplaceRegistration, *, active: bool) -> bool:
    """Mirror the AWS plan into AGRO-AI's internal plan/quota model.

    Marketplace owns billing. This record exists only so platform limits and
    credits are enforced consistently; it must never trigger Stripe billing.
    """
    if not row.organization_id:
        # The AWS license can be fully reconciled before the buyer links an
        # AGRO-AI organization. Linking will materialize the internal plan record.
        return True
    existing = (
        db.query(PlatformApiSubscription)
        .filter(
            PlatformApiSubscription.organization_id == row.organization_id,
            PlatformApiSubscription.status_slot == "active",
        )
        .first()
    )
    if not active:
        if existing is not None and existing.billing_mode == "aws_marketplace":
            existing.status = "canceled"
        return True

    if row.plan_identifier not in MARKETPLACE_PLAN_DIMENSIONS:
        return False
    plan = (
        db.query(PlatformApiPlan)
        .filter(
            PlatformApiPlan.catalog_version == settings.PLATFORM_API_PLAN_CATALOG_VERSION,
            PlatformApiPlan.plan_identifier == row.plan_identifier,
            PlatformApiPlan.active.is_(True),
        )
        .first()
    )
    if plan is None:
        return False
    if existing is not None and existing.billing_mode not in {"none", "aws_marketplace"}:
        return False
    subscription = existing or PlatformApiSubscription(
        organization_id=row.organization_id,
        plan_id=plan.id,
        status_slot="active",
    )
    subscription.plan_id = plan.id
    subscription.status = "active"
    subscription.billing_mode = "aws_marketplace"
    subscription.billing_interval = "month"
    subscription.contract_reference = f"aws-marketplace:{row.id}"
    subscription.entitlement_policy_json = {
        "source": "aws_marketplace",
        "dimension": row.plan_identifier,
        "overages_allowed": False,
    }
    if existing is None:
        db.add(subscription)
    return True


def reconcile_registration(
    db,
    client,
    row: AwsMarketplaceRegistration,
    product_id: str,
    *,
    entitlements,
    product_code: str,
) -> str:
    agreement_active = agreement_is_active(client, row, product_id)
    # A deprovision event wins over a stale eventual-consistency API response.
    if row.status == "revoked":
        sync_marketplace_subscription(db, row, active=False)
        row.reconciled_at = datetime.utcnow()
    elif agreement_active and row.status in {"license_confirmed", "active"}:
        plan_identifier, expires_at = marketplace_plan_entitlement(entitlements, row, product_code)
        if plan_identifier is None:
            # Fail closed but remain recoverable if AWS entitlement propagation is delayed.
            row.status = "license_confirmed"
            row.plan_identifier = None
            row.entitlement_expires_at = None
            row.reconciled_at = None
            sync_marketplace_subscription(db, row, active=False)
        else:
            row.plan_identifier = plan_identifier
            row.entitlement_expires_at = expires_at
            if row.organization_id and not sync_marketplace_subscription(db, row, active=True):
                row.status = "license_confirmed"
                row.reconciled_at = None
            else:
                row.status = "active"
                row.reconciled_at = datetime.utcnow()
    elif row.status == "active":
        row.status = "revoked"
        sync_marketplace_subscription(db, row, active=False)
        row.reconciled_at = datetime.utcnow()
    else:
        row.reconciled_at = None
    db.commit()
    return row.status


def require_marketplace_access(db, organization_id: str) -> bool:
    row = db.query(AwsMarketplaceRegistration).filter_by(organization_id=organization_id).first()
    if row is None:
        return False
    if (
        row.status != "active"
        or row.plan_identifier not in MARKETPLACE_PLAN_DIMENSIONS
        or not row.reconciled_at
        or row.reconciled_at < datetime.utcnow() - timedelta(hours=25)
    ):
        raise HTTPException(status_code=403, detail={"code": "aws_marketplace_license_inactive"})
    return True
