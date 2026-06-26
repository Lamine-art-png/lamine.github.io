# agroai_api/app/main.py

from __future__ import annotations

import datetime
import io
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

VERSION = "2.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle — starts scheduler after Alembic migrations."""

    # Start background scheduler if enabled (sync runs on schedule, NOT blocking startup)
    if settings.ENABLE_SCHEDULER and settings.WISECONN_API_KEY:
        from app.core.scheduler import start_scheduler

        start_scheduler()
        logger.info("Scheduler started — first sync will run on next interval")
    else:
        logger.info("Background scheduler disabled (ENABLE_SCHEDULER=%s, API key set=%s)",
                    settings.ENABLE_SCHEDULER, bool(settings.WISECONN_API_KEY))

    yield  # App is running

    # Shutdown
    if settings.ENABLE_SCHEDULER:
        from app.core.scheduler import stop_scheduler

        stop_scheduler()


app = FastAPI(
    title="AGRO-AI API",
    version=VERSION,
    lifespan=lifespan,
)

# SaaS auth + billing routes
from app.api.v1.auth import router as auth_router  # noqa: E402
from app.api.v1.billing import router as billing_router  # noqa: E402

app.include_router(auth_router, prefix="/v1")
app.include_router(billing_router, prefix="/v1")

# SaaS workspace / tenant / entitlement routes
from app.api.v1.saas import router as saas_router  # noqa: E402
app.include_router(saas_router, prefix="/v1")

# Assurance Passport routes
from app.api.v1.assurance import router as assurance_router  # noqa: E402
app.include_router(assurance_router, prefix="/v1")


# WiseConn integration routes
from app.api.v1.wiseconn import router as wiseconn_router  # noqa: E402

app.include_router(wiseconn_router, prefix="/v1")

# Decisioning routes (water state + recommendations)
from app.api.v1.decisioning import router as decisioning_router  # noqa: E402

app.include_router(decisioning_router, prefix="/v1")

# Execution assurance routes (verification + outcome tracking)
from app.api.v1.execution_assurance import router as execution_router  # noqa: E402

app.include_router(execution_router, prefix="/v1")

# Forecast routes (VWC forecast, accuracy, optimization)
from app.api.v1.forecast import router as forecast_router  # noqa: E402

app.include_router(forecast_router, prefix="/v1")

from app.api.v1.intelligence import router as intelligence_router  # noqa: E402
app.include_router(intelligence_router, prefix="/v1")

from app.api.v1.workbench import router as workbench_router  # noqa: E402
app.include_router(workbench_router, prefix="/v1")

from app.api.v1.compliance import router as compliance_router  # noqa: E402
app.include_router(compliance_router, prefix="/v1")

from app.api.v1.controllers import router as controllers_router  # noqa: E402
app.include_router(controllers_router, prefix="/v1")

from app.api.v1.talgil import router as talgil_router  # noqa: E402
app.include_router(talgil_router, prefix="/v1")

from app.api.v1.ai import router as ai_router  # noqa: E402
app.include_router(ai_router, prefix="/v1")

from app.api.v1.agents import router as agents_router  # noqa: E402
app.include_router(agents_router, prefix="/v1")

from app.api.v1.platform_intelligence import router as platform_intelligence_router  # noqa: E402
app.include_router(platform_intelligence_router, prefix="/v1")

from app.api.v1.connectors import router as connectors_router  # noqa: E402
app.include_router(connectors_router, prefix="/v1")

from app.api.v1.connector_hub import router as connector_hub_router  # noqa: E402
app.include_router(connector_hub_router, prefix="/v1")


# Prometheus metrics endpoint
from app.core.metrics import metrics_endpoint  # noqa: E402

app.get("/metrics")(metrics_endpoint)


# Request metrics middleware
import time  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from app.core.metrics import api_requests, api_latency  # noqa: E402


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        endpoint = request.url.path
        method = request.method
        api_requests.labels(method=method, endpoint=endpoint, status=response.status_code).inc()
        api_latency.labels(method=method, endpoint=endpoint).observe(elapsed)
        return response


app.add_middleware(MetricsMiddleware)

# CORS: allow your production site + local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://agroai-pilot.com",
        "https://www.agroai-pilot.com",
        "https://app.agroai-pilot.com",
        "https://agroai-portal.pages.dev",
        "https://agroai-command-center-v2-preview.pages.dev",
        "https://app-v2.agroai-pilot.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://localhost:4174",
        "http://127.0.0.1:4174",
        "http://localhost:4180",
        "http://127.0.0.1:4180",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# -------------------------
# Health
# -------------------------
@app.get("/v1/health")
async def health() -> Dict[str, Any]:
    from app.core.scheduler import get_last_sync_result

    sync_status = get_last_sync_result()
    return {
        "status": "ok",
        "database": "ok",
        "version": VERSION,
        "scheduler_enabled": settings.ENABLE_SCHEDULER,
        "last_sync": sync_status,
    }


# -------------------------
# Existing evaluation recommendation route
# (Keeps your current behavior compatible)
# -------------------------
class EvaluationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float = Field(..., gt=0)


class EvaluationResponse(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float
    recommended_inches_per_week: float
    savings_pct: float


@app.post("/v1/evaluation/recommendation", response_model=EvaluationResponse)
@app.post("/v1/demo/recommendation", response_model=EvaluationResponse, include_in_schema=False)
async def evaluation_recommendation(payload: EvaluationRequest) -> EvaluationResponse:
    # Toy logic: ~25% water savings
    rec = round(payload.baseline_inches_per_week * 0.75, 2)
    savings_pct = round(
        (payload.baseline_inches_per_week - rec) / payload.baseline_inches_per_week * 100,
        1,
    )

    return EvaluationResponse(
        **payload.dict(),
        recommended_inches_per_week=rec,
        savings_pct=savings_pct,
    )
