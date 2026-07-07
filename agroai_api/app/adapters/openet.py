"""OpenET API adapter for tenant-scoped self-service connections.

Uses the official OpenET API key flow and live endpoints. Credentials are passed
at construction time so callers can resolve them from the connector vault rather
than process-global environment variables.
"""
from __future__ import annotations

import ast
import gzip
import json
from typing import Any, Iterable, Optional

import httpx


class OpenETError(Exception):
    pass


class OpenETAuthError(OpenETError):
    pass


class OpenETRateLimitError(OpenETError):
    def __init__(self, message: str, retry_after_seconds: int | None = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class OpenETServerError(OpenETError):
    pass


class OpenETClientError(OpenETError):
    pass


class OpenETAdapter:
    """Async client for OpenET account, geodatabase, and raster APIs."""

    def __init__(self, api_url: str, api_key: str, timeout: int = 45):
        self.api_url = api_url.rstrip("/")
        self._api_key = api_key.strip()
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                timeout=httpx.Timeout(self._timeout),
                headers={"Authorization": self._api_key, "Accept": "application/json"},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _retry_after(response: httpx.Response) -> int | None:
        raw = response.headers.get("Retry-After", "").strip()
        return int(raw) if raw.isdigit() else None

    @staticmethod
    def _decode_payload(response: httpx.Response) -> Any:
        if not response.content:
            return None
        data = response.content
        is_gzip = data[:2] == b"\x1f\x8b" or "gzip" in response.headers.get("content-encoding", "").lower()
        if is_gzip:
            try:
                data = gzip.decompress(data)
            except OSError:
                pass
        text = data.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(text)
            except (SyntaxError, ValueError) as exc:
                raise OpenETClientError("OpenET returned an unsupported response payload") from exc

    def _handle(self, response: httpx.Response, method: str, path: str) -> Any:
        if response.status_code in {401, 403}:
            raise OpenETAuthError("OpenET authorization failed")
        if response.status_code == 429:
            raise OpenETRateLimitError("OpenET rate limit reached", self._retry_after(response))
        if response.status_code >= 500:
            raise OpenETServerError(f"OpenET upstream error {response.status_code}")
        if response.status_code >= 400:
            preview = response.text[:300].replace("\n", " ")
            raise OpenETClientError(f"OpenET {method} {path} failed ({response.status_code}): {preview}")
        return self._decode_payload(response)

    async def _get(self, path: str) -> Any:
        response = await self._get_client().get(path)
        return self._handle(response, "GET", path)

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        response = await self._get_client().post(path, json=payload)
        return self._handle(response, "POST", path)

    async def check_auth(self) -> bool:
        if not self.configured:
            return False
        try:
            await self.account_status()
            return True
        except OpenETAuthError:
            return False

    async def account_status(self) -> dict[str, Any]:
        payload = await self._get("/account/status")
        return payload if isinstance(payload, dict) else {"status": payload}

    async def field_ids_for_geometry(self, geometry: Iterable[float], version: float = 2.1) -> list[str]:
        payload = await self._post(
            "/geodatabase/metadata/ids",
            {"geometry": [float(value) for value in geometry], "version": version},
        )
        return self._extract_ids(payload)

    async def field_ids_for_asset(self, asset_id: str, version: float = 2.1) -> list[str]:
        payload = await self._post(
            "/geodatabase/metadata/ids",
            {"asset_id": str(asset_id), "version": version},
        )
        return self._extract_ids(payload)

    async def field_properties(self, field_ids: Iterable[str], version: float = 2.1) -> list[dict[str, Any]]:
        ids = [str(value) for value in field_ids][:100]
        if not ids:
            return []
        payload = await self._post(
            "/geodatabase/metadata/properties",
            {"field_ids": ids, "version": version},
        )
        return self._records(payload)

    async def field_boundaries(self, field_ids: Iterable[str], version: float = 2.1) -> Any:
        ids = [str(value) for value in field_ids][:100]
        return await self._post(
            "/geodatabase/metadata/boundaries",
            {"field_ids": ids, "version": version},
        )

    async def timeseries_by_field_ids(
        self,
        *,
        field_ids: Iterable[str],
        start_date: str,
        end_date: str,
        interval: str = "monthly",
        models: list[str] | None = None,
        variables: list[str] | None = None,
        version: float = 2.1,
    ) -> list[dict[str, Any]]:
        ids = [str(value) for value in field_ids][:100]
        if not ids:
            return []
        payload = await self._post(
            "/geodatabase/timeseries",
            {
                "date_range": [start_date, end_date],
                "interval": interval,
                "field_ids": ids,
                "models": models or ["Ensemble"],
                "variables": variables or ["ET"],
                "file_format": "JSON",
                "version": version,
            },
        )
        return self._records(payload)

    async def timeseries_for_polygon(
        self,
        *,
        geometry: Iterable[float],
        start_date: str,
        end_date: str,
        interval: str = "monthly",
        model: str = "Ensemble",
        variable: str = "ET",
        reference_et: str = "gridMET",
        reducer: str = "mean",
        units: str = "mm",
        version: float = 2.1,
    ) -> list[dict[str, Any]]:
        payload = await self._post(
            "/raster/timeseries/polygon",
            {
                "date_range": [start_date, end_date],
                "interval": interval,
                "geometry": [float(value) for value in geometry],
                "model": model,
                "variable": variable,
                "reference_et": reference_et,
                "reducer": reducer,
                "units": units,
                "file_format": "JSON",
                "version": version,
            },
        )
        return self._records(payload)

    async def upload_geojson(self, filename: str, data: bytes) -> dict[str, Any]:
        response = await self._get_client().post(
            "/account/upload",
            files={"file": (filename, data, "application/geo+json")},
        )
        payload = self._handle(response, "POST", "/account/upload")
        return payload if isinstance(payload, dict) else {"result": payload}

    @classmethod
    def _extract_ids(cls, payload: Any) -> list[str]:
        if isinstance(payload, list):
            result: list[str] = []
            for item in payload:
                if isinstance(item, (str, int)):
                    result.append(str(item))
                elif isinstance(item, dict):
                    value = item.get("field_id") or item.get("fieldId") or item.get("id")
                    if value is not None:
                        result.append(str(value))
            return result
        if isinstance(payload, dict):
            for key in ("field_ids", "ids", "data", "results", "items"):
                if key in payload:
                    return cls._extract_ids(payload[key])
        return []

    @classmethod
    def _records(cls, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item if isinstance(item, dict) else {"value": item} for item in payload]
        if isinstance(payload, dict):
            for key in ("data", "results", "items", "records", "timeseries", "features"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item if isinstance(item, dict) else {"value": item} for item in value]
            return [payload]
        return []
