"""Talgil API adapter for read-only runtime surfaces in AGRO-AI FastAPI."""
from __future__ import annotations

import logging
import re
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from dataclasses import dataclass
from datetime import datetime
 main
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.adapters.base import ControllerAdapter, DataProviderAdapter

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (httpx.TimeoutException, httpx.ConnectError)
STATUS_CACHE_TTL_FAILURE_SECONDS = 5 * 60
STATUS_CACHE_TTL_SUCCESS_SECONDS = 15 * 60


@dataclass
class TalgilDiagnostic:
    error_type: Optional[str] = None
    error_message_sanitized: Optional[str] = None
    upstream_status_code: Optional[int] = None
    upstream_response_preview_sanitized: Optional[str] = None
    response_shape: Optional[str] = None
    retry_after_seconds: Optional[int] = None


@dataclass
class TalgilRuntimeStatus:
    status: str
    configured: bool
    live: bool
    targets: int
    notes: str


def _sanitize_text(value: str, max_len: int = 200) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[\r\n\t]+", " ", value).strip()
    return cleaned[:max_len]


def _parse_retry_after_seconds(raw_value: Optional[str]) -> Optional[int]:
    if not raw_value:
        return None

    value = raw_value.strip()
    if value.isdigit():
        return max(int(value), 0)

    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    seconds = int((dt - datetime.now(timezone.utc)).total_seconds())
    return max(seconds, 0)


@dataclass
class TalgilDiagnostic:
    error_type: Optional[str] = None
    error_message_sanitized: Optional[str] = None
    upstream_status_code: Optional[int] = None
    upstream_response_preview_sanitized: Optional[str] = None
    response_shape: Optional[str] = None


def _sanitize_text(value: str, max_len: int = 200) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[\r\n\t]+", " ", value).strip()
    return cleaned[:max_len]


