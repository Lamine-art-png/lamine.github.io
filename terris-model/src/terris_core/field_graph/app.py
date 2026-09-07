from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from terris_core.field_graph.store import FieldGraphStore


class EventRequest(BaseModel):
    event_type: str
    field_id: str
    crop_cycle_id: str | None = None
    truth_label: str
    source: str
    observed_at: str | None = None
    payload: dict[str, Any]
    provenance: dict[str, Any] = Field(default_factory=dict)
    training_consent: bool = False
    event_id: str | None = None
    idempotency_key: str | None = None


@lru_cache(maxsize=1)
def get_store() -> FieldGraphStore:
    return FieldGraphStore()


app = FastAPI(title="Terris Field Graph", version="0.1.0")


@app.get("/health")
def health():
    return {"ok": True, "service": "terris-field-graph"}


@app.post("/v1/field-graph/events")
def append_event(request: EventRequest, x_terris_tenant_id: str = Header(min_length=1)):
    try:
        return get_store().append_event(x_terris_tenant_id, request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Field Graph event persistence failed") from exc


@app.get("/v1/field-graph/fields/{field_id}/state")
def field_state(field_id: str, x_terris_tenant_id: str = Header(min_length=1)):
    try:
        return get_store().field_state(x_terris_tenant_id, field_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Field Graph state retrieval failed") from exc


@app.get("/v1/field-graph/training-export")
def training_export(x_terris_tenant_id: str = Header(min_length=1)):
    try:
        return {"events": get_store().training_export(x_terris_tenant_id)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Field Graph training export failed") from exc
