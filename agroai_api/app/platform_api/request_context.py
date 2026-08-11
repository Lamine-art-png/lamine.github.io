from __future__ import annotations

import re
import uuid


CLIENT_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")


def new_server_request_id() -> str:
    """Return the server-owned identifier exposed in responses and logs."""

    return f"req_{uuid.uuid4().hex}"


def bounded_client_correlation_id(value: str | None) -> str | None:
    """Preserve a safe client X-Request-Id only as correlation metadata."""

    candidate = str(value or "").strip()
    if CLIENT_CORRELATION_ID_PATTERN.fullmatch(candidate):
        return candidate
    return None


def new_billing_operation_id() -> str:
    """Return a request-local identity used only for ordinary usage metering."""

    return f"bill_{uuid.uuid4().hex}"
