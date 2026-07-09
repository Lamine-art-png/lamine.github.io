"""Minimal Resend REST client for the dedicated outreach credential."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import OutreachSettings
from .templates import RenderedEmail


class ResendError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass(frozen=True, slots=True)
class ResendResult:
    id: str
    raw: dict[str, Any]


class ResendClient:
    def __init__(self, settings: OutreachSettings) -> None:
        self.settings = settings

    def send(self, *, to: str, rendered: RenderedEmail, idempotency_key: str, account_tag: str | None = None) -> ResendResult:
        if not self.settings.resend_api_key:
            raise ResendError("OUTREACH_RESEND_API_KEY is not configured")
        payload: dict[str, Any] = {
            "from": self.settings.sender,
            "to": [to],
            "subject": rendered.subject,
            "html": rendered.html,
            "text": rendered.text,
            "reply_to": self.settings.reply_to,
            "headers": {
                "List-Unsubscribe": f"<{rendered.unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        }
        if account_tag:
            safe_tag = "".join(ch if ch.isascii() and (ch.isalnum() or ch in "_-") else "_" for ch in account_tag)[:200]
            if safe_tag:
                payload["tags"] = [{"name": "account", "value": safe_tag}]
        request = Request(
            self.settings.resend_api_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.resend_api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key[:256],
                "User-Agent": "AGRO-AI-Outreach/1.0",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - configured HTTPS Resend endpoint
                parsed = json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ResendError(f"Resend rejected request with HTTP {exc.code}", status_code=exc.code, response_body=body) from exc
        except URLError as exc:
            raise ResendError(f"Could not reach Resend: {exc.reason}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ResendError("Resend returned an unreadable response") from exc
        resend_id = str(parsed.get("id") or "").strip()
        if not resend_id:
            raise ResendError("Resend response did not contain an email id", response_body=json.dumps(parsed))
        return ResendResult(id=resend_id, raw=parsed)


__all__ = ["ResendClient", "ResendError", "ResendResult"]
