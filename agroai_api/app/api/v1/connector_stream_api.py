from __future__ import annotations

from fastapi import APIRouter

from app.services.object_storage import get_object_store
from app.services.task_outbox_service import drain_pending_outbox


# Compatibility module retained for imports used by the hardened streamed-upload
# route. Public upload handling lives only in connector_stream_secure.py; keeping
# a second /evidence/upload-stream route here made route order determine behavior.
router = APIRouter(tags=["connector-stream-internal"])


# Internal Queue callbacks are intentionally mounted on this otherwise route-free
# compatibility router so app.main can preserve its existing include boundary
# without re-registering the customer upload endpoint.
from app.api.v1.cloudflare_queue import router as cloudflare_queue_router  # noqa: E402

router.include_router(cloudflare_queue_router)


__all__ = ["router", "get_object_store", "drain_pending_outbox"]
