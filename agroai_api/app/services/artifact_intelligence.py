from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OPENAI_BASE = "https://api.openai.com/v1"

_ARTIFACT_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "audience": {"type": "string"},
        "objective": {"type": "string"},
        "executive_summary": {"type": "string"},
        "design_direction": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "layout": {
                        "type": "string",
                        "enum": ["title", "thesis", "two_column", "metrics", "evidence", "actions", "timeline", "closing"],
                    },
                    "eyebrow": {"type": "string"},
                    "title": {"type": "string"},
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "value": {"type": "string"},
                                "label": {"type": "string"},
                                "context": {"type": "string"},
                            },
                            "required": ["value", "label", "context"],
                        },
                    },
                    "left_title": {"type": "string"},
                    "left_points": {"type": "array", "items": {"type": "string"}},
                    "right_title": {"type": "string"},
                    "right_points": {"type": "array", "items": {"type": "string"}},
                    "callout": {"type": "string"},
                    "source_notes": {"type": "array", "items": {"type": "string"}},
                    "speaker_note": {"type": "string"},
                },
                "required": [
                    "layout", "eyebrow", "title", "headline", "body", "bullets", "metrics",
                    "left_title", "left_points", "right_title", "right_points", "callout",
                    "source_notes", "speaker_note",
                ],
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "heading": {"type": "string"},
                    "summary": {"type": "string"},
                    "paragraphs": {"type": "array", "items": {"type": "string"}},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "source_notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["heading", "summary", "paragraphs", "bullets", "source_notes"],
            },
        },
        "quality_checks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title", "subtitle", "audience", "objective", "executive_summary",
        "design_direction", "slides", "sections", "quality_checks",
    ],
}


