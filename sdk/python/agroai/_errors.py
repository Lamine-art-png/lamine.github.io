from __future__ import annotations

from typing import Any


class AgroAIError(Exception):
    """Base class for every error raised by the AGRO-AI SDK."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.body = body

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"code={self.code}")
        if self.status_code:
            parts.append(f"status={self.status_code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " | ".join(parts)


class APIConnectionError(AgroAIError):
    """The request never produced an HTTP response."""


class APITimeoutError(APIConnectionError):
    """The request timed out."""


class APIStatusError(AgroAIError):
    """The API returned a non-success status."""


class BadRequestError(APIStatusError):
    pass


class AuthenticationError(APIStatusError):
    pass


class InsufficientBalanceError(APIStatusError):
    """402: add funds to the Intelligence wallet; ``required_cents`` is the run price."""

    @property
    def required_cents(self) -> int | None:
        detail = self.body if isinstance(self.body, dict) else {}
        return detail.get("required_cents")


class PermissionDeniedError(APIStatusError):
    pass


class NotFoundError(APIStatusError):
    pass


class ConflictError(APIStatusError):
    """409: idempotency key reused with a different request, run in progress, etc."""


class UnsupportedMediaTypeError(APIStatusError):
    pass


class PayloadTooLargeError(APIStatusError):
    pass


class UnprocessableEntityError(APIStatusError):
    pass


class RateLimitError(APIStatusError):
    pass


class InternalServerError(APIStatusError):
    pass


_BY_STATUS = {
    400: BadRequestError,
    401: AuthenticationError,
    402: InsufficientBalanceError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    413: PayloadTooLargeError,
    415: UnsupportedMediaTypeError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def error_for(status_code: int, payload: Any, request_id: str | None) -> APIStatusError:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, list):  # FastAPI request validation errors
        message = "; ".join(str(item.get("msg")) for item in detail[:5] if isinstance(item, dict)) or "Invalid request"
        return UnprocessableEntityError(message, status_code=status_code, code="request_validation_failed", request_id=request_id, body=detail)
    if not isinstance(detail, dict):
        detail = payload if isinstance(payload, dict) else {}
    cls = _BY_STATUS.get(status_code, InternalServerError if status_code >= 500 else APIStatusError)
    return cls(
        str(detail.get("message") or detail.get("code") or f"AGRO-AI API request failed with {status_code}"),
        status_code=status_code,
        code=detail.get("code"),
        request_id=detail.get("request_id") or request_id,
        body=detail,
    )
