"""Talgil runtime routes backed by real read-path implementation."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.adapters.registry import AdapterRegistry

router = APIRouter(prefix="/talgil", tags=["talgil"])


class TalgilAuthResponse(BaseModel):
    authenticated: bool
    api_url: str
    message: str


class TalgilStatusResponse(BaseModel):
    status: str
    configured: bool
    live: bool
    api_url: str
    targets: int
    sensors: int
    notes: str


@router.get("/auth", response_model=TalgilAuthResponse)
async def check_auth() -> TalgilAuthResponse:
    adapter = AdapterRegistry.get_talgil()
    ok = await adapter.check_auth()
    return TalgilAuthResponse(
        authenticated=ok,
        api_url=adapter.api_url,
        message="Authentication successful" if ok else "Authentication failed or API key missing",
    )


@router.get("/status", response_model=TalgilStatusResponse)
async def get_status() -> TalgilStatusResponse:
    adapter = AdapterRegistry.get_talgil()
    configured = adapter.configured
    live = False
    targets: List[Dict[str, Any]] = []
    sensors = 0

    if configured:
        live = await adapter.check_auth()
        if live:
            targets = await adapter.list_targets()
            for target in targets:
                target_id = str(target.get("id", ""))
                if not target_id:
                    continue
                sensors += len(await adapter.list_zones(target_id))

    if live:
        status = "live"
        notes = "Live runtime checks succeeded against Talgil read endpoints."
    elif configured:
        status = "configured"
        notes = "TALGIL_API_KEY is present but runtime auth/read checks did not succeed."
    else:
        status = "integration_ready"
        notes = "TALGIL_API_KEY is not configured in this runtime."

    return TalgilStatusResponse(
        status=status,
        configured=configured,
        live=live,
        api_url=adapter.api_url,
        targets=len(targets),
        sensors=sensors,
        notes=notes,
    )


@router.get("/targets", response_model=List[Dict[str, Any]])
async def list_targets() -> List[Dict[str, Any]]:
    adapter = AdapterRegistry.get_talgil()
    return await adapter.list_targets()


@router.get("/targets/{controller_id}", response_model=Dict[str, Any])
async def get_target_image(controller_id: str) -> Dict[str, Any]:
    adapter = AdapterRegistry.get_talgil()
    image = await adapter.get_target_image(controller_id)
    if not image:
        raise HTTPException(status_code=404, detail="Talgil controller not found")
    return image


@router.get("/farms", response_model=List[Dict[str, Any]])
async def list_farms() -> List[Dict[str, Any]]:
    adapter = AdapterRegistry.get_talgil()
    return await adapter.list_farms()


@router.get("/farms/{farm_id}/zones", response_model=List[Dict[str, Any]])
async def list_farm_zones(farm_id: str) -> List[Dict[str, Any]]:
    adapter = AdapterRegistry.get_talgil()
    return await adapter.list_zones(farm_id)


@router.get("/sensors", response_model=List[Dict[str, Any]])
async def list_sensors() -> List[Dict[str, Any]]:
    adapter = AdapterRegistry.get_talgil()
    targets = await adapter.list_targets()
    sensors: List[Dict[str, Any]] = []

    for target in targets:
        target_id = str(target.get("id", ""))
        if not target_id:
            continue
        sensors.extend(await adapter.list_zones(target_id))

    return sensors
