from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import connector_unified_v3 as unified_v3
from app.services import provider_sync_jobs
from app.services.ag_provider_sync_jobs import AG_SYNC_PROVIDERS, queue_ag_provider_sync

provider_sync_jobs.SUPPORTED_PROVIDERS.update(AG_SYNC_PROVIDERS)
unified_v3.queue_provider_sync = queue_ag_provider_sync

router = APIRouter()
router.include_router(unified_v3.router)
