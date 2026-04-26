"""AGRO-AI Intelligence Engine v1 routes."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app.services.intelligence_engine import (
    CanonicalFieldContext,
    DataQualityResult,
    IntelligenceEngineV1,
    RecommendationRequest,
    RecommendationResponse,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])
engine = IntelligenceEngineV1()


@router.post("/field-context/normalize", response_model=CanonicalFieldContext)
async def normalize_field_context(payload: Dict[str, Any]) -> CanonicalFieldContext:
    return engine.normalize_field_context(payload)


@router.post("/data-quality", response_model=DataQualityResult)
async def evaluate_data_quality(payload: CanonicalFieldContext) -> DataQualityResult:
    return engine.evaluate_data_quality(payload)


@router.post("/recommend", response_model=RecommendationResponse)
async def recommend(payload: RecommendationRequest) -> RecommendationResponse:
    return engine.recommend(payload)


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
