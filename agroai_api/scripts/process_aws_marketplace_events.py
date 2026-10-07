"""Run one bounded batch using the configured seller-account SQS queue."""
import json
import re
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from app.core.config import settings
from app.db.base import SessionLocal
from app.platform_api.aws_marketplace_events import consume_license_messages


def main():
    if not settings.AWS_MARKETPLACE_EVENTS_ENABLED:
        raise SystemExit("AWS Marketplace event processing is disabled")
    seller = settings.AWS_MARKETPLACE_SELLER_ACCOUNT_ID
    region = settings.AWS_MARKETPLACE_REGION
    queue = settings.AWS_MARKETPLACE_QUEUE_URL
    parsed = urlparse(queue)
    if (
        not re.fullmatch(r"[0-9]{12}", seller)
        or not settings.AWS_MARKETPLACE_PRODUCT_CODE
        or not settings.AWS_MARKETPLACE_PRODUCT_ID
        or not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region)
        or parsed.scheme != "https"
        or parsed.netloc != f"sqs.{region}.amazonaws.com"
        or not re.fullmatch(rf"/{seller}/[A-Za-z0-9_-]+", parsed.path)
        or parsed.query or parsed.fragment
    ):
        raise SystemExit("AWS Marketplace queue configuration is invalid")
    config = Config(connect_timeout=3, read_timeout=20, retries={"max_attempts": 2})
    sts = boto3.client("sts", region_name=region, config=config)
    if sts.get_caller_identity()["Account"] != seller:
        raise SystemExit("AWS credentials do not belong to the configured seller")
    sqs = boto3.client("sqs", region_name=region, config=config)
    agreements = boto3.client("marketplace-agreement", region_name=region, config=config)
    entitlements = boto3.client("marketplace-entitlement", region_name=region, config=config)
    counts = consume_license_messages(
        sqs,
        SessionLocal,
        queue_url=queue,
        seller_account_id=seller,
        product_code=settings.AWS_MARKETPLACE_PRODUCT_CODE,
        region=region,
        agreements=agreements,
        product_id=settings.AWS_MARKETPLACE_PRODUCT_ID,
        entitlements=entitlements,
    )
    print(json.dumps(counts))
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Startup/receive failures must not emit raw SDK exceptions or payloads.
        raise SystemExit("AWS Marketplace event processing unavailable; check configuration and service health") from None
