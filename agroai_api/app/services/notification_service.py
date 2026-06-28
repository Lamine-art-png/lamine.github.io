from __future__ import annotations

from typing import Any


def notification_configured() -> bool:
    """Return whether a live notification transport is wired.

    The first shipping version stores requests reliably in the AGRO-AI workspace.
    A later deployment can connect email/CRM without changing the customer flow.
    """
    return False


def send_notification(*, kind: str, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Safe notification placeholder.

    Customer support/sales/onboarding requests should never fail because outbound
    notification plumbing is not configured. We therefore return a clear internal
    status while the request remains stored in the product.
    """
    return {
        "notification_status": "stored_not_notified",
        "provider": "workspace_inbox",
        "kind": kind,
        "subject": subject,
    }
