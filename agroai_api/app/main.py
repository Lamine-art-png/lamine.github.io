import uuid
import time
from contextlib import asynccontextmanager
from pathlib import Path
import csv
from typing import List

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import setup_logging, set_request_id
from app.core import metrics
from app.db.base import init_db
from app.api.v1 import api_router


logger = setup_logging()


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AGRO-AI API")
    init_db()
    logger.info("Database initialized")
    try:
        yield
    finally:
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
# Demo recommendation endpoint
# ---------------------------------------------------------------------------

DATA_CSV = Path(__file__).resolve().parent.parent / "data" / "demo_blocks.csv"


class DemoRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


class DemoBlockResponse(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float
    recommended_inches_per_week: float
    water_savings_percent: float
    notes: str


class DemoResponse(BaseModel):
    status: str
    blocks: List[DemoBlockResponse]


def _block_from_row(row: dict) -> DemoBlockResponse:
    baseline = float(row["baseline_inches_per_week"])
    agroai = float(row["agroai_inches_per_week"])
    savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

    return DemoBlockResponse(
        field_id=row["field_id"],
        crop=row["crop"],
        acres=float(row["acres"]),
        location=row.get("location", ""),
        baseline_inches_per_week=baseline,
        recommended_inches_per_week=agroai,
        water_savings_percent=savings_pct,
        notes="Demo CSV block for AGRO-AI pilot.",
    )


@app.post("/v1/demo/recommendation", response_model=DemoResponse)
async def demo_recommendation(payload: DemoRequest) -> DemoResponse:
    """
    Demo-only irrigation recommendation endpoint.

    Behaviour:
    - If `data/demo_blocks.csv` exists and has a row with this `field_id`,
      we use the baseline + AGRO-AI inches from that row.
    - Otherwise we synthesize a demo result from the payload and assume 30% savings.
    """

    blocks: List[DemoBlockResponse] = []

    # Try to load from CSV
    if DATA_CSV.exists():
        with DATA_CSV.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("field_id") == payload.field_id:
                    blocks.append(_block_from_row(row))

    # Fallback: synthesize from payload (30% savings)
    if not blocks:
        baseline = payload.baseline_inches_per_week
        agroai = round(baseline * 0.7, 2)
        savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

        blocks.append(
            DemoBlockResponse(
                field_id=payload.field_id,
                crop=payload.crop,
                acres=payload.acres,
                location=payload.location,
                baseline_inches_per_week=baseline,
                recommended_inches_per_week=agroai,
                water_savings_percent=savings_pct,
                notes="Synthetic demo block (no CSV row found).",
            )
        )

    return DemoResponse(status="ok", blocks=blocks)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

# Safely read BACKEND_CORS_ORIGINS; default to "*"
allow_origins = getattr(settings, "BACKEND_CORS_ORIGINS", ["*"])

# If env gives us a comma-separated string, normalize to list
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


# ---------------------------------------------------------------------------
# Request ID + metrics middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def add_request_id_and_timing(request: Request, call_next):
    request_id = str(uuid.uuid4())
    set_request_id(request_id)
    start = time.monotonic()

    try:
        response: Response = await call_next(request)
    except Exception:
        logger.exception("Request failed")
        raise
    finally:
        duration_ms = (time.monotonic() - start) * 1000.0
        status_code = getattr(response, "status_code", "error")

        logger.info(
            "request",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": status_code,
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
            },
        )

        # Don't let metrics errors break requests
        try:
            metrics.REQUEST_LATENCY.observe(duration_ms / 1000.0)
            metrics.REQUEST_COUNT.labels(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
            ).inc()
        except Exception:
            logger.debug("Metrics update failed", exc_info=True)

    return response


# ---------------------------------------------------------------------------
# Routers & root
# ---------------------------------------------------------------------------

# All existing versioned endpoints (/v1/health, /v1/...) live here
app.include_router(api_router, prefix="/v1")


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse(
        {
            "status": "ok",
            "message": "AGRO-AI irrigation intelligence API",
            "version": settings.VERSION,
        }
    )

