import uuid
import time
from contextlib import asynccontextmanager
from pathlib import Path
import csv
from typing import List

from pydantic import BaseModel
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.base import init_db
from app.api.v1 import api_router

# ------------------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------------------

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

# Mount existing v1 API router (health, recommendations, etc.)
app.include_router(api_router, prefix="/v1")


# ------------------------------------------------------------------------------
# Demo recommendation endpoint
# ------------------------------------------------------------------------------

DATA_CSV = Path(__file__).resolve().parent.parent / "data" / "demo_blocks.csv"


class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


class DemoRecommendationBlock(BaseModel):
    field_id: str
    crop: str
    acres: float
    baseline_inches_per_week: float
    agroai_inches_per_week: float
    water_savings_percent: float


class DemoRecommendationResponse(BaseModel):
    status: str
    blocks: List[DemoRecommendationBlock]


@app.post("/v1/demo/recommendation", response_model=DemoRecommendationResponse)
async def demo_recommendation(
    payload: DemoRecommendationRequest,
) -> DemoRecommendationResponse:
    rows: list[DemoRecommendationBlock] = []

    # Try to use demo_blocks.csv if it exists
    if DATA_CSV.exists():
        with DATA_CSV.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["field_id"] != payload.field_id:
                    continue

                baseline = float(row["baseline_inches_per_week"])
                agroai = float(row["agroai_inches_per_week"])
                savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

                rows.append(
                    DemoRecommendationBlock(
                        field_id=row["field_id"],
                        crop=row["crop"],
                        acres=float(row["acres"]),
                        baseline_inches_per_week=baseline,
                        agroai_inches_per_week=agroai,
                        water_savings_percent=savings_pct,
                    )
                )

    # Fallback: synthesize a demo block from the payload (30% savings)
    if not rows:
        baseline = payload.baseline_inches_per_week
        agroai = round(baseline * 0.7, 2)
        savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

        rows.append(
            DemoRecommendationBlock(
                field_id=payload.field_id,
                crop=payload.crop,
                acres=payload.acres,
                baseline_inches_per_week=baseline,
                agroai_inches_per_week=agroai,
                water_savings_percent=savings_pct,
            )
        )

    return DemoRecommendationResponse(status="ok", blocks=rows)


# ------------------------------------------------------------------------------
# CORS + simple request logging middleware
# ------------------------------------------------------------------------------

allow_origins = getattr(settings, "BACKEND_CORS_ORIGINS", ["*"])
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
async def add_request_logging(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start = time.monotonic()

    try:
        response: Response = await call_next(request)
    finally:
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "request",
            extra={
                "path": str(request.url.path),
                "method": request.method,
                "status_code": getattr(response, "status_code", None),
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
            },
        )

    return response

