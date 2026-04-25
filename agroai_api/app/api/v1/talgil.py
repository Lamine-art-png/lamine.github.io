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
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
    retry_after_seconds: Optional[int] = None

 main


class TalgilSensorsResponse(BaseModel):
    ok: bool
    status: str
    live: bool
    sensors: List[Dict[str, Any]]
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    upstream_status_code: Optional[int] = None
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
    retry_after_seconds: Optional[int] = None

 main


@router.get("/auth", response_model=TalgilAuthResponse)
async def check_auth() -> TalgilAuthResponse:
    adapter = AdapterRegistry.get_talgil()
    status = await adapter.get_runtime_status(use_cache=True)
    return TalgilAuthResponse(
        authenticated=status.live,
        api_url=adapter.api_url,
        message="Authentication successful" if status.live else "Authentication failed or API key missing",
    )


@router.get("/status", response_model=TalgilStatusResponse)
async def get_status() -> TalgilStatusResponse:
    adapter = AdapterRegistry.get_talgil()
    status = await adapter.get_runtime_status(use_cache=True)
    diagnostic = adapter.last_diagnostic

    diagnostic = adapter.last_diagnostic
    return TalgilStatusResponse(
        status=status.status,
        configured=status.configured,
        live=status.live,
        api_url=adapter.api_url,
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
        targets=status.targets,
        sensors=0,
        notes=status.notes,

        targets=len(targets),
        sensors=sensors,
        notes=notes,
 main
        last_error_type=diagnostic.error_type,
        last_error_message_sanitized=diagnostic.error_message_sanitized,
        upstream_status_code=diagnostic.upstream_status_code,
        upstream_response_preview_sanitized=diagnostic.upstream_response_preview_sanitized,
        response_shape=diagnostic.response_shape,
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
        retry_after_seconds=diagnostic.retry_after_seconds,

 main
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
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
    configured = adapter.configured

    try:
        status = await adapter.get_runtime_status(use_cache=True)
        if not status.live:
            diagnostic = adapter.last_diagnostic
            error_type = "rate_limited" if diagnostic.upstream_status_code == 429 else diagnostic.error_type
            return TalgilSensorsResponse(
                ok=False,
                status=status.status,
                live=False,
                sensors=[],
                error_type=error_type,
                error_message=diagnostic.error_message_sanitized,
                upstream_status_code=diagnostic.upstream_status_code,
                retry_after_seconds=diagnostic.retry_after_seconds,
            )

        targets = await adapter.list_targets()
        sensors: List[Dict[str, Any]] = []

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
 main
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
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
            error_type=("rate_limited" if diagnostic.upstream_status_code == 429 else None)
            or diagnostic.error_type
            or exc.__class__.__name__,
            error_message=diagnostic.error_message_sanitized or str(exc),
            upstream_status_code=diagnostic.upstream_status_code,
            retry_after_seconds=diagnostic.retry_after_seconds,

            error_type=diagnostic.error_type or exc.__class__.__name__,
            error_message=diagnostic.error_message_sanitized or str(exc),
            upstream_status_code=diagnostic.upstream_status_code,
 main
        )
