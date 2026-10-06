"""Initial AWS onboarding boundary, disabled until the seller config is ready.

This endpoint deliberately does not provision API access or mark a license active.
License events, account linking, and metering remain separate launch requirements.
"""
from datetime import datetime, timedelta
from hashlib import sha256
from html import escape
import secrets

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limiting import limiter
from app.db.base import get_db
from app.models.aws_marketplace import AwsMarketplaceRegistration
from app.models.platform_product import PlatformApiSubscription
from app.models.saas import Organization
from app.api.deps import AuthContext, get_auth_context, require_approved_organization
from app.platform_api.terms import require_user_acceptance
from app.platform_api.aws_marketplace import InvalidMarketplaceIdentity, resolve_purchase

router = APIRouter(prefix="/marketplace/aws", tags=["aws-marketplace"])


class MarketplaceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=36, max_length=36)
    claim_code: str = Field(min_length=40, max_length=128)


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
    if row.status == "revoked":
        raise HTTPException(status_code=409, detail="AWS license is no longer available; manage your subscription in AWS Marketplace")
    if row.organization_id:
        raise HTTPException(status_code=409, detail="AWS license is already linked to an account")
    claim_code = secrets.token_urlsafe(32)
    row.claim_token_hash = sha256(claim_code.encode()).hexdigest()
    row.claim_expires_at = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    reference = escape(row.id)
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
        '<p>Sign in to your approved AGRO-AI organization, accept the current Platform API terms, '
        'and enter this reference and one-time claim code in the AWS Marketplace linking form. '
        'The claim code expires in one hour.</p>'
        f'<p>Reference: <strong>{reference}</strong></p>'
        f'<p>One-time claim code: <strong>{escape(claim_code)}</strong></p></main></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/link")
@limiter.limit("10/minute")
def link_purchase(
    payload: MarketplaceLink,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    _enabled()
    if not ctx.organization or not ctx.membership or ctx.membership.status != "active" or ctx.membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Active organization administrator required")
    require_approved_organization(ctx.organization)
    require_user_acceptance(db, organization_id=ctx.organization.id, user_id=ctx.user.id)
    # Serialize linking against Stripe checkout on the organization row.
    db.query(Organization).filter_by(id=ctx.organization.id).with_for_update().one()
    row = db.query(AwsMarketplaceRegistration).filter_by(id=payload.reference).with_for_update().first()
    candidate = sha256(payload.claim_code.encode()).hexdigest()
    if (
        row is None or row.organization_id or row.status == "revoked"
        or not row.claim_token_hash or not secrets.compare_digest(candidate, row.claim_token_hash)
        or not row.claim_expires_at or row.claim_expires_at < datetime.utcnow()
    ):
        raise HTTPException(status_code=409, detail="AWS claim is unavailable; restart registration from AWS Marketplace")
    if db.query(AwsMarketplaceRegistration).filter_by(organization_id=ctx.organization.id).first():
        raise HTTPException(status_code=409, detail="Organization already has an AWS license")
    subscription = db.query(PlatformApiSubscription).filter_by(organization_id=ctx.organization.id, status_slot="active").first()
    if subscription and subscription.billing_mode == "stripe":
        raise HTTPException(status_code=409, detail="Existing Stripe subscription requires billing migration before AWS linking")
    row.organization_id = ctx.organization.id
    row.linked_by_user_id = ctx.user.id
    row.linked_at = datetime.utcnow()
    row.claim_token_hash = None
    row.claim_expires_at = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="AWS license or organization already linked") from None
    return {"status": row.status, "reference": row.id, "access": "active" if row.status == "active" else "pending_reconciliation"}


@router.get("/status")
def marketplace_status(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    if not ctx.organization or not ctx.membership or ctx.membership.status != "active":
        raise HTTPException(status_code=403, detail="Active organization membership required")
    row = db.query(AwsMarketplaceRegistration).filter_by(organization_id=ctx.organization.id).first()
    if row is None:
        return {"linked": False}
    return {
        "linked": True,
        "status": row.status,
        "reference": row.id,
        "last_reconciled_at": row.reconciled_at.isoformat() if row.reconciled_at else None,
    }
