"""Route-level commercial guards for premium artifact operations."""
from __future__ import annotations

import uuid
from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import Organization, User
from app.services.commercial_control import require_feature
from app.services.quota import commit_reservation, release_reservation, reserve_quota


REPORT_PDF_PATH = "/v1/intelligence/chat/report-pdf"
REPORT_EMAIL_PATH = "/v1/intelligence/chat/report-email"
ROUTER_REPORT_PATHS = {"/intelligence/chat/report-pdf", "/intelligence/chat/report-email"}


def enforce_report_commercial_boundary(
    request: Request,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Generator[None, None, None]:
    """Feature-gate and durably account direct report export routes."""
    path = request.url.path
    if path not in {REPORT_PDF_PATH, REPORT_EMAIL_PATH}:
        yield
        return

    org = db.query(Organization).filter(Organization.id == tenant_id).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    require_feature(db, org, "reports.pdf_export", recommended_plan="professional")
    if path == REPORT_EMAIL_PATH:
        require_feature(db, org, "reports.email_delivery", recommended_plan="professional")

    request_id = request.headers.get("Idempotency-Key") or str(uuid.uuid4())
    reservation = reserve_quota(
        db,
        org,
        "report_export",
        user_id=user.id,
        request_id=request_id,
        metadata={"route": path, "delivery": "email" if path == REPORT_EMAIL_PATH else "download"},
    )
    try:
        yield
    except Exception:
        release_reservation(db, reservation, reason="report_route_failed")
        db.commit()
        raise
    else:
        commit_reservation(
            db,
            reservation,
            event_type="report_export",
            metadata={"route": path, "delivery": "email" if path == REPORT_EMAIL_PATH else "download"},
        )
        db.commit()


def install_report_commercial_guards() -> None:
    """Attach the guard to exact report routes before FastAPI includes the router."""
    from app.api.v1.chat_artifacts import router as chat_artifacts_router

    for route in chat_artifacts_router.routes:
        if getattr(route, "path", None) not in ROUTER_REPORT_PATHS:
            continue
        already_installed = any(
            getattr(getattr(dependency, "dependency", None), "__name__", "")
            == enforce_report_commercial_boundary.__name__
            for dependency in getattr(route, "dependencies", [])
        )
        if not already_installed:
            route.dependencies.append(Depends(enforce_report_commercial_boundary))
