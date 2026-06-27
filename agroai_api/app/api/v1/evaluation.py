from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["evaluation"])
legacy_router = APIRouter(include_in_schema=False)


class EvaluationRunRequest(BaseModel):
    block_ids: list[str] = Field(default_factory=list)


def _payload(block_ids: list[str] | None = None) -> dict[str, Any]:
    ids = block_ids or ["evaluation-block-1"]
    return {
        "status": "ok",
        "mode": "evaluation",
        "recommendation": {
            "action": "Review imported field evidence before operational use",
            "confidence": "low",
            "reason": "Evaluation logic needs live or uploaded field evidence before issuing operational instructions.",
        },
        "prescriptions": [
            {
                "block_id": block_id,
                "action": "Collect recent irrigation, ET/weather, and field evidence",
                "reason": "evaluation logic is available, but live customer evidence is required for a production-grade recommendation.",
            }
            for block_id in ids
        ],
        "report_endpoint": "/v1/evaluation/report",
        "next_actions": [
            "Upload controller or field evidence.",
            "Connect provider credentials for live sync.",
            "Generate an evaluation report after evidence is available.",
        ],
    }


@router.get("/evaluation/sample-report", response_class=HTMLResponse)
async def sample_report() -> str:
    return """
    <html><body>
      <h1>AGRO-AI Sample Report</h1>
      <p>This report supports evaluation workflows for irrigation evidence, readiness, and field intelligence.</p>
    </body></html>
    """


@legacy_router.get("/demo/sample-report", response_class=HTMLResponse)
async def legacy_sample_report() -> str:
    return await sample_report()


@router.get("/v1/evaluation/blocks")
async def evaluation_blocks() -> dict[str, Any]:
    return {"status": "ok", "blocks": [{"id": "evaluation-block-1", "name": "Evaluation Block", "source": "evaluation"}]}


@router.post("/v1/evaluation/recommendation")
async def evaluation_recommendation(payload: EvaluationRunRequest | None = None) -> dict[str, Any]:
    return _payload(payload.block_ids if payload else None)


@router.post("/v1/evaluation/run")
async def evaluation_run(payload: EvaluationRunRequest) -> dict[str, Any]:
    return _payload(payload.block_ids)


@router.get("/v1/evaluation/report")
async def evaluation_report() -> dict[str, Any]:
    return {"status": "ok", "report": "AGRO-AI evaluation report", "source": "evaluation"}


@legacy_router.post("/v1/demo/recommendation")
async def legacy_recommendation(payload: EvaluationRunRequest | None = None) -> dict[str, Any]:
    return await evaluation_recommendation(payload)


@legacy_router.get("/v1/demo/blocks")
async def legacy_blocks() -> dict[str, Any]:
    return await evaluation_blocks()


@legacy_router.post("/v1/demo/run")
async def legacy_run(payload: EvaluationRunRequest) -> dict[str, Any]:
    return await evaluation_run(payload)


@legacy_router.get("/v1/demo/report")
async def legacy_report() -> dict[str, Any]:
    return await evaluation_report()
