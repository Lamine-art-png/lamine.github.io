"""In-process AWS Marketplace event consumer and agreement reconciler.

Runs only when AWS_MARKETPLACE_EVENTS_ENABLED is true. Credentials come from the
standard boto3 provider chain, so Render managed OIDC can supply short-lived AWS
credentials via AWS_ROLE_ARN + AWS_WEB_IDENTITY_TOKEN_FILE without stored keys.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import boto3
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, CredentialRetrievalError, NoCredentialsError

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.aws_marketplace import AwsMarketplaceRegistration
from app.platform_api.aws_marketplace_events import consume_license_messages
from app.platform_api.aws_marketplace_reconciliation import reconcile_registration

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_last_event_result: dict[str, Any] | None = None
_last_reconcile_result: dict[str, Any] | None = None
_identity_verified_logged = False





def _safe_aws_error_code(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        return str((exc.response.get("Error") or {}).get("Code") or "ClientError")[:80]
    if isinstance(exc, NoCredentialsError):
        return "NoCredentialsError"
    if isinstance(exc, CredentialRetrievalError):
        return "CredentialRetrievalError"
    if isinstance(exc, BotoCoreError):
        return exc.__class__.__name__[:80]
    return exc.__class__.__name__[:80]


def _log_credential_diagnostic(scope: str, exc: Exception) -> None:
    logger.error(
        "AWS Marketplace %s unavailable aws_error=%s role_arn_present=%s web_identity_token_file_present=%s",
        scope,
        _safe_aws_error_code(exc),
        bool(os.environ.get("AWS_ROLE_ARN")),
        bool(os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")),
    )


def _aws_config() -> Config:
    return Config(connect_timeout=3, read_timeout=20, retries={"max_attempts": 2})


def _seller_identity_valid() -> bool:
    return bool(
        re.fullmatch(r"[0-9]{12}", settings.AWS_MARKETPLACE_SELLER_ACCOUNT_ID or "")
        and re.fullmatch(r"[a-z]{2}-[a-z]+-\d", settings.AWS_MARKETPLACE_REGION or "")
    )


def _event_configuration_valid() -> bool:
    if not _seller_identity_valid():
        return False
    if not settings.AWS_MARKETPLACE_PRODUCT_CODE or not re.fullmatch(
        r"prod-[a-z0-9]+", settings.AWS_MARKETPLACE_PRODUCT_ID or ""
    ):
        return False
    parsed = urlparse(settings.AWS_MARKETPLACE_QUEUE_URL or "")
    return bool(
        parsed.scheme == "https"
        and parsed.netloc == f"sqs.{settings.AWS_MARKETPLACE_REGION}.amazonaws.com"
        and re.fullmatch(
            rf"/{settings.AWS_MARKETPLACE_SELLER_ACCOUNT_ID}/[A-Za-z0-9_-]+",
            parsed.path,
        )
        and not parsed.query
        and not parsed.fragment
    )


def _credentials_match_seller() -> bool:
    global _identity_verified_logged
    account = boto3.client(
        "sts",
        region_name=settings.AWS_MARKETPLACE_REGION,
        config=_aws_config(),
    ).get_caller_identity()["Account"]
    matches = account == settings.AWS_MARKETPLACE_SELLER_ACCOUNT_ID
    if matches and not _identity_verified_logged:
        logger.warning(
            "AWS Marketplace seller identity verified account=%s role_arn_present=%s web_identity_token_file_present=%s",
            account,
            bool(os.environ.get("AWS_ROLE_ARN")),
            bool(os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")),
        )
        _identity_verified_logged = True
    return matches


def process_events_once() -> dict[str, Any]:
    """Consume one bounded SQS batch without exposing payloads or SDK errors."""
    global _last_event_result
    if not settings.AWS_MARKETPLACE_EVENTS_ENABLED:
        return {"skipped": "disabled"}
    if not _event_configuration_valid():
        _last_event_result = {"status": "configuration_invalid", "checked_at": datetime.utcnow().isoformat()}
        logger.error("AWS Marketplace event worker configuration is invalid")
        return _last_event_result
    try:
        if not _credentials_match_seller():
            _last_event_result = {"status": "wrong_aws_account", "checked_at": datetime.utcnow().isoformat()}
            logger.error("AWS Marketplace event worker credentials do not match the configured seller account")
            return _last_event_result
        config = _aws_config()
        sqs = boto3.client("sqs", region_name=settings.AWS_MARKETPLACE_REGION, config=config)
        agreements = boto3.client(
            "marketplace-agreement",
            region_name=settings.AWS_MARKETPLACE_REGION,
            config=config,
        )
        entitlements = boto3.client(
            "marketplace-entitlement",
            region_name=settings.AWS_MARKETPLACE_REGION,
            config=config,
        )
        counts = consume_license_messages(
            sqs,
            SessionLocal,
            queue_url=settings.AWS_MARKETPLACE_QUEUE_URL,
            seller_account_id=settings.AWS_MARKETPLACE_SELLER_ACCOUNT_ID,
            product_code=settings.AWS_MARKETPLACE_PRODUCT_CODE,
            region=settings.AWS_MARKETPLACE_REGION,
            agreements=agreements,
            product_id=settings.AWS_MARKETPLACE_PRODUCT_ID,
            entitlements=entitlements,
        )
        _last_event_result = {
            "status": "ok" if not counts.get("failed") else "partial",
            **counts,
            "checked_at": datetime.utcnow().isoformat(),
        }
        if counts.get("failed"):
            logger.warning("AWS Marketplace event worker completed with failed messages")
        return _last_event_result
    except Exception as exc:
        _last_event_result = {"status": "unavailable", "checked_at": datetime.utcnow().isoformat()}
        _log_credential_diagnostic("event_processing", exc)
        return _last_event_result


def reconcile_once() -> dict[str, Any]:
    """Refresh active/license-confirmed registrations against AWS Agreement state."""
    global _last_reconcile_result
    if not settings.AWS_MARKETPLACE_EVENTS_ENABLED:
        return {"skipped": "disabled"}
    if not _seller_identity_valid() or not re.fullmatch(
        r"prod-[a-z0-9]+", settings.AWS_MARKETPLACE_PRODUCT_ID or ""
    ):
        _last_reconcile_result = {"status": "configuration_invalid", "checked_at": datetime.utcnow().isoformat()}
        logger.error("AWS Marketplace reconciliation configuration is invalid")
        return _last_reconcile_result
    try:
        if not _credentials_match_seller():
            _last_reconcile_result = {"status": "wrong_aws_account", "checked_at": datetime.utcnow().isoformat()}
            logger.error("AWS Marketplace reconciliation credentials do not match the configured seller account")
            return _last_reconcile_result
        config = _aws_config()
        agreements = boto3.client(
            "marketplace-agreement",
            region_name=settings.AWS_MARKETPLACE_REGION,
            config=config,
        )
        entitlements = boto3.client(
            "marketplace-entitlement",
            region_name=settings.AWS_MARKETPLACE_REGION,
            config=config,
        )
        counts = {"checked": 0, "active": 0, "revoked": 0, "pending": 0, "failed": 0}
        with SessionLocal() as db:
            ids = [
                row.id
                for row in db.query(AwsMarketplaceRegistration.id)
                .filter(AwsMarketplaceRegistration.status.in_(["active", "license_confirmed"]))
                .all()
            ]
        for registration_id in ids:
            with SessionLocal() as db:
                try:
                    row = db.get(AwsMarketplaceRegistration, registration_id)
                    if row is None:
                        continue
                    state = reconcile_registration(
                        db,
                        agreements,
                        row,
                        settings.AWS_MARKETPLACE_PRODUCT_ID,
                        entitlements=entitlements,
                        product_code=settings.AWS_MARKETPLACE_PRODUCT_CODE,
                    )
                    counts["checked"] += 1
                    bucket = "active" if state == "active" else "revoked" if state == "revoked" else "pending"
                    counts[bucket] += 1
                except Exception:
                    db.rollback()
                    counts["failed"] += 1
        _last_reconcile_result = {
            "status": "ok" if not counts["failed"] else "partial",
            **counts,
            "checked_at": datetime.utcnow().isoformat(),
        }
        if counts["failed"]:
            logger.warning("AWS Marketplace reconciliation completed with failed registrations")
        return _last_reconcile_result
    except Exception as exc:
        _last_reconcile_result = {"status": "unavailable", "checked_at": datetime.utcnow().isoformat()}
        _log_credential_diagnostic("reconciliation", exc)
        return _last_reconcile_result


def worker_status() -> dict[str, Any]:
    return {
        "enabled": bool(settings.AWS_MARKETPLACE_EVENTS_ENABLED),
        "configuration_valid": _event_configuration_valid() if settings.AWS_MARKETPLACE_EVENTS_ENABLED else False,
        "last_event_result": _last_event_result,
        "last_reconcile_result": _last_reconcile_result,
    }


def start_aws_marketplace_worker() -> AsyncIOScheduler | None:
    """Start bounded event polling and hourly reconciliation in the API process."""
    global _scheduler
    if not settings.AWS_MARKETPLACE_EVENTS_ENABLED:
        logger.info("AWS Marketplace runtime worker disabled by configuration")
        return None
    if not _event_configuration_valid():
        logger.error("AWS Marketplace runtime worker not started: configuration is invalid")
        return None
    if _scheduler is not None:
        return _scheduler

    poll_seconds = max(15, int(getattr(settings, "AWS_MARKETPLACE_EVENT_POLL_SECONDS", 60)))
    reconcile_seconds = max(300, int(getattr(settings, "AWS_MARKETPLACE_RECONCILE_SECONDS", 3600)))
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        process_events_once,
        trigger=IntervalTrigger(seconds=poll_seconds),
        id="aws_marketplace_events",
        name="AWS Marketplace SQS consumer",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.utcnow() + timedelta(seconds=5),
    )
    _scheduler.add_job(
        reconcile_once,
        trigger=IntervalTrigger(seconds=reconcile_seconds),
        id="aws_marketplace_reconcile",
        name="AWS Marketplace agreement reconciliation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.utcnow() + timedelta(seconds=15),
    )
    _scheduler.start()
    logger.info(
        "AWS Marketplace runtime worker started (poll=%ss, reconcile=%ss)",
        poll_seconds,
        reconcile_seconds,
    )
    return _scheduler


def stop_aws_marketplace_worker() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        finally:
            _scheduler = None
