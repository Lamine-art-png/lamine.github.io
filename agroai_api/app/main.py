kfrom pathlib import Path
import csv
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel


# --- FastAPI app -------------------------------------------------------------

app = FastAPI(
    title="AGRO-AI Irrigation Intelligence API",
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

DATA_CSV = Path(__file__).resolve().parent.parent / "data" / "demo_blocks.csv"


# --- Models ------------------------------------------------------------------

class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


class DemoBlock(BaseModel):
    field_id: str
    crop: str
    acres: float
    baseline_inches_per_week: float
    agroai_inches_per_week: float
    water_savings_percent: float


class DemoResponse(BaseModel):
    status: str
    blocks: List[DemoBlock]


# --- Endpoints ---------------------------------------------------------------

@app.get("/v1/health")
def health():
    return {
        "status": "ok",
        "database": "ok",
        "version": "1.1.0",
    }


@app.post("/v1/demo/recommendation", response_model=DemoResponse)
def demo_recommendation(payload: DemoRecommendationRequest) -> DemoResponse:
    """
    Tiny demo endpoint:
    - optional: looks up the field in demo_blocks.csv
    - otherwise: pretends 30% water savings on the payload baseline
    """
    blocks: List[DemoBlock] = []

    # 1) If we have a CSV, try to use it
    if DATA_CSV.exists():
        with DATA_CSV.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("field_id") != payload.field_id:
                    continue

                baseline = float(row["baseline_inches_per_week"])
                agroai = float(row.get("agroai_inches_per_week") or baseline * 0.7)
                savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

                blocks.append(
                    DemoBlock(
                        field_id=row["field_id"],
                        crop=row["crop"],
                        acres=float(row["acres"]),
                        baseline_inches_per_week=baseline,
                        agroai_inches_per_week=agroai,
                        water_savings_percent=savings_pct,
                    )
                )

    # 2) Fallback: synthesize from payload
    if not blocks:
        baseline = payload.baseline_inches_per_week
        agroai = round(baseline * 0.7, 2)  # pretend 30% savings
        savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

        blocks.append(
            DemoBlock(
                field_id=payload.field_id,
                crop=payload.crop,
                acres=payload.acres,
                baseline_inches_per_week=baseline,
                agroai_inches_per_week=agroai,
                water_savings_percent=savings_pct,
            )
        )

    return DemoResponse(status="ok", blocks=blocks)

