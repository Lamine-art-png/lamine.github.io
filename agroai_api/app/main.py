import uuid
import time
from contextlib import asynccontextmanager

from pydantic import BaseModel
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, set_request_id
from app.core import metrics
from app.db.base import init_db
from app.api.v1 import api_router

logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
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

class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


class DemoRecommendationResponse(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float
    recommended_inches_per_week: float
    expected_water_savings_percent: float
    notes: str


@app.post("/v1/demo/recommendation", response_model=DemoRecommendationResponse)
def demo_recommendation(payload: DemoRecommendationRequest) -> DemoRecommendationResponse:
    # Simple demo logic: constant 27.5% savings
    savings_fraction = 0.275

    recommended = payload.baseline_inches_per_week * (1 - savings_fraction)

    return DemoRecommendationResponse(
        field_id=payload.field_id,
        crop=payload.crop,
        acres=payload.acres,
        location=payload.location,
        baseline_inches_per_week=payload.baseline_inches_per_week,
        recommended_inches_per_week=round(recommended, 2),
        expected_water_savings_percent=round(savings_fraction * 100, 1),
        notes="Demo-only recommendation for AGRO-AI OEM integration.",
    )

# CORS
# Safely read BACKEND_CORS_ORIGINS if it exists, otherwise default to "*"
allow_origins = getattr(settings, "BACKEND_CORS_ORIGINS", ["*"])

# If it comes from env as a comma-separated string, normalize to list
if isinstance(allow_origins, str):
    allow_origins = [o.strip() for o in allow_origins.split(",") if o.strip()]

if not allow_origins:
    allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_request_id_and_timing(request: Request, call_next):
    request_id = str(uuid.uuid4())
    set_request_id(request_id)
    start = time.monotonic()

    try:
        response: Response = await call_next(request)
    except Exception as exc:
        logger.error("Request failed", exc_info=True)
        raise exc
    finally:
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "request",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": getattr(response, "status_code", None),
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
            },
        )

    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": "internal_error"},
    )


# --------------------------------------------------------------------
# Mount v1 API (health + demo)
# --------------------------------------------------------------------
app.include_router(api_router, prefix="/v1")


@app.get("/metrics")
def get_metrics():
    if not settings.ENABLE_METRICS:
        return Response(status_code=404)
    return metrics.metrics_endpoint()


@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/v1/health",
    }

