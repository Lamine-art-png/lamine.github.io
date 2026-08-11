"""Provider-aware execution wrapper for safe outreach retries."""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from .idempotency_reconciliation import provider_error_type, reconcile_provider_accepted_send
from .resend_client import ResendClient, ResendError


class TypedResendClient(ResendClient):
    """Preserve Resend's stable error type in safe application error text."""

    def send(self, **kwargs):  # type: ignore[override]
        try:
            return super().send(**kwargs)
        except ResendError as exc:
            error_type = provider_error_type(exc.response_body)
            message = str(exc)
            if error_type:
                message = f"{message} [{error_type}]"
            raise ResendError(
                message,
                status_code=exc.status_code,
                response_body=exc.response_body,
            ) from exc


def _detail_text(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, sort_keys=True)
    except (TypeError, ValueError):
        return str(detail)


def install_provider_reconciliation(router_module: Any) -> None:
    """Install once on the production router without changing endpoint contracts."""
    if getattr(router_module, "_provider_reconciliation_installed", False):
        return

    router_module.resend = TypedResendClient(router_module.settings)
    original_execute_one = router_module._execute_one

    def execute_one(prospect, *, send_now: bool):
        try:
            return original_execute_one(prospect, send_now=send_now)
        except HTTPException as exc:
            detail_text = _detail_text(exc.detail)
            if exc.status_code != 502 or "invalid_idempotent_request" not in detail_text:
                raise

            base_rendered = router_module._rendered(prospect)
            idempotency_key = router_module._idempotency_key(prospect, base_rendered)
            metadata = {
                "verification": prospect.email_verification_status.value,
                "engagement_tracking": True,
                "tracked_links": list(router_module._TRACKED_LINK_KEYS),
                **router_module._message_metadata(prospect),
                **router_module._language_metadata(base_rendered),
            }
            reconciled_id = reconcile_provider_accepted_send(
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
            if not reconciled_id:
                raise
            return {
                "status": "sent",
                "record_id": reconciled_id,
                "resend_id": None,
                "prospect_id": prospect.prospect_id,
                "email": prospect.email,
                "account": prospect.account,
                "subject": base_rendered.subject,
                "reply_to": router_module.settings.reply_to,
                "engagement_tracking": True,
                "provider_reconciled": True,
                **router_module._message_metadata(prospect),
                **router_module._language_metadata(base_rendered),
            }

    router_module._execute_one = execute_one
    router_module._provider_reconciliation_installed = True


__all__ = ["TypedResendClient", "install_provider_reconciliation"]
