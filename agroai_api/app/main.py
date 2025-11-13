import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import setup_logging, set_request_id
from app.core import metrics
from app.db.base import init_db
from app.api.v1 import api_router

logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("Starting AGRO-AI API")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down AGRO-AI API")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request ID + basic metrics middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_request_id_and_metrics(request: Request, call_next):
    # Request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    set_request_id(request_id)
    request.state.request_id = request_id

    start_time = time.time()
    response: Response = await call_next(request)
    duration_ms = (time.time() - start_time) * 1000.0

    # response headers
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-ms"] = f"{duration_ms:.2f}"

    # prometheus-style metrics (if enabled)
    try:
        metrics.http_requests_total.labels(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        ).inc()
        metrics.http_request_duration_ms.observe(duration_ms)
    except Exception:
        # never break the request on metrics failure
        logger.exception("Failed to record metrics")

    return response


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": "internal_error"},
    )


# ---------------------------------------------------------------------------
# Mount v1 API router (existing endpoints, including /v1/health)
# ---------------------------------------------------------------------------
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# ---------------------------------------------------------------------------
# Demo recommendation endpoint (API-first OEM demo)
# ---------------------------------------------------------------------------
class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


@app.post(f"{settings.API_V1_PREFIX}/demo/recommendation", tags=["demo"])
async def demo_recommendation(payload: DemoRecommendationRequest):
    """
    Demo endpoint for OEMs / pilots.

    Takes a simple field payload and returns a mocked
    irrigation recommendation + savings estimate.
    """
    # Pick a mid-range savings between 20–35%
    target_savings = 0.275  # 27.5 %

    recommended_inches = payload.baseline_inches_per_week * (1 - target_savings)

    return {
        "field_id": payload.field_id,
        "crop": payload.crop,
        "acres": payload.acres,
        "location": payload.location,
        "baseline_inches_per_week": payload.baseline_inches_per_week,
        "recommended_inches_per_week": round(recommended_inches, 2),
        "expected_water_savings_percent": round(target_savings * 100, 1),
        "notes": "Demo-only recommendation for AGRO-AI OEM integration.",
    }


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------
@app.get("/metrics")
def get_metrics():
    if not getattr(settings, "ENABLE_METRICS", False):
        return Response(status_code=404)
    return metrics.metrics_endpoint()


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": f"{settings.API_V1_PREFIX}/health",
    }

