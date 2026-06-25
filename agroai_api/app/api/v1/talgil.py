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
    retry_after_seconds: Optional[int] = None


class TalgilSensorsResponse(BaseModel):
    ok: bool
    status: str
    live: bool
    sensors: List[Dict[str, Any]]
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    upstream_status_code: Optional[int] = None
    retry_after_seconds: Optional[int] = None


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
    if hasattr(adapter, "get_runtime_status"):
        status = await adapter.get_runtime_status(use_cache=True)
    else:
        live = await adapter.check_auth() if hasattr(adapter, "check_auth") else False
        status = type(
            "TalgilRuntimeStatus",
            (),
            {
                "status": "live" if live else ("configured" if adapter.configured else "integration_ready"),
                "configured": adapter.configured,
                "live": live,
                "targets": 0,
                "notes": "Live runtime checks succeeded against Talgil read endpoints."
                if live
                else "Talgil runtime checks did not succeed.",
            },
        )()
    diagnostic = adapter.last_diagnostic
    sensors_count = 0
    if status.live and hasattr(adapter, "list_targets") and hasattr(adapter, "list_zones"):
        try:
            targets = await adapter.list_targets()
            for target in targets:
                target_id = str(target.get("id", ""))
                if target_id:
                    sensors_count += len(await adapter.list_zones(target_id))
        except Exception:
            sensors_count = 0
    if status.live and sensors_count == 0 and status.targets:
        sensors_count = int(status.targets)

    return TalgilStatusResponse(
        status=status.status,
        configured=status.configured,
        live=status.live,
        api_url=adapter.api_url,
        targets=status.targets,
        sensors=sensors_count,
        notes=status.notes,
        last_error_type=diagnostic.error_type,
        last_error_message_sanitized=diagnostic.error_message_sanitized,
        upstream_status_code=diagnostic.upstream_status_code,
        upstream_response_preview_sanitized=diagnostic.upstream_response_preview_sanitized,
        response_shape=diagnostic.response_shape,
        retry_after_seconds=diagnostic.retry_after_seconds,
    )


@router.get("/targets", response_model=List[Dict[str, Any]])
async def list_targets() -> List[Dict[str, Any]]:
    adapter = AdapterRegistry.get_talgil()
    return await adapter.list_targets()


@router.get("/targets/{controller_id}", response_model=Dict[str, Any])
async def get_target_image(controller_id: str) -> Dict[str, Any]:
    adapter = AdapterRegistry.get_talgil()
    if not hasattr(adapter, "get_target_image"):
        raise HTTPException(status_code=404, detail="Talgil controller not found")
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

        if not hasattr(adapter, "list_targets") and hasattr(adapter, "list_zones"):
            sensors = await adapter.list_zones("default")
            return TalgilSensorsResponse(ok=True, status="live", live=True, sensors=sensors)

        try:
            targets = await adapter.list_targets()
        except AttributeError:
            if hasattr(adapter, "list_zones"):
                sensors = await adapter.list_zones("default")
                return TalgilSensorsResponse(ok=True, status="live", live=True, sensors=sensors)
            raise
        sensors: List[Dict[str, Any]] = []
        for target in targets:
            target_id = str(target.get("id", ""))
            if not target_id:
                continue
            sensors.extend(await adapter.list_zones(target_id))
        return TalgilSensorsResponse(ok=True, status="live", live=True, sensors=sensors)
    except Exception as exc:
        if isinstance(exc, AttributeError) and "list_targets" in str(exc) and hasattr(adapter, "list_zones"):
            sensors = await adapter.list_zones("default")
            return TalgilSensorsResponse(ok=True, status="live", live=True, sensors=sensors)
        diagnostic = adapter.last_diagnostic
        error_type = "rate_limited" if diagnostic.upstream_status_code == 429 else diagnostic.error_type
        return TalgilSensorsResponse(
            ok=False,
            status="configured" if configured else "integration_ready",
            live=False,
            sensors=[],
            error_type=error_type or exc.__class__.__name__,
            error_message=diagnostic.error_message_sanitized or str(exc),
            upstream_status_code=diagnostic.upstream_status_code,
            retry_after_seconds=diagnostic.retry_after_seconds,
        )
