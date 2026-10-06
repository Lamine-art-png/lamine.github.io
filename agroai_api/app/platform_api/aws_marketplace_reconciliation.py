"""Reconcile an event-observed license with current AWS agreement state.

The registration token and an EventBridge notification are insufficient to grant
access. The agreement must belong to the expected buyer and product, and its
specific license entitlement must be provisioned.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException

from app.models.aws_marketplace import AwsMarketplaceRegistration


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


def reconcile_registration(db, client, row: AwsMarketplaceRegistration, product_id: str) -> str:
    active = agreement_is_active(client, row, product_id)
    # A deprovision event wins over a stale eventual-consistency API response.
    if row.status == "revoked":
        row.reconciled_at = datetime.utcnow()
    elif active and row.status in {"license_confirmed", "active"}:
        row.status = "active"
        row.reconciled_at = datetime.utcnow()
    elif row.status == "active":
        row.status = "revoked"
        row.reconciled_at = datetime.utcnow()
    else:
        row.reconciled_at = None
    db.commit()
    return row.status


def require_marketplace_access(db, organization_id: str) -> bool:
    row = db.query(AwsMarketplaceRegistration).filter_by(organization_id=organization_id).first()
    if row is None:
        return False
    if row.status != "active" or not row.reconciled_at or row.reconciled_at < datetime.utcnow() - timedelta(hours=25):
        raise HTTPException(status_code=403, detail={"code": "aws_marketplace_license_inactive"})
    return True
