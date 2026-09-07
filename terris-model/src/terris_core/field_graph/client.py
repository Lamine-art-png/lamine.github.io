from __future__ import annotations

import os
from dataclasses import dataclass
import requests


@dataclass
class FieldGraphClient:
    base_url: str = os.getenv("TERRIS_FIELD_GRAPH_URL", "")
    api_key: str = os.getenv("TERRIS_FIELD_GRAPH_API_KEY", "")
    timeout: float = 8.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self, tenant_id: str) -> dict[str, str]:
        headers = {"x-terris-tenant-id": tenant_id, "content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    def field_state(self, tenant_id: str, field_id: str) -> dict:
        if not self.configured:
            return {"configured": False, "field_id": field_id, "facts": []}
        response = requests.get(
            f"{self.base_url.rstrip('/')}/v1/field-graph/fields/{field_id}/state",
            headers=self._headers(tenant_id),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def append_event(self, tenant_id: str, event: dict) -> dict:
        if not self.configured:
            raise RuntimeError("TERRIS_FIELD_GRAPH_URL is not configured")
        response = requests.post(
            f"{self.base_url.rstrip('/')}/v1/field-graph/events",
            headers=self._headers(tenant_id),
            json=event,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
