from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.cloudflare_queue import _require_queue_token
from app.db.base import get_db
from app.services.runtime_diagnostics import connector_runtime_diagnostics


router = APIRouter(tags=["internal-runtime-diagnostics"])


@router.get("/internal/operations/diagnostics", dependencies=[Depends(_require_queue_token)])
def operations_diagnostics(db: Session = Depends(get_db)) -> dict:
    try:
        return connector_runtime_diagnostics(db)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "runtime_diagnostics_unavailable", "reason": exc.__class__.__name__},
        ) from exc
