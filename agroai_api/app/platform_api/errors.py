from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class PlatformApiHTTPException(HTTPException):
    """Platform-only exception rendered without FastAPI's legacy detail wrapper."""


def platform_error(
    code: str,
    message: str,
    *,
    status_code: int = 400,
    error_type: str = "request_error",
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    payload: dict[str, Any] = {
        "code": code,
        "type": error_type,
        "message": message,
    }
    if request_id:
        payload["request_id"] = request_id
    if details:
        payload["details"] = details
    return HTTPException(status_code=status_code, detail=payload)


def error_response(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = str(getattr(request.state, "request_id", "") or request.headers.get("x-request-id") or "")
    if isinstance(exc.detail, dict) and {"code", "type", "message"}.issubset(exc.detail):
        payload = dict(exc.detail)
        payload.setdefault("request_id", request_id)
    else:
        payload = {
            "code": "platform_api_error",
            "type": "request_error",
            "message": "The Platform API request could not be completed.",
            "request_id": request_id,
        }
    return JSONResponse(payload, status_code=exc.status_code, headers=getattr(exc, "headers", None))
