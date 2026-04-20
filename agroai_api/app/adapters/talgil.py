"""Talgil API adapter for read-only runtime surfaces in AGRO-AI FastAPI."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.adapters.base import ControllerAdapter, DataProviderAdapter

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (httpx.TimeoutException, httpx.ConnectError)


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

        if not api_key:
            logger.info("Talgil adapter initialized without TALGIL_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

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
        if resp.status_code in (401, 403):
            raise TalgilAuthError(f"Talgil auth failed ({method} {path})")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 500:
            raise TalgilServerError(f"Talgil server error {resp.status_code}")
        if resp.status_code >= 400:
            raise TalgilClientError(f"Talgil client error {resp.status_code}: {resp.text[:200]}")

        if not resp.content:
            return None
        return resp.json()

    async def check_auth(self) -> bool:
        if not self._api_key:
            return False
        try:
            targets = await self.list_targets()
            return isinstance(targets, list)
        except Exception:
            return False

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
        # FastAPI portal already expects farm-grouping semantics.
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
