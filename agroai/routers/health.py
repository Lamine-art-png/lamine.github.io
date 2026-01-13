import os
from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter()

@router.get("/v1/health")
def health():
    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "build": os.getenv("GIT_SHA", os.getenv("RENDER_GIT_COMMIT", "dev")),
    }
