import time
from fastapi import APIRouter, HTTPException

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

@router.get("/blocks", response_model=list[DemoBlock])
def blocks():
    return list_demo_blocks()

@router.post("/recommendation", response_model=DemoRecommendationResponse)
async def recommendation(req: DemoRecommendationRequest):
    start = time.time()

    try:
        block = get_block(req.block_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown demo block")

    data_sources = []

    # Weather acquisition
    if req.mode == "synthetic":
        weather = synth_weather(block.lat, block.lon)
        data_sources.append("synthetic_weather")
    else:
        try:
            weather = await fetch_openweather(block.lat, block.lon)
            data_sources.append("openweather")
        except Exception as e:
            # Fail soft for demo reliability
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
        recommendation=engine_out["recommendation"],
        drivers=drivers,
        confidence=engine_out["confidence"],
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

