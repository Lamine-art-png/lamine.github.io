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


@router.get("/auth", response_model=TalgilAuthResponse)
async def check_auth() -> TalgilAuthResponse:
    adapter = AdapterRegistry.get_talgil()
    ok = await adapter.check_auth()
    return TalgilAuthResponse(
        authenticated=ok,
        api_url=adapter.api_url,
        message="Authentication successful" if ok else "Authentication failed or API key missing",
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
