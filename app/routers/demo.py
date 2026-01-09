import time
import uuid
import os
import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.schemas.demo import (
    DemoBlock,
    DemoRecommendationRequest,
    DemoRecommendationResponse,
)
from app.services.demo_blocks import list_demo_blocks, get_block
from app.services.weather_provider import (
    fetch_openweather,
    synth_weather,
    extract_drivers,
)
from app.services.recommendation_engine import generate_recommendation

router = APIRouter()

# In-memory store (OK for demo; not reliable across multiple ECS tasks/replicas)
RUNS: Dict[str, Dict[str, Any]] = {}


def _now_utc_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class DemoRunRequest(BaseModel):
    """
    Runs recommendations for multiple blocks in one request and returns:
    - a prescriptions payload (JSON)
    - a report_url (PDF)
    """
    block_ids: List[str] = Field(..., min_length=1)
    mode: str = "synthetic"  # use synthetic for reliability during live demos
    assumptions: Dict[str, Any] = Field(default_factory=dict)


@router.get("/blocks", response_model=List[DemoBlock])
def blocks():
    return list_demo_blocks()


@router.post("/recommendation", response_model=DemoRecommendationResponse)
async def recommendation(req: DemoRecommendationRequest):
    start = time.time()

    try:
        block = get_block(req.block_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown demo block")

    data_sources: List[str] = []

    # Weather acquisition
    if req.mode == "synthetic":
        weather = synth_weather(block.lat, block.lon)
        data_sources.append("synthetic_weather")
    else:
        try:
            weather = await fetch_openweather(block.lat, block.lon)
            data_sources.append("openweather")
        except Exception:
            # Fail-soft for demo reliability
            weather = synth_weather(block.lat, block.lon)
            data_sources.append("openweather_failed_fallback_synthetic")

    drivers = extract_drivers(weather)

    engine_out = generate_recommendation(
        block=block,
        assumptions=req.assumptions,
        drivers=drivers,
        mode=req.mode,
    )

    latency_ms = int((time.time() - start) * 1000)

    # Keep your existing response shape
    response = DemoRecommendationResponse(
        block={
            "id": block.id,
            "label": block.label,
            "lat": block.lat,
            "lon": block.lon,
            "crop": block.crop,
            "acres": block.acres,
            "region": block.region,
        },
        recommendation=engine_out.get("recommendation"),
        drivers=drivers,
        confidence=engine_out.get("confidence"),
        notes=engine_out.get("notes", []),
        soil_balance=engine_out.get("soil_balance"),
        api_debug={
            "latency_ms": latency_ms,
            "data_sources": data_sources,
            "model_version": "demo-engine-0.2",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )

    return response


@router.post("/run")
async def run_demo(req: DemoRunRequest = Body(...)):
    """
    Multi-block demo run:
    POST /v1/demo/run  (because main.py mounts router with prefix="/v1/demo")
    """
    run_id = str(uuid.uuid4())
    started_at = _now_utc_iso()

    prescriptions: List[Dict[str, Any]] = []

    for block_id in req.block_ids:
        try:
            block = get_block(block_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown demo block: {block_id}")

        data_sources: List[str] = []

        if req.mode == "synthetic":
            weather = synth_weather(block.lat, block.lon)
            data_sources.append("synthetic_weather")
        else:
            try:
                weather = await fetch_openweather(block.lat, block.lon)
                data_sources.append("openweather")
            except Exception:
                weather = synth_weather(block.lat, block.lon)
                data_sources.append("openweather_failed_fallback_synthetic")

        drivers = extract_drivers(weather)

        engine_out = generate_recommendation(
            block=block,
            assumptions=req.assumptions,
            drivers=drivers,
            mode=req.mode,
        )

        prescriptions.append(
            {
                "block": {
                    "id": block.id,
                    "label": block.label,
                    "lat": block.lat,
                    "lon": block.lon,
                    "crop": block.crop,
                    "acres": block.acres,
                    "region": block.region,
                },
                "recommendation": engine_out.get("recommendation"),
                "confidence": engine_out.get("confidence"),
                "drivers": drivers,
                "notes": engine_out.get("notes", []),
                "soil_balance": engine_out.get("soil_balance"),
                "data_sources": data_sources,
            }
        )

    RUNS[run_id] = {
        "run_id": run_id,
        "started_at": started_at,
        "mode": req.mode,
        "assumptions": req.assumptions,
        "prescriptions": prescriptions,
    }

    return {
        "run_id": run_id,
        "started_at": started_at,
        "mode": req.mode,
        "prescriptions": prescriptions,
        # full path is helpful in demos
        "report_url": f"/v1/demo/report/{run_id}.pdf",
    }


@router.get("/report/{run_id}.pdf")
def demo_report_pdf(run_id: str):
    """
    PDF summary for the last /run request.
    GET /v1/demo/report/{run_id}.pdf
    """
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="run_id not found")

    # Requires: reportlab in requirements.txt
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    os.makedirs("/tmp/agroai-demo", exist_ok=True)
    path = f"/tmp/agroai-demo/{run_id}.pdf"

    run = RUNS[run_id]
    presc = run["prescriptions"]

    c = canvas.Canvas(path, pagesize=letter)
    w, h = letter

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 50, "AGRO-AI — Weekly Proof Report (DEMO)")

    c.setFont("Helvetica", 11)
    c.drawString(50, h - 80, f"Run ID: {run_id}")
    c.drawString(50, h - 100, f"Started: {run.get('started_at')}   Mode: {run.get('mode')}")

    y = h - 140
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Prescriptions Summary")
    y -= 22

    c.setFont("Helvetica", 10)
    for item in presc[:12]:
        label = item["block"].get("label") or item["block"]["id"]
        conf = item.get("confidence")
        conf_txt = f"{conf:.2f}" if isinstance(conf, (int, float)) else "n/a"
        c.drawString(60, y, f"- {label}: confidence {conf_txt} (decision-support)")
        y -= 14
        if y < 90:
            c.showPage()
            y = h - 60
            c.setFont("Helvetica", 10)

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, 55, "Demo report — not a compliance document. For illustration only.")
    c.save()

    return FileResponse(path, media_type="application/pdf", filename="agroai_demo_report.pdf")

