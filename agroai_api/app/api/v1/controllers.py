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
    wiseconn = AdapterRegistry.get_wiseconn()
    talgil = AdapterRegistry.get_talgil()

    wiseconn_live = False
    wiseconn_farms: List[Dict[str, Any]] = []
    zones_by_farm: Dict[str, List[Dict[str, Any]]] = {}

    try:
        wiseconn_live = await wiseconn.check_auth()
        if wiseconn_live:
            wiseconn_farms = await wiseconn.list_farms()
            for farm in wiseconn_farms:
                farm_id = str(farm.get("id", ""))
                if not farm_id:
                    continue
                zones_by_farm[farm_id] = await wiseconn.list_zones(farm_id)
    except Exception:
        wiseconn_live = False
        wiseconn_farms = []
        zones_by_farm = {}

    all_wiseconn_zones = [zone for zones in zones_by_farm.values() for zone in zones]
    wiseconn_counter = Counter(
        str(zone.get("provider") or zone.get("source") or "unknown").lower()
        for zone in all_wiseconn_zones
    )

    talgil_live = False
    talgil_targets_count = 0
    talgil_zones_count = 0
    talgil_status: ControllerStatus = "configured"
    talgil_configured = talgil.configured
    talgil_notes = (
        "TALGIL_API_KEY is set, but runtime auth/read checks failed. Verify key scope and Talgil API availability."
    )

    try:
        status_payload = await talgil.get_runtime_status(use_cache=True)
        talgil_live = bool(status_payload.live)
        talgil_targets_count = int(status_payload.targets)
        talgil_configured = bool(status_payload.configured)
        talgil_status = status_payload.status
        talgil_notes = status_payload.notes
    except Exception:
        talgil_live = False
        talgil_targets_count = 0
        talgil_zones_count = 0
        talgil_status = "integration_ready" if not talgil_configured else "configured"

    if talgil_status not in ("live", "configured", "integration_ready"):
        talgil_status = "configured" if talgil_configured else "integration_ready"

    wiseconn_env = ControllerEnvironment(
        source="wiseconn",
        label="WiseConn",
        status="live" if wiseconn_live else "configured",
        live=bool(wiseconn_live),
        configured=True,
        farms=len(wiseconn_farms),
        zones=len(all_wiseconn_zones),
        notes=(
            "Live read path available via /v1/wiseconn endpoints."
            if wiseconn_live
            else "Configured in AGRO-AI API but not authenticated in this runtime."
        ),
        sources=dict(wiseconn_counter),
    )

    talgil_env = ControllerEnvironment(
        source="talgil",
        label="Talgil",
        status=talgil_status,
        live=bool(talgil_live),
        configured=talgil_configured,
        farms=talgil_targets_count,
        zones=talgil_zones_count,
        notes=talgil_notes,
        sources={"talgil": talgil_zones_count} if talgil_zones_count else {},
    )

    environments = [wiseconn_env, talgil_env]
    totals = {
        "farms": sum(item.farms for item in environments),
        "zones": sum(item.zones for item in environments),
        "live_environments": sum(1 for item in environments if item.live),
        "configured_environments": sum(1 for item in environments if item.configured),
    }

    return ControllerEnvironmentResponse(environments=environments, totals=totals)
