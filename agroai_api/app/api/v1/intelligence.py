"""AGRO-AI Intelligence Engine v1 routes."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.intelligence_engine import (
    CanonicalFieldContext,
    ContextNormalizationResult,
    DataQualityResult,
    IntelligenceEngineV1,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services.live_field_context import (
    LiveContextAssemblerError,
    LiveContextNotFoundError,
    LiveFieldContextAssembler,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])
engine = IntelligenceEngineV1()
live_assembler = LiveFieldContextAssembler()


class LiveRecommendationRequest(BaseModel):
    source: str
    entity_id: str
    crop_type: str | None = None
    soil_type: str | None = None
    irrigation_method: str | None = None
    area: float | None = None
    location: Dict[str, Any] | None = None
    weather_context: Dict[str, Any] | None = None
    field_observations: list[str] | None = None
    language: str = "en"
    user_role: str | None = None
    units: str | None = None
    time_horizon: str = "today"


@router.post("/field-context/normalize", response_model=ContextNormalizationResult)
async def normalize_field_context(payload: Dict[str, Any]) -> ContextNormalizationResult:
    return engine.normalize_field_context(payload)


@router.post("/data-quality", response_model=DataQualityResult)
async def evaluate_data_quality(payload: CanonicalFieldContext) -> DataQualityResult:
    return engine.evaluate_data_quality(payload)


@router.post("/recommend", response_model=RecommendationResponse)
async def recommend(payload: Dict[str, Any]) -> RecommendationResponse:
    normalized = engine.normalize_field_context(payload.get("field_context") or {})
    request = RecommendationRequest(
        field_context=normalized.normalized_context,
        language=payload.get("language", "en"),
        user_role=payload.get("user_role"),
        units=payload.get("units"),
        time_horizon=payload.get("time_horizon", "today"),
    )
    response = engine.recommend(request)
    return response


def _merge_overrides(base_context: Dict[str, Any], payload: LiveRecommendationRequest) -> tuple[Dict[str, Any], list[str]]:
    overrides: list[str] = []
    merged = dict(base_context)
    for field_name in ("crop_type", "soil_type", "irrigation_method", "area", "location", "weather_context", "field_observations"):
        value = getattr(payload, field_name)
        if value is not None:
            merged[field_name] = value
            overrides.append(field_name)
    return merged, overrides


async def _recommend_live(source: str, entity_id: str, payload: LiveRecommendationRequest) -> RecommendationResponse:
    try:
        assembled = await live_assembler.assemble(source, entity_id)
    except LiveContextNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LiveContextAssemblerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    context_payload, manual_overrides = _merge_overrides(
        assembled["context"].model_dump(mode="python"),
        payload,
    )
    normalized = engine.normalize_field_context(context_payload)
    request = RecommendationRequest(
        field_context=normalized.normalized_context,
        language=payload.language,
        user_role=payload.user_role,
        units=payload.units,
        time_horizon=payload.time_horizon,
    )
    response = engine.recommend(request)
    response.source_trace = {
        "source": normalized.normalized_context.source,
        "source_entity_id": normalized.normalized_context.source_entity_id,
        "context_origin": "mixed" if manual_overrides else assembled.get("context_origin", "live"),
        "inputs_used": normalized.normalized_context.confidence_inputs,
        "live_inputs_used": assembled.get("live_inputs_used", []),
        "manual_overrides_used": manual_overrides,
        "missing_inputs": response.missing_data,
        "telemetry_used": bool(assembled.get("live_inputs_used")),
        "controller_provider": normalized.normalized_context.controller_context.provider,
        "confidence_basis": response.confidence_label,
        "warnings": assembled.get("warnings", []),
    }
    return response


@router.get("/live-context/wiseconn/{zone_id}", response_model=ContextNormalizationResult)
async def live_context_wiseconn(zone_id: str) -> ContextNormalizationResult:
    try:
        assembled = await live_assembler.assemble_wiseconn_zone(zone_id)
    except LiveContextNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LiveContextAssemblerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    normalized = engine.normalize_field_context(assembled["context"].model_dump(mode="python"))
    normalized.warnings.extend(assembled.get("warnings", []))
    return normalized


@router.get("/live-context/talgil/{target_id}", response_model=ContextNormalizationResult)
async def live_context_talgil(target_id: str) -> ContextNormalizationResult:
    try:
        assembled = await live_assembler.assemble_talgil_target(target_id)
    except LiveContextNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LiveContextAssemblerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    normalized = engine.normalize_field_context(assembled["context"].model_dump(mode="python"))
    normalized.warnings.extend(assembled.get("warnings", []))
    return normalized


@router.post("/recommend/live", response_model=RecommendationResponse)
async def recommend_live(payload: LiveRecommendationRequest) -> RecommendationResponse:
    return await _recommend_live(payload.source, payload.entity_id, payload)


@router.post("/recommend/live/wiseconn/{zone_id}", response_model=RecommendationResponse)
async def recommend_live_wiseconn(zone_id: str, payload: LiveRecommendationRequest) -> RecommendationResponse:
    return await _recommend_live("wiseconn", zone_id, payload)


@router.post("/recommend/live/talgil/{target_id}", response_model=RecommendationResponse)
async def recommend_live_talgil(target_id: str, payload: LiveRecommendationRequest) -> RecommendationResponse:
    return await _recommend_live("talgil", target_id, payload)


@router.get("/schema")
async def schema() -> Dict[str, Any]:
    return {
        "field_context_schema": CanonicalFieldContext.model_json_schema(),
        "recommendation_request_schema": RecommendationRequest.model_json_schema(),
        "recommendation_response_schema": RecommendationResponse.model_json_schema(),
        "data_quality_schema": DataQualityResult.model_json_schema(),
        "supported_languages": ["en", "fr", "es", "pt", "ar"],
        "notes": "Translations currently fall back to English unless translation provider is configured.",
    }
