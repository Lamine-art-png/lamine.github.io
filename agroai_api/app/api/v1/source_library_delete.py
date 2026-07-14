from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.services.source_deletion import delete_source_reference


router = APIRouter(tags=["source-library"])


@router.delete("/source-library/{source_ref}")
def delete_source_library_item(
    source_ref: str,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return delete_source_reference(db, auth=auth, source_ref=source_ref)
