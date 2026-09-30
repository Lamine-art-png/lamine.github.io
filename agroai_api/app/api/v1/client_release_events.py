"""Privacy-safe portal release diagnostics.

The portal reports release-convergence events (stale build detected, recovery
attempted/succeeded/deferred, reload loop prevented, asset or dynamic-import
failure, service-worker update). Only build identifiers, the event, a trigger
or reason category, the first path segment and page visibility are accepted;
anything else is dropped. Nothing is stored: events are emitted as structured
log lines so stale-release traffic is visible in production logs.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import Response

from app.core.rate_limiting import limiter

router = APIRouter(tags=["client-release"])
logger = logging.getLogger("agroai.frontend_release")

EVENTS = frozenset({
    "stale_build_detected",
    "recovery_attempted",
    "recovery_succeeded",
    "recovery_deferred",
    "reload_loop_prevented",
    "asset_load_failure",
    "dynamic_import_failure",
    "service_worker_updated",
})
_BUILD = re.compile(r"^[A-Za-z0-9._:/-]{1,120}$")
_ROUTE = re.compile(r"^/[a-z-]{0,40}$")
_WORD = re.compile(r"^[a-z_]{1,40}$")
MAX_BODY_BYTES = 2048


def _clean(payload: dict[str, Any]) -> dict[str, Any] | None:
    event = payload.get("event")
    if event not in EVENTS:
        return None
    cleaned: dict[str, Any] = {"event": event}
    for key in ("running_build", "latest_build"):
        value = payload.get(key)
        if isinstance(value, str) and _BUILD.match(value):
            cleaned[key] = value
    route = payload.get("route")
    if isinstance(route, str) and (route in {"/", "/other"} or _ROUTE.match(route)):
        cleaned["route"] = route
    for key in ("trigger", "visibility"):
        value = payload.get(key)
        if isinstance(value, str) and _WORD.match(value):
            cleaned[key] = value
    reason = payload.get("reason")
    if isinstance(reason, str):
        # Categories only (e.g. unsaved_input); free-form error text is reduced
        # to its error class name so no URL, token or content can be logged.
        category = reason.split(":", 1)[0].strip()
        if _WORD.match(category) or re.fullmatch(r"[A-Za-z]{1,40}Error", category):
            cleaned["reason"] = category
    attempts = payload.get("attempts")
    if isinstance(attempts, int) and 0 <= attempts <= 100:
        cleaned["attempts"] = attempts
    return cleaned


@router.post("/client/release-events", status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
@limiter.limit("60/minute")
async def client_release_event(request: Request) -> Response:
    body = await request.body()
    if len(body) <= MAX_BODY_BYTES:
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            payload = None
        cleaned = _clean(payload) if isinstance(payload, dict) else None
        if cleaned:
            logger.info("frontend_release_event %s", json.dumps(cleaned, sort_keys=True))
    return Response(status_code=status.HTTP_202_ACCEPTED)


_SKEW_LOGGED: dict[str, float] = {}
_SKEW_INTERVAL_SECONDS = 600


def log_client_build_skew(client_build: str | None, server_build: str | None, path: str) -> None:
    """Sampled log of API traffic from a portal build other than the deployed one."""
    if not client_build or not server_build or not _BUILD.match(client_build):
        return
    if client_build in {server_build, "unversioned"}:
        return
    now = time.monotonic()
    if now - _SKEW_LOGGED.get(client_build, -_SKEW_INTERVAL_SECONDS) < _SKEW_INTERVAL_SECONDS:
        return
    if len(_SKEW_LOGGED) > 256:
        _SKEW_LOGGED.clear()
    _SKEW_LOGGED[client_build] = now
    segment = path.split("/")[2] if path.startswith("/v1/") and len(path.split("/")) > 2 else ""
    logger.warning(
        "frontend_build_skew %s",
        json.dumps({"client_build": client_build, "server_build": server_build, "api_family": segment[:40]}, sort_keys=True),
    )
