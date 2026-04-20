"""Controller environment summary endpoints for AGRO-AI portal framing."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.adapters.registry import AdapterRegistry

router = APIRouter(prefix="/controllers", tags=["controllers"])


ControllerStatus = Literal["live", "configured", "integration_ready"]


class ControllerEnvironment(BaseModel):
    source: str
    label: str
    status: ControllerStatus
    live: bool
    configured: bool
    farms: int = 0
    zones: int = 0
    notes: str
    sources: Dict[str, int] = Field(default_factory=dict)


class ControllerEnvironmentResponse(BaseModel):
    environments: List[ControllerEnvironment]
    totals: Dict[str, int]


@router.get("/environments", response_model=ControllerEnvironmentResponse)
async def get_controller_environments() -> ControllerEnvironmentResponse:
    """Return source-aware controller environment summary for portal UI."""
    adapter = AdapterRegistry.get_wiseconn()
    wiseconn_live = False
    wiseconn_farms: List[Dict[str, Any]] = []
    zones_by_farm: Dict[str, List[Dict[str, Any]]] = {}

    try:
        wiseconn_live = await adapter.check_auth()
        if wiseconn_live:
            wiseconn_farms = await adapter.list_farms()
            for farm in wiseconn_farms:
                farm_id = str(farm.get("id", ""))
                if not farm_id:
                    continue
                zones_by_farm[farm_id] = await adapter.list_zones(farm_id)
    except Exception:
        wiseconn_live = False
        wiseconn_farms = []
        zones_by_farm = {}

    all_zones = [zone for zones in zones_by_farm.values() for zone in zones]
    source_counter = Counter(
        str(zone.get("provider") or zone.get("source") or "unknown").lower()
        for zone in all_zones
    )

    wiseconn_env = ControllerEnvironment(
        source="wiseconn",
        label="WiseConn",
        status="live" if wiseconn_live else "configured",
        live=bool(wiseconn_live),
        configured=True,
        farms=len(wiseconn_farms),
        zones=len(all_zones),
        notes=(
            "Live read path available via /v1/wiseconn endpoints."
            if wiseconn_live
            else "Configured in AGRO-AI API but not authenticated in this runtime."
        ),
        sources=dict(source_counter),
    )

    talgil_env = ControllerEnvironment(
        source="talgil",
        label="Talgil",
        status="integration_ready",
        live=False,
        configured=False,
        farms=0,
        zones=0,
        notes=(
            "Preserved integration artifacts are present in-repo, but tenant-scoped "
            "runtime routes are not wired in this FastAPI deployment yet."
        ),
        sources={},
    )

    environments = [wiseconn_env, talgil_env]
    totals = {
        "farms": sum(item.farms for item in environments),
        "zones": sum(item.zones for item in environments),
        "live_environments": sum(1 for item in environments if item.live),
        "configured_environments": sum(1 for item in environments if item.configured),
    }

    return ControllerEnvironmentResponse(
        environments=environments,
        totals=totals,
    )
