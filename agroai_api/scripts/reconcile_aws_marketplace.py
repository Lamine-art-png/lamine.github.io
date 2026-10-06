"""Refresh agreement state even if EventBridge delivery is delayed or lost."""
import json
import re

import boto3
from botocore.config import Config

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.aws_marketplace import AwsMarketplaceRegistration
from app.platform_api.aws_marketplace_reconciliation import reconcile_registration


def main():
    if not settings.AWS_MARKETPLACE_EVENTS_ENABLED:
        raise SystemExit("AWS Marketplace reconciliation is disabled")
    seller = settings.AWS_MARKETPLACE_SELLER_ACCOUNT_ID
    product_id = settings.AWS_MARKETPLACE_PRODUCT_ID
    if not re.fullmatch(r"[0-9]{12}", seller) or not re.fullmatch(r"prod-[a-z0-9]+", product_id):
        raise SystemExit("AWS Marketplace reconciliation configuration is invalid")
    config = Config(connect_timeout=3, read_timeout=20, retries={"max_attempts": 2})
    if boto3.client("sts", region_name=settings.AWS_MARKETPLACE_REGION, config=config).get_caller_identity()["Account"] != seller:
        raise SystemExit("AWS credentials do not belong to the configured seller")
    agreements = boto3.client("marketplace-agreement", region_name=settings.AWS_MARKETPLACE_REGION, config=config)
    counts = {"checked": 0, "active": 0, "revoked": 0, "pending": 0, "failed": 0}
    with SessionLocal() as db:
        ids = [row.id for row in db.query(AwsMarketplaceRegistration.id).filter(AwsMarketplaceRegistration.status.in_(["active", "license_confirmed"])).all()]
    for registration_id in ids:
        with SessionLocal() as db:
            try:
                row = db.get(AwsMarketplaceRegistration, registration_id)
                if row is None:
                    continue
                state = reconcile_registration(db, agreements, row, product_id)
                counts["checked"] += 1
                counts["active" if state == "active" else "revoked" if state == "revoked" else "pending"] += 1
            except Exception:
                db.rollback()
                counts["failed"] += 1
    print(json.dumps(counts))
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("AWS Marketplace reconciliation unavailable; check configuration and service health") from None
