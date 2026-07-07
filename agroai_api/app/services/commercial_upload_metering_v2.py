"""Install one commercial evidence-import meter around every live upload route."""
from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Iterable

from fastapi import HTTPException, status
from fastapi.routing import APIRoute

from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization, QuotaReservation
from app.services.quota import commit_reservation, release_reservation, reserve_quota

_TARGET_PATHS = {
    "/evidence/upload",
    "/evidence/upload-stream",
    "/connectors/connections/{connection_id}/upload",
    "/connectors/connections/{connection_id}/upload-stream",
}


def _release(db, reservation_id: str, reason: str) -> None:
    row = db.get(QuotaReservation, reservation_id)
    if row is not None and row.state == "reserved":
        release_reservation(db, row, reason=reason)
        db.commit()


def _scope(db, tenant_id: str, kwargs: dict[str, Any]) -> tuple[str | None, str]:
    workspace_id = kwargs.get("workspace_id")
    provider = str(kwargs.get("provider") or "manual_csv")
    connection_id = kwargs.get("connection_id")
    if connection_id:
        connection = db.get(ConnectorConnection, connection_id)
        if connection is not None and connection.tenant_id == tenant_id:
            workspace_id = connection.workspace_id
            provider = connection.provider
    return workspace_id, provider


def _wrap_route(route: APIRoute) -> None:
    if getattr(route, "_agroai_commercial_metered", False):
        return
    original = route.dependant.call
    path = route.path

    @wraps(original)
    async def metered(*args, **kwargs):
        db = kwargs.get("db")
        tenant_id = kwargs.get("tenant_id")
        if db is None or not tenant_id:
            result = original(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        org = db.get(Organization, tenant_id)
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

        workspace_id, provider = _scope(db, tenant_id, kwargs)
        reservation = reserve_quota(
            db,
            org,
            "evidence_upload",
            workspace_id=workspace_id,
            metadata={"provider": provider, "surface": path},
        )
        reservation_id = reservation.id
        try:
            result = original(*args, **kwargs)
            result = await result if inspect.isawaitable(result) else result
            row = db.get(QuotaReservation, reservation_id)
            if isinstance(result, dict) and result.get("deduplicated"):
                if row is not None and row.state == "reserved":
                    release_reservation(db, row, reason="deduplicated_import")
            elif row is not None:
                commit_reservation(
                    db,
                    row,
                    event_type="evidence_upload",
                    metadata={"provider": provider, "surface": path},
                )
            db.commit()
            if isinstance(result, dict):
                return {**result, "commercial_metric": "evidence_upload", "shared_import_quota": True}
            return result
        except Exception:
            db.rollback()
            _release(db, reservation_id, "upload_failed")
            raise

    # FastAPI copies mounted routes and re-analyzes their endpoint signatures.
    # Resolve postponed annotations in the original endpoint's own globals now,
    # so ForwardRef names such as UploadFile and Session remain valid after the
    # commercial wrapper is moved through another router.
    metered.__signature__ = inspect.signature(original, eval_str=True)
    route.dependant.call = metered
    route.endpoint = metered
    route._agroai_commercial_metered = True


def install_commercial_upload_metering(routers: Iterable[Any]) -> None:
    for router in routers:
        for route in getattr(router, "routes", []):
            if not isinstance(route, APIRoute):
                continue
            if route.path not in _TARGET_PATHS or "POST" not in (route.methods or set()):
                continue
            _wrap_route(route)
