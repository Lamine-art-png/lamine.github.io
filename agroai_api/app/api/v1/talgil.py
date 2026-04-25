"""Talgil runtime routes backed by real read-path implementation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    auth_header_used: str = "TLG-API-Key"
    auth_check_path: str = "/mytargets"
    last_error_type: Optional[str] = None
    last_error_message_sanitized: Optional[str] = None
    upstream_status_code: Optional[int] = None
    upstream_response_preview_sanitized: Optional[str] = None
    response_shape: Optional[str] = None


class TalgilSensorsResponse(BaseModel):
    ok: bool
    status: str
    live: bool
    sensors: List[Dict[str, Any]]
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    upstream_status_code: Optional[int] = None


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

    diagnostic = adapter.last_diagnostic
    return TalgilStatusResponse(
        status=status,
        configured=configured,
        live=live,
        api_url=adapter.api_url,
        targets=len(targets),
        sensors=sensors,
        notes=notes,
        last_error_type=diagnostic.error_type,
        last_error_message_sanitized=diagnostic.error_message_sanitized,
        upstream_status_code=diagnostic.upstream_status_code,
        upstream_response_preview_sanitized=diagnostic.upstream_response_preview_sanitized,
        response_shape=diagnostic.response_shape,
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


@router.get("/sensors", response_model=TalgilSensorsResponse)
async def list_sensors() -> TalgilSensorsResponse:
    adapter = AdapterRegistry.get_talgil()
    sensors: List[Dict[str, Any]] = []
    configured = adapter.configured

    try:
        live = await adapter.check_auth() if configured else False
        if not live:
            status = "configured" if configured else "integration_ready"
            diagnostic = adapter.last_diagnostic
            return TalgilSensorsResponse(
                ok=False,
                status=status,
                live=False,
                sensors=[],
                error_type=diagnostic.error_type,
                error_message=diagnostic.error_message_sanitized,
                upstream_status_code=diagnostic.upstream_status_code,
            )

        targets = await adapter.list_targets()
        for target in targets:
            target_id = str(target.get("id", ""))
            if not target_id:
                continue
            sensors.extend(await adapter.list_zones(target_id))
        return TalgilSensorsResponse(ok=True, status="live", live=True, sensors=sensors)
    except Exception as exc:
        diagnostic = adapter.last_diagnostic
        return TalgilSensorsResponse(
            ok=False,
            status="configured" if configured else "integration_ready",
            live=False,
            sensors=[],
            error_type=diagnostic.error_type or exc.__class__.__name__,
            error_message=diagnostic.error_message_sanitized or str(exc),
            upstream_status_code=diagnostic.upstream_status_code,
        )
