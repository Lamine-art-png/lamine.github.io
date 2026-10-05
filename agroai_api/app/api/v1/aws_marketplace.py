"""Initial AWS onboarding boundary, disabled until the seller config is ready.

This endpoint deliberately does not provision API access or mark a license active.
License events, account linking, and metering remain separate launch requirements.
"""
from html import escape

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limiting import limiter
from app.db.base import get_db
from app.models.aws_marketplace import AwsMarketplaceRegistration
from app.platform_api.aws_marketplace import InvalidMarketplaceIdentity, resolve_purchase

router = APIRouter(prefix="/marketplace/aws", tags=["aws-marketplace"])


def marketplace_client():
    return boto3.client(
        "meteringmarketplace",
        region_name=settings.AWS_MARKETPLACE_REGION,
        config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2}),
    )


def _enabled():
    if not settings.AWS_MARKETPLACE_ONBOARDING_ENABLED:
        raise HTTPException(status_code=503, detail="AWS Marketplace onboarding is not enabled yet")
    if not settings.AWS_MARKETPLACE_PRODUCT_CODE:
        raise HTTPException(status_code=503, detail="AWS Marketplace seller configuration is incomplete")


def _resolve(token):
    return resolve_purchase(marketplace_client(), token, settings.AWS_MARKETPLACE_PRODUCT_CODE)


@router.post("/register", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def register(request: Request, db: Session = Depends(get_db)):
    _enabled()
    # Reject oversized forms before parsing; never retain or log the purchase token.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            raise HTTPException(status_code=413, detail="Registration form too large")
    from urllib.parse import parse_qs
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="Expected an AWS registration form")
    try:
        form = parse_qs(body.decode("utf-8"), max_num_fields=10)
        tokens = form.get("x-amzn-marketplace-token", [])
        if len(tokens) != 1:
            raise InvalidMarketplaceIdentity("Missing registration token")
        # The synchronous SDK call runs off the async request loop.
        from starlette.concurrency import run_in_threadpool
        identity = await run_in_threadpool(_resolve, tokens[0])
    except (UnicodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid AWS registration") from None
    except (BotoCoreError, ClientError):
        raise HTTPException(status_code=503, detail="AWS purchase validation unavailable; retry from AWS Marketplace") from None
    row = db.query(AwsMarketplaceRegistration).filter_by(license_arn=identity["license_arn"]).first()
    if row and (row.customer_aws_account_id != identity["customer_aws_account_id"] or row.product_code != identity["product_code"]):
        raise HTTPException(status_code=409, detail="Purchase identity conflict")
    if row is None:
        row = AwsMarketplaceRegistration(**identity)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.query(AwsMarketplaceRegistration).filter_by(**identity).first()
            if row is None:
                raise HTTPException(status_code=409, detail="Purchase identity conflict") from None
    reference = escape(row.id)
    if row.status == "revoked":
        raise HTTPException(status_code=409, detail="AWS license is no longer available; manage your subscription in AWS Marketplace")
    message = (
        "Your AWS license has been confirmed. API access is pending account setup."
        if row.status == "license_confirmed"
        else "Your AWS purchase identity has been validated. API access is pending license confirmation and account setup."
    )
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>AGRO-AI AWS onboarding</title><main><h1>Purchase received</h1>'
        f'<p>{message}</p>'
        '<p>Contact <a href="mailto:contact@agroai-pilot.com">contact@agroai-pilot.com</a> '
        f'with registration reference <strong>{reference}</strong> to complete account linking.</p></main></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'", "X-Content-Type-Options": "nosniff"},
    )
