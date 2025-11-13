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
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request logging / request ID middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Attach a request ID and basic timing to each request."""
    request_id = str(uuid.uuid4())
    start_time = time.time()

    # store on request and in our logging context
    request.state.request_id = request_id
    set_request_id(request_id)

    response: Response = await call_next(request)

    process_time_ms = (time.time() - start_time) * 1000.0
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-ms"] = f"{process_time_ms:.2f}"

    logger.info(
        "request",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "process_time_ms": process_time_ms,
            "request_id": request_id,
        },
    )

    return response


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": "internal_error"},
    )


# ---------------------------------------------------------------------------
# Mount v1 API router
# ---------------------------------------------------------------------------
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


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


# ---------------------------------------------------------------------------
# Demo recommendation endpoint (/v1/demo/recommendation)
# ---------------------------------------------------------------------------
class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


@app.post("/v1/demo/recommendation")
async def demo_recommendation(payload: DemoRecommendationRequest):
    """
    Demo endpoint for OEMs / pilots.

    Takes a simple field payload and returns a mocked irrigation
    recommendation + water-savings estimate.
    """
    # Pick a mid-range savings between 20–35%
    target_savings = 0.275  # 27.5%

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

