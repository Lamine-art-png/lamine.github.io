"""WiseConn API adapter — real HTTP client for DropControl platform.

This adapter handles both the read path (discovery, telemetry) and
write path (irrigation creation) against the WiseConn REST API.

ASSUMPTIONS (documented and isolated):
1. Base URL: https://api.wiseconn.com (configurable via WISECONN_API_URL)
2. Auth: API key passed in 'api_key' header (from wiseconn-node patterns)
3. Entity hierarchy: account → farms → zones → measures → data
4. Time params: initTime/endTime in 'yyyy/MM/dd HH:mm' format
5. Irrigations created via POST to zone-scoped endpoint
6. Responses are JSON with camelCase keys

If any assumption is wrong, the adapter logs the raw response and raises
a clear error so we can adjust without rewriting the core.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.adapters.base import ControllerAdapter, DataProviderAdapter
from app.schemas.wiseconn import (
    CanonicalDataPoint,
    CanonicalFarm,
    CanonicalIrrigation,
    CanonicalMeasure,
    CanonicalZone,
    ExecutionStatus,
    WCDataPointRaw,
    WCFarmRaw,
    WCIrrigationRaw,
    WCMeasureRaw,
    WCZoneRaw,
    normalize_unit,
    normalize_variable,
)

logger = logging.getLogger(__name__)

# WiseConn date format observed in wiseconn-node library
WC_DATE_FMT = "%Y/%m/%d %H:%M"

# Retry on transient HTTP errors
RETRYABLE_ERRORS = (httpx.TimeoutException, httpx.ConnectError)


class WiseConnAdapter(ControllerAdapter, DataProviderAdapter):
    """Production WiseConn adapter with real HTTP calls.

    Implements both ControllerAdapter (write path) and
    DataProviderAdapter (read path).
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

        # Track whether we've confirmed auth
        self._auth_verified = False

        if not api_key:
            logger.warning(
                "WiseConn adapter initialized without API key. "
                "Set WISECONN_API_KEY env var for live access."
            )
        else:
            logger.info(
                "WiseConn adapter initialized for %s (key: %s...)",
                self.api_url,
                api_key[:4] if len(api_key) > 4 else "****",
            )

    # ------------------------------------------------------------------
    # HTTP client management
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                timeout=httpx.Timeout(self._timeout),
                headers=self._auth_headers(),
                follow_redirects=True,
            )
        return self._client

    def _auth_headers(self) -> Dict[str, str]:
        """Build authentication headers.

        Assumption: WiseConn uses 'api_key' header.
        If this is wrong, also try 'apikey', 'x-api-key', 'Authorization: Bearer'.
        The check_auth method probes all variants.
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["api_key"] = self._api_key
        return headers

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core HTTP helpers with retry and logging
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(RETRYABLE_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        """HTTP GET with retries, logging, and error handling."""
        client = self._get_client()
        logger.debug("GET %s params=%s", path, params)
        resp = await client.get(path, params=params)
        return self._handle_response(resp, "GET", path)

    @retry(
        retry=retry_if_exception_type(RETRYABLE_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _post(self, path: str, json_data: Optional[Dict] = None) -> Any:
        """HTTP POST with retries, logging, and error handling."""
        client = self._get_client()
        # Redact any sensitive fields before logging
        safe_log = {k: v for k, v in (json_data or {}).items() if k != "api_key"}
        logger.debug("POST %s body=%s", path, safe_log)
        resp = await client.post(path, json=json_data)
        return self._handle_response(resp, "POST", path)

    def _handle_response(self, resp: httpx.Response, method: str, path: str) -> Any:
        """Unified response handling with structured logging."""
        if resp.status_code == 401:
            logger.error("WiseConn auth failed (%s %s): 401", method, path)
            raise WiseConnAuthError("Authentication failed. Check WISECONN_API_KEY.")
        if resp.status_code == 403:
            logger.error("WiseConn forbidden (%s %s): 403", method, path)
            raise WiseConnAuthError("Access forbidden. API key may lack permissions.")
        if resp.status_code == 404:
            logger.warning("WiseConn not found (%s %s): 404", method, path)
            return None
        if resp.status_code == 429:
            logger.warning("WiseConn rate limited (%s %s)", method, path)
            raise WiseConnRateLimitError("Rate limited by WiseConn API.")
        if resp.status_code >= 500:
            logger.error(
                "WiseConn server error (%s %s): %d", method, path, resp.status_code
            )
            raise WiseConnServerError(f"Server error {resp.status_code}")
        if resp.status_code >= 400:
            logger.error(
                "WiseConn client error (%s %s): %d body=%s",
                method, path, resp.status_code, resp.text[:500],
            )
            raise WiseConnClientError(
                f"Client error {resp.status_code}: {resp.text[:200]}"
            )

        # Success
        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            logger.warning("Non-JSON response from %s %s: %s", method, path, resp.text[:200])
            return resp.text

    # ------------------------------------------------------------------
    # DataProviderAdapter: Auth
    # ------------------------------------------------------------------

    async def check_auth(self) -> bool:
        """Verify API key is valid.

        Tries multiple auth header patterns if the first fails.
        """
        if not self._api_key:
            return False

        # Try primary: api_key header
        try:
            result = await self._get("/farms")
            if result is not None:
                self._auth_verified = True
                logger.info("WiseConn auth verified via api_key header")
                return True
        except WiseConnAuthError:
            pass

        # Try alternative headers
        alt_headers = [
            ("apikey", self._api_key),
            ("x-api-key", self._api_key),
            ("Authorization", f"Bearer {self._api_key}"),
        ]
        for header_name, header_value in alt_headers:
            try:
                client = self._get_client()
                resp = await client.get(
                    "/farms",
                    headers={header_name: header_value, "Accept": "application/json"},
                )
                if resp.status_code < 400:
                    # Found the right header — update client
                    logger.info("WiseConn auth works with header: %s", header_name)
                    if self._client and not self._client.is_closed:
                        await self._client.aclose()
                    self._client = httpx.AsyncClient(
                        base_url=self.api_url,
                        timeout=httpx.Timeout(self._timeout),
                        headers={
                            header_name: header_value,
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                        follow_redirects=True,
                    )
                    self._auth_verified = True
                    return True
            except Exception as e:
                logger.debug("Auth header %s failed: %s", header_name, e)
                continue

        logger.error("WiseConn auth failed with all header variants")
        return False

    # ------------------------------------------------------------------
    # DataProviderAdapter: Discovery
    # ------------------------------------------------------------------

    async def list_farms(self) -> List[Dict[str, Any]]:
        """Discover farms. Returns raw API response as list of dicts."""
        result = await self._get("/farms")
        if result is None:
            return []
        if isinstance(result, list):
            return result
        # Some APIs wrap in {"farms": [...]} or {"data": [...]}
        if isinstance(result, dict):
            for key in ("farms", "data", "items", "results"):
                if key in result and isinstance(result[key], list):
                    return result[key]
            return [result]
        return []

    async def list_zones(self, farm_id: str) -> List[Dict[str, Any]]:
        """List zones for a farm."""
        result = await self._get(f"/farms/{farm_id}/zones")
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("zones", "data", "items"):
                if key in result and isinstance(result[key], list):
                    return result[key]
            return [result]
        return []

    async def list_measures(self, zone_id: str) -> List[Dict[str, Any]]:
        """List measures/sensors for a zone."""
        result = await self._get(f"/zones/{zone_id}/measures")
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("measures", "data", "items"):
                if key in result and isinstance(result[key], list):
                    return result[key]
            return [result]
        return []

    # ------------------------------------------------------------------
    # DataProviderAdapter: Telemetry read path
    # ------------------------------------------------------------------

    async def get_measure_data(
        self,
        measure_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Get time-series data for a measure.

        Uses initTime/endTime query params per wiseconn-node library.
        """
        params = {
            "initTime": start_time.strftime(WC_DATE_FMT),
            "endTime": end_time.strftime(WC_DATE_FMT),
        }
        result = await self._get(f"/measures/{measure_id}/data", params=params)
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("data", "items", "values", "dataPoints"):
                if key in result and isinstance(result[key], list):
                    return result[key]
            return [result]
        return []

    async def get_last_data(self, measure_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent data point for a measure."""
        result = await self._get(f"/measures/{measure_id}/data/last")
        if result is None:
            # Fallback: get last 1 hour of data
            now = datetime.utcnow()
            data = await self.get_measure_data(
                measure_id, now - timedelta(hours=24), now
            )
            return data[-1] if data else None
        if isinstance(result, list):
            return result[-1] if result else None
        return result

    # ------------------------------------------------------------------
    # DataProviderAdapter: Irrigation read/write
    # ------------------------------------------------------------------

    async def list_irrigations(
        self,
        zone_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List irrigation events for a zone."""
        params: Dict[str, str] = {}
        if start_time:
            params["initTime"] = start_time.strftime(WC_DATE_FMT)
        if end_time:
            params["endTime"] = end_time.strftime(WC_DATE_FMT)

        result = await self._get(f"/zones/{zone_id}/irrigations", params=params)
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("irrigations", "data", "items"):
                if key in result and isinstance(result[key], list):
                    return result[key]
            return [result]
        return []

    async def create_irrigation(
        self,
        zone_id: str,
        start_time: datetime,
        duration_minutes: int,
        metadata: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Create a minimal irrigation action in the demo environment.

        Designed to be the smallest safe write that proves the path works.
        """
        payload: Dict[str, Any] = {
            "start": start_time.strftime(WC_DATE_FMT),
            "minutes": duration_minutes,
        }
        if metadata:
            payload.update(metadata)

        logger.info(
            "Creating irrigation: zone=%s start=%s duration=%dmin",
            zone_id, start_time.isoformat(), duration_minutes,
        )

        result = await self._post(f"/zones/{zone_id}/irrigations", json_data=payload)
        if result is None:
            raise WiseConnClientError("Empty response from irrigation creation")
        return result if isinstance(result, dict) else {"raw": result}

    # ------------------------------------------------------------------
    # ControllerAdapter: Write path (legacy interface compatibility)
    # ------------------------------------------------------------------

    async def apply_schedule(
        self,
        controller_id: str,
        start_time: datetime,
        duration_min: float,
        zone_ids: Optional[list] = None,
        metadata: Optional[dict] = None,
    ) -> Dict:
        """Apply schedule via WiseConn API.

        Maps the ControllerAdapter interface to WiseConn irrigation creation.
        controller_id is treated as a zone_id in WiseConn's model.
        """
        zone_id = controller_id  # WiseConn zones are the control units
        if zone_ids and len(zone_ids) > 0:
            zone_id = zone_ids[0]

        result = await self.create_irrigation(
            zone_id=zone_id,
            start_time=start_time,
            duration_minutes=int(duration_min),
            metadata=metadata,
        )

        provider_id = str(result.get("id", result.get("irrigationId", "")))
        return {
            "provider_schedule_id": provider_id,
            "status": "accepted",
            "raw": result,
        }

    async def cancel_schedule(
        self, controller_id: str, provider_schedule_id: str
    ) -> bool:
        """Cancel irrigation via WiseConn API."""
        try:
            await self._post(
                f"/irrigations/{provider_schedule_id}/cancel",
                json_data={},
            )
            return True
        except Exception as e:
            logger.error("Failed to cancel irrigation %s: %s", provider_schedule_id, e)
            return False

    # ------------------------------------------------------------------
    # Canonical mapping: raw WiseConn → AGRO-AI models
    # ------------------------------------------------------------------

    def map_farm(self, raw: Dict[str, Any]) -> CanonicalFarm:
        """Map a raw WiseConn farm to AGRO-AI canonical farm."""
        parsed = WCFarmRaw.model_validate(raw)
        return CanonicalFarm(
            provider="wiseconn",
            provider_id=str(parsed.id),
            name=parsed.name or f"Farm {parsed.id}",
            latitude=parsed.latitude,
            longitude=parsed.longitude,
            timezone=parsed.timezone,
            raw=raw,
        )

    def map_zone(self, raw: Dict[str, Any], farm_id: str) -> CanonicalZone:
        """Map a raw WiseConn zone to AGRO-AI canonical zone."""
        parsed = WCZoneRaw.model_validate(raw)
        # type can be a list (e.g. ['Soil', 'Irrigation']) or a string
        zone_type = parsed.type
        if isinstance(zone_type, list):
            zone_type = ",".join(str(t) for t in zone_type)
        return CanonicalZone(
            provider="wiseconn",
            provider_id=str(parsed.id),
            farm_provider_id=farm_id,
            name=parsed.name or f"Zone {parsed.id}",
            zone_type=zone_type,
            area_ha=parsed.area * 0.404686 if parsed.area else None,  # acres→ha
            raw=raw,
        )

    def map_measure(self, raw: Dict[str, Any], zone_id: str) -> CanonicalMeasure:
        """Map a raw WiseConn measure to AGRO-AI canonical measure."""
        parsed = WCMeasureRaw.model_validate(raw)
        return CanonicalMeasure(
            provider="wiseconn",
            provider_id=str(parsed.id),
            zone_provider_id=zone_id,
            name=parsed.name or f"Measure {parsed.id}",
            variable=normalize_variable(parsed.name, parsed.unit),
            unit=normalize_unit(parsed.unit),
            depth_inches=parsed.depth,
            raw=raw,
        )

    def map_data_points(
        self,
        raw_data: List[Dict[str, Any]],
        measure: CanonicalMeasure,
    ) -> List[CanonicalDataPoint]:
        """Map raw WiseConn data points to canonical time series."""
        points = []
        for raw in raw_data:
            parsed = WCDataPointRaw.model_validate(raw)
            if parsed.value is None:
                continue

            # Parse timestamp
            ts = self._parse_timestamp(parsed.time)
            if ts is None:
                continue

            points.append(
                CanonicalDataPoint(
                    timestamp=ts,
                    value=parsed.value,
                    unit=measure.unit,
                    variable=measure.variable,
                    depth_inches=measure.depth_inches,
                    source_measure_id=measure.provider_id,
                    provider="wiseconn",
                )
            )
        return points

    def map_irrigation(
        self, raw: Dict[str, Any], zone_id: str
    ) -> CanonicalIrrigation:
        """Map raw WiseConn irrigation to canonical model."""
        parsed = WCIrrigationRaw.model_validate(raw)
        start = self._parse_timestamp(parsed.start) if parsed.start else None
        end = self._parse_timestamp(parsed.end) if parsed.end else None
        return CanonicalIrrigation(
            provider="wiseconn",
            provider_id=str(parsed.id) if parsed.id else None,
            zone_provider_id=zone_id,
            start_time=start,
            end_time=end,
            duration_minutes=parsed.duration_minutes,
            status=ExecutionStatus.APPLIED,
            program_name=parsed.program_name,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        """Parse various timestamp formats from WiseConn."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            # Epoch milliseconds
            if value > 1e12:
                return datetime.utcfromtimestamp(value / 1000.0)
            return datetime.utcfromtimestamp(value)
        if isinstance(value, str):
            for fmt in (
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
            # Try ISO parse as last resort
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except Exception:
                pass
        logger.warning("Could not parse WiseConn timestamp: %s", value)
        return None


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class WiseConnError(Exception):
    """Base WiseConn adapter error."""
    pass


class WiseConnAuthError(WiseConnError):
    """Authentication/authorization failure."""
    pass


class WiseConnRateLimitError(WiseConnError):
    """Rate limit exceeded."""
    pass


class WiseConnServerError(WiseConnError):
    """WiseConn server-side error (5xx)."""
    pass


class WiseConnClientError(WiseConnError):
    """Client-side error (4xx)."""
    pass
