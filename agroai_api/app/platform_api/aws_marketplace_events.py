"""Authenticated SQS license intake. No public webhook and no access provisioning.

Only call this from the seller-account queue consumer. Queue policies, IAM and
STS establish the sender boundary; JSON source fields alone are not authentication.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from uuid import UUID

from app.models.aws_marketplace import AwsMarketplaceLicenseEvent, AwsMarketplaceRegistration


LICENSE_UPDATED = "License Updated - Manufacturer"
LICENSE_DEPROVISIONED = "License Deprovisioned - Manufacturer"


class InvalidLicenseEvent(ValueError):
    pass


def parse_license_event(body: str, *, seller_account_id: str, product_code: str, region: str, now=None):
    if not re.fullmatch(r"[0-9]{12}", seller_account_id) or not product_code or not region:
        raise InvalidLicenseEvent("Seller configuration is incomplete")
    if not isinstance(body, str) or len(body.encode("utf-8")) > 65536:
        raise InvalidLicenseEvent("Event too large")
    try:
        event = json.loads(body)
        event_id = event["id"]
        if str(UUID(event_id)) != event_id:
            raise ValueError("Invalid event ID")
        event_type = event["detail-type"]
        detail = event["detail"]
        account_id = detail["acceptor"]["accountId"]
        license_arn = detail["license"]["arn"]
        occurred_at = datetime.fromisoformat(event["time"].replace("Z", "+00:00"))
        if (
            event.get("source") != "aws.agreement-marketplace"
            or event.get("account") != seller_account_id
            or event.get("region") != region
            or event_type not in {LICENSE_UPDATED, LICENSE_DEPROVISIONED}
            or detail.get("catalog") != "AWSMarketplace"
            or detail["product"]["code"] != product_code
            or not re.fullmatch(r"[0-9]{12}", account_id)
            or not re.fullmatch(r"arn:aws[a-z-]*:license-manager:[^:]*:[0-9]{12}:license[:/][A-Za-z0-9-]+", license_arn)
            or occurred_at.tzinfo is None
            or occurred_at > (now or datetime.now(timezone.utc)) + timedelta(minutes=5)
        ):
            raise ValueError("Unexpected license event")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise InvalidLicenseEvent("Invalid AWS license event") from None
    return {
        "event_id": event_id,
        "event_type": event_type,
        "license_arn": license_arn,
        "customer_aws_account_id": account_id,
        "product_code": product_code,
        "occurred_at": occurred_at.astimezone(timezone.utc).replace(tzinfo=None),
        "payload_digest": hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def process_license_event(db, body: str, *, seller_account_id: str, product_code: str, region: str):
    """Commit the license state and receipt together before acknowledging SQS.

An event can arrive before ResolveCustomer. Keep it by license so registration
cannot reset a confirmed or revoked state. Multiple licenses on one account
remain separate. Database races are retried by SQS, never silently acknowledged.
"""
    event = parse_license_event(body, seller_account_id=seller_account_id, product_code=product_code, region=region)
    receipt = db.get(AwsMarketplaceLicenseEvent, event["event_id"])
    if receipt is not None:
        if receipt.payload_digest != event["payload_digest"]:
            raise InvalidLicenseEvent("Event ID reused with different content")
        return "duplicate"
    row = db.query(AwsMarketplaceRegistration).filter_by(license_arn=event["license_arn"]).with_for_update().first()
    if row is None:
        row = AwsMarketplaceRegistration(
            license_arn=event["license_arn"],
            customer_aws_account_id=event["customer_aws_account_id"],
            product_code=product_code,
            status="pending_license",
        )
        db.add(row)
    elif row.customer_aws_account_id != event["customer_aws_account_id"] or row.product_code != product_code:
        raise InvalidLicenseEvent("License identity conflict")
    # At equal timestamps, revocation wins. Older updates cannot reactivate it.
    newer = row.license_updated_at is None or event["occurred_at"] > row.license_updated_at
    same_time_revoke = event["occurred_at"] == row.license_updated_at and event["event_type"] == LICENSE_DEPROVISIONED
    if newer or same_time_revoke:
        row.status = "license_confirmed" if event["event_type"] == LICENSE_UPDATED else "revoked"
        row.license_updated_at = event["occurred_at"]
    db.add(AwsMarketplaceLicenseEvent(**{key: event[key] for key in ("event_id", "payload_digest", "license_arn", "event_type", "occurred_at")}))
    db.commit()
    return "processed"


def consume_license_messages(sqs, db_factory, *, queue_url: str, seller_account_id: str, product_code: str, region: str, agreements=None, product_id: str = ""):
    """One bounded batch. A failed message stays in SQS for retry/dead-lettering."""
    result = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=10, VisibilityTimeout=60)
    processed = failed = 0
    for message in result.get("Messages", []):
        with db_factory() as db:
            try:
                event = parse_license_event(message["Body"], seller_account_id=seller_account_id, product_code=product_code, region=region)
                process_license_event(db, message["Body"], seller_account_id=seller_account_id, product_code=product_code, region=region)
                if agreements is not None and product_id:
                    from app.platform_api.aws_marketplace_reconciliation import reconcile_registration
                    row = db.query(AwsMarketplaceRegistration).filter_by(license_arn=event["license_arn"]).one()
                    reconcile_registration(db, agreements, row, product_id)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                processed += 1
            except Exception:
                # Never log bodies, customer IDs, receipt handles or SDK exceptions.
                db.rollback()
                failed += 1
    return {"processed": processed, "failed": failed}