class TalgilAdapter(ControllerAdapter, DataProviderAdapter):
    """Talgil read-path adapter.

    Backed by real Talgil endpoints from the preserved worker integration:
    - GET /mytargets
    - GET /targets/{id}/

    Write paths are intentionally unsupported in this FastAPI runtime.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        self._last_diagnostic = TalgilDiagnostic()
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
        self._status_cache: Optional[TalgilRuntimeStatus] = None
        self._status_cache_expires_at_monotonic: float = 0.0

 main

        if not api_key:
            logger.info("Talgil adapter initialized without TALGIL_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    @property
    def last_diagnostic(self) -> TalgilDiagnostic:
        return self._last_diagnostic

    def _set_last_diagnostic(
        self,
        *,
        error_type: Optional[str] = None,
        error_message_sanitized: Optional[str] = None,
        upstream_status_code: Optional[int] = None,
        upstream_response_preview_sanitized: Optional[str] = None,
        response_shape: Optional[str] = None,
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
        retry_after_seconds: Optional[int] = None,

 main
    ) -> None:
        self._last_diagnostic = TalgilDiagnostic(
            error_type=error_type,
            error_message_sanitized=error_message_sanitized,
            upstream_status_code=upstream_status_code,
            upstream_response_preview_sanitized=upstream_response_preview_sanitized,
            response_shape=response_shape,
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
            retry_after_seconds=retry_after_seconds,

 main
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                timeout=httpx.Timeout(self._timeout),
                headers=self._auth_headers(),
                follow_redirects=True,
            )
        return self._client

    def _auth_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["TLG-API-Key"] = self._api_key
        return headers

    def _set_status_cache(self, payload: TalgilRuntimeStatus) -> None:
        ttl = STATUS_CACHE_TTL_SUCCESS_SECONDS if payload.live else STATUS_CACHE_TTL_FAILURE_SECONDS
        self._status_cache = payload
        self._status_cache_expires_at_monotonic = time.monotonic() + ttl

    def _get_status_cache(self) -> Optional[TalgilRuntimeStatus]:
        if self._status_cache is None:
            return None
        if time.monotonic() >= self._status_cache_expires_at_monotonic:
            self._status_cache = None
            return None
        return self._status_cache

    @retry(
        retry=retry_if_exception_type(RETRYABLE_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        client = self._get_client()
        resp = await client.get(path, params=params)
        return self._handle_response(resp, "GET", path)

    def _handle_response(self, resp: httpx.Response, method: str, path: str) -> Any:
        preview = _sanitize_text(resp.text)
        response_shape: Optional[str]
        if not resp.content:
            response_shape = "empty"
        else:
            try:
                parsed = resp.json()
                if isinstance(parsed, list):
                    response_shape = "list"
                elif isinstance(parsed, dict):
                    response_shape = "dict"
                else:
                    response_shape = "text"
            except ValueError:
                response_shape = "invalid_json"

        if resp.status_code in (401, 403):
            error = TalgilAuthError(f"Talgil auth failed ({method} {path})")
            self._set_last_diagnostic(
                error_type=error.__class__.__name__,
                error_message_sanitized=_sanitize_text(str(error)),
                upstream_status_code=resp.status_code,
                upstream_response_preview_sanitized=preview,
                response_shape=response_shape,
            )
            raise error
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb


 main
        if resp.status_code == 404:
            self._set_last_diagnostic(
                error_type="TalgilNotFound",
                error_message_sanitized=_sanitize_text(f"Talgil endpoint not found ({method} {path})"),
                upstream_status_code=resp.status_code,
                upstream_response_preview_sanitized=preview,
                response_shape=response_shape,
            )
            return None

        if resp.status_code == 429:
            retry_after_seconds = _parse_retry_after_seconds(resp.headers.get("Retry-After"))
            error = TalgilRateLimitError("Talgil upstream rate limit reached", retry_after_seconds=retry_after_seconds)
            self._set_last_diagnostic(
                error_type=error.__class__.__name__,
                error_message_sanitized=_sanitize_text(str(error)),
                upstream_status_code=resp.status_code,
                upstream_response_preview_sanitized=preview,
                response_shape=response_shape,
                retry_after_seconds=retry_after_seconds,
            )
            raise error

        if resp.status_code >= 500:
            error = TalgilServerError(f"Talgil server error {resp.status_code}")
            self._set_last_diagnostic(
                error_type=error.__class__.__name__,
                error_message_sanitized=_sanitize_text(str(error)),
                upstream_status_code=resp.status_code,
                upstream_response_preview_sanitized=preview,
                response_shape=response_shape,
            )
            raise error
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb


 main
        if resp.status_code >= 400:
            error = TalgilClientError(f"Talgil client error {resp.status_code}")
            self._set_last_diagnostic(
                error_type=error.__class__.__name__,
                error_message_sanitized=_sanitize_text(str(error)),
                upstream_status_code=resp.status_code,
                upstream_response_preview_sanitized=preview,
                response_shape=response_shape,
            )
            raise error

        if not resp.content:
            self._set_last_diagnostic(response_shape="empty")
            return None
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb

        try:
            parsed = resp.json()
        except ValueError as exc:
            error = TalgilResponseError(f"Talgil returned invalid JSON ({method} {path})")
            self._set_last_diagnostic(
                error_type=error.__class__.__name__,
                error_message_sanitized=_sanitize_text(str(error)),
                upstream_status_code=resp.status_code,
                upstream_response_preview_sanitized=preview,
                response_shape="invalid_json",
            )
            raise error from exc

        shape = "dict" if isinstance(parsed, dict) else "list" if isinstance(parsed, list) else "text"
        self._set_last_diagnostic(response_shape=shape)
        return parsed

    async def get_runtime_status(self, *, use_cache: bool = True) -> TalgilRuntimeStatus:
        if use_cache:
            cached = self._get_status_cache()
            if cached is not None:
                return cached

        configured = self.configured
        if not configured:


        try:
            parsed = resp.json()
        except ValueError as exc:
            error = TalgilResponseError(f"Talgil returned invalid JSON ({method} {path})")
            self._set_last_diagnostic(
                error_type=error.__class__.__name__,
                error_message_sanitized=_sanitize_text(str(error)),
                upstream_status_code=resp.status_code,
                upstream_response_preview_sanitized=preview,
                response_shape="invalid_json",
            )
            raise error from exc

        shape = "dict" if isinstance(parsed, dict) else "list" if isinstance(parsed, list) else "text"
        self._set_last_diagnostic(response_shape=shape)
        return parsed

    async def check_auth(self) -> bool:
        if not self._api_key:
 main
            self._set_last_diagnostic(
                error_type="MissingApiKey",
                error_message_sanitized="TALGIL_API_KEY is not configured in this runtime.",
            )
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
            payload = TalgilRuntimeStatus(
                status="integration_ready",
                configured=False,
                live=False,
                targets=0,
                notes="TALGIL_API_KEY is not configured in this runtime.",
            )
            self._set_status_cache(payload)
            return payload

        try:
            targets = await self.list_targets()
            payload = TalgilRuntimeStatus(
                status="live",
                configured=True,
                live=True,
                targets=len(targets),
                notes="Live runtime checks succeeded against Talgil read endpoints.",
            )
            self._set_status_cache(payload)
            return payload
        except Exception as exc:
            self._set_last_diagnostic(
                error_type=self._last_diagnostic.error_type or exc.__class__.__name__,
                error_message_sanitized=self._last_diagnostic.error_message_sanitized or _sanitize_text(str(exc)),
                upstream_status_code=self._last_diagnostic.upstream_status_code,
                upstream_response_preview_sanitized=self._last_diagnostic.upstream_response_preview_sanitized,
                response_shape=self._last_diagnostic.response_shape,
                retry_after_seconds=self._last_diagnostic.retry_after_seconds,
            )
            payload = TalgilRuntimeStatus(
                status="configured",
                configured=True,
                live=False,
                targets=0,
                notes="TALGIL_API_KEY is present but runtime auth/read checks did not succeed.",
            )
            self._set_status_cache(payload)
            return payload

    async def check_auth(self) -> bool:
        status = await self.get_runtime_status(use_cache=True)
        return status.live

            return False
        try:
            targets = await self.list_targets()
            ok = isinstance(targets, list)
            if ok:
                self._set_last_diagnostic(response_shape="list")
            return ok
        except Exception as exc:
            self._set_last_diagnostic(
                error_type=exc.__class__.__name__,
                error_message_sanitized=_sanitize_text(str(exc)),
                upstream_status_code=self._last_diagnostic.upstream_status_code,
                upstream_response_preview_sanitized=self._last_diagnostic.upstream_response_preview_sanitized,
                response_shape=self._last_diagnostic.response_shape,
            )
            return False
 main

    async def list_targets(self) -> List[Dict[str, Any]]:
        payload = await self._get("/mytargets")
        rows = payload if isinstance(payload, list) else []
        return [
            {
                "id": str(row.get("ID")),
                "name": row.get("Name") or f"Controller {row.get('ID')}",
                "online": bool(row.get("Online", 0)),
                "provider": "talgil",
                "source": "talgil",
                "raw": row,
            }
            for row in rows
            if row.get("ID") is not None
        ]

    async def get_target_image(self, controller_id: str) -> Dict[str, Any]:
        payload = await self._get(f"/targets/{controller_id}/")
        return payload if isinstance(payload, dict) else {}

    async def list_farms(self) -> List[Dict[str, Any]]:
        return await self.list_targets()

    async def list_zones(self, farm_id: str) -> List[Dict[str, Any]]:
        image = await self.get_target_image(farm_id)
        sensors = image.get("Sensors") if isinstance(image, dict) else []
        sensors = sensors if isinstance(sensors, list) else []
        return [
            {
                "id": str(sensor.get("UID")),
                "name": sensor.get("Name") or sensor.get("UID") or "Sensor",
                "provider": "talgil",
                "source": "talgil",
                "farm_id": str(farm_id),
                "sensor_type": sensor.get("Type"),
                "units": sensor.get("Units"),
                "value": sensor.get("Value"),
                "controller_id": str(farm_id),
            }
            for sensor in sensors
            if sensor.get("UID")
        ]

    async def list_measures(self, zone_id: str) -> List[Dict[str, Any]]:
        return []

    async def get_measure_data(
        self,
        measure_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        return []

    async def create_irrigation(
        self,
        zone_id: str,
        start_time: datetime,
        duration_minutes: int,
        metadata: Optional[dict] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError("Talgil write path is not wired in FastAPI runtime")

    async def list_irrigations(
        self,
        zone_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        return []

    async def apply_schedule(
        self,
        controller_id: str,
        start_time: datetime,
        duration_min: float,
        zone_ids: Optional[list] = None,
        metadata: Optional[dict] = None,
    ) -> Dict:
        raise NotImplementedError("Talgil schedule apply is not wired in FastAPI runtime")

    async def cancel_schedule(self, controller_id: str, provider_schedule_id: str) -> bool:
        raise NotImplementedError("Talgil schedule cancel is not wired in FastAPI runtime")


class TalgilError(Exception):
    pass


class TalgilAuthError(TalgilError):
    pass


class TalgilServerError(TalgilError):
    pass


class TalgilClientError(TalgilError):
    pass


 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
class TalgilRateLimitError(TalgilClientError):
    def __init__(self, message: str, retry_after_seconds: Optional[int] = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)



 main
class TalgilResponseError(TalgilError):
    pass