def _quality_key() -> str:
    return str(
        os.getenv("AGROAI_ARTIFACT_API_KEY")
        or os.getenv("AGROAI_INTELLIGENCE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("AGROAI_REALTIME_API_KEY")
        or ""
    ).strip()


def _response_text(body: dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                chunks.append(part["text"].strip())
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _trim(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        return [_trim(item, limit) for item in value[:30]]
    if isinstance(value, dict):
        return {str(k)[:100]: _trim(v, limit) for k, v in list(value.items())[:80]}
    return value


def _fallback_plan(
    *,
    format_name: str,
    title: str,
    question: str,
    answer: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    paragraphs = [part.strip() for part in answer.split("\n") if part.strip()]
    if not paragraphs:
        paragraphs = [answer.strip() or "No grounded analysis was supplied."]
    source_notes = [
        str(item.get("filename") or item.get("name") or item.get("source_type") or "Workspace source")
        for item in evidence[:8]
    ]
    if format_name == "pptx":
        slides = [
            {
                "layout": "title",
                "eyebrow": "AGRO-AI ENTERPRISE INTELLIGENCE",
                "title": title,
                "headline": "",
                "body": question[:260],
                "bullets": [],
                "metrics": [],
                "left_title": "",
                "left_points": [],
                "right_title": "",
                "right_points": [],
                "callout": "",
                "source_notes": [],
                "speaker_note": "",
            },
            {
                "layout": "thesis",
                "eyebrow": "EXECUTIVE VIEW",
                "title": "What matters now",
                "headline": paragraphs[0][:220],
                "body": paragraphs[1][:480] if len(paragraphs) > 1 else "",
                "bullets": paragraphs[2:5],
                "metrics": [],
                "left_title": "",
                "left_points": [],
                "right_title": "",
                "right_points": [],
                "callout": "",
                "source_notes": source_notes[:3],
                "speaker_note": "",
            },
            {
                "layout": "evidence",
                "eyebrow": "EVIDENCE",
                "title": "What the workspace supports",
                "headline": "",
                "body": "",
                "bullets": paragraphs[1:5],
                "metrics": [],
                "left_title": "",
                "left_points": [],
                "right_title": "",
                "right_points": [],
                "callout": "",
                "source_notes": source_notes,
                "speaker_note": "",
            },
            {
                "layout": "actions",
                "eyebrow": "NEXT ACTIONS",
                "title": "Move the operation forward",
                "headline": "",
                "body": "",
                "bullets": paragraphs[-4:],
                "metrics": [],
                "left_title": "",
                "left_points": [],
                "right_title": "",
                "right_points": [],
                "callout": "",
                "source_notes": [],
                "speaker_note": "",
            },
            {
                "layout": "closing",
                "eyebrow": "AGRO-AI",
                "title": "From intelligence to execution",
                "headline": "Keep the evidence, decision, and next action in one operating system.",
                "body": "",
                "bullets": [],
                "metrics": [],
                "left_title": "",
                "left_points": [],
                "right_title": "",
                "right_points": [],
                "callout": "",
                "source_notes": [],
                "speaker_note": "",
            },
        ]
        sections: list[dict[str, Any]] = []
    else:
        slides = []
        sections = [
            {
                "heading": "Executive summary",
                "summary": paragraphs[0][:400],
                "paragraphs": paragraphs[:4],
                "bullets": [],
                "source_notes": source_notes[:4],
            },
            {
                "heading": "Operating analysis",
                "summary": paragraphs[1][:400] if len(paragraphs) > 1 else "",
                "paragraphs": paragraphs[1:7],
                "bullets": [],
                "source_notes": source_notes,
            },
            {
                "heading": "Recommended next actions",
                "summary": "",
                "paragraphs": [],
                "bullets": paragraphs[-5:],
                "source_notes": [],
            },
        ]
    return {
        "title": title,
        "subtitle": "AGRO-AI workspace intelligence",
        "audience": "Agricultural operations team",
        "objective": question[:400],
        "executive_summary": paragraphs[0][:700],
        "design_direction": "Premium, minimal, agriculture-first enterprise design.",
        "slides": slides,
        "sections": sections,
        "quality_checks": ["Grounded content only", "Readable density", "Clear next actions"],
        "model": None,
        "reasoning_effort": None,
        "fallback": True,
    }


def create_artifact_plan(
    *,
    format_name: str,
    title: str,
    question: str,
    answer: str,
    evidence: list[dict[str, Any]],
    analysis_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = _quality_key()
    if not key:
        return _fallback_plan(
            format_name=format_name,
            title=title,
            question=question,
            answer=answer,
            evidence=evidence,
        )

    model = str(os.getenv("AGROAI_ARTIFACT_MODEL") or "gpt-5.6-sol").strip()
    effort = str(os.getenv("AGROAI_ARTIFACT_REASONING_EFFORT") or "xhigh").strip().lower()
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        effort = "xhigh"

    instructions = """You are AGRO-AI's senior artifact strategist and information designer.

You do not merely format text. You first decide what the artifact must accomplish,
who it is for, what evidence supports it, what the narrative should be, and which
information belongs on each page or slide.

Quality rules:
- Think like a top-tier strategy consultant, enterprise product designer, and agricultural operations analyst.
- Use only the supplied grounded analysis and evidence context. Never invent customer facts, metrics, acreage, savings, telemetry, integrations, or outcomes.
- For PowerPoint: create a coherent 6-9 slide story when the material supports it. Every slide must have one job and one clear takeaway. Vary layouts deliberately. Keep slides concise; move nuance to speaker_note. Avoid walls of text and generic filler.
- A title is not a takeaway. Prefer specific, decision-oriented headlines.
- Metrics may appear only when the same value is explicitly supported in the supplied context.
- Evidence slides should distinguish observed facts, gaps, and implications.
- Action slides must be operational: owner/next step/verification when supported.
- For DOCX/PDF: create a polished executive document with an executive summary, evidence-backed analysis, clear sections, and practical next actions.
- Preserve uncertainty and missing evidence. Do not hide conflicts.
- Design direction is premium, minimal, agriculture-first enterprise software: restrained, clean, authoritative.
- Do an internal quality review before returning the final plan. Remove repetition, weak titles, redundant slides, and generic language.
Return only the strict JSON schema."""

    user_payload = {
        "format": format_name,
        "requested_title": title,
        "user_request": question,
        "grounded_answer": answer[:30000],
        "grounded_analysis_context": _trim(analysis_context or {}, 5000),
        "uploaded_evidence_metadata": _trim(evidence, 3000),
    }
    request = {
        "model": model,
        "store": False,
        "instructions": instructions,
        "input": [
            {
                "role": "user",
                "content": "Design the exact AGRO-AI artifact from this grounded context:\n"
                + json.dumps(user_payload, ensure_ascii=False, default=str),
            }
        ],
        "reasoning": {"effort": effort},
        "text": {
            "verbosity": "medium",
            "format": {
                "type": "json_schema",
                "name": "agroai_artifact_plan_v2",
                "strict": True,
                "schema": _ARTIFACT_PLAN_SCHEMA,
            },
        },
        "max_output_tokens": 12000,
    }

    try:
        with httpx.Client(timeout=95.0) as client:
            response = client.post(
                f"{_OPENAI_BASE}/responses",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=request,
            )
        if response.status_code >= 400:
            logger.warning("artifact_planner http_failed model=%s status=%s", model, response.status_code)
            return _fallback_plan(
                format_name=format_name,
                title=title,
                question=question,
                answer=answer,
                evidence=evidence,
            )
        body = response.json()
        raw = json.loads(_response_text(body))
        if not isinstance(raw, dict):
            raise ValueError("artifact plan was not an object")
        raw["model"] = model
        raw["reasoning_effort"] = effort
        raw["fallback"] = False
        if format_name == "pptx":
            slides = list(raw.get("slides") or [])[:10]
            if len(slides) < 4:
                raise ValueError("artifact plan did not contain enough slides")
            raw["slides"] = slides
            raw["sections"] = []
        else:
            sections = list(raw.get("sections") or [])[:10]
            if len(sections) < 2:
                raise ValueError("artifact plan did not contain enough sections")
            raw["sections"] = sections
            raw["slides"] = []
        return raw
    except Exception as exc:
        logger.warning("artifact_planner failed model=%s error=%s", model, exc.__class__.__name__)
        return _fallback_plan(
            format_name=format_name,
            title=title,
            question=question,
            answer=answer,
            evidence=evidence,
        )
