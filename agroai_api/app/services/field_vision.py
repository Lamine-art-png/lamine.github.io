"""Multimodal field-photo analysis for Field Intelligence.

Images are read only from the tenant-scoped durable object store. The provider
returns bounded, explicitly uncertain agronomic observations; it never executes
equipment commands or presents a visual hypothesis as a confirmed diagnosis.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings

DEFAULT_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct"
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class FieldVisionResult:
    provider: str
    status: str  # completed | skipped | unavailable | failed
    model: str | None = None
    latency_ms: int | None = None
    analysis: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    retryable: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and bool(self.analysis)


def _env(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def _internal_endpoint() -> str:
    api_url = str(getattr(settings, "API_URL", "") or "").strip().rstrip("/")
    return f"{api_url}/v1/internal/edge/field-vision" if api_url else ""


def _resolved_model() -> str:
    return _env("FIELD_VISION_MODEL") or DEFAULT_MODEL


def _resolved_endpoint(model: str) -> str:
    explicit = _env("FIELD_VISION_ENDPOINT")
    if explicit:
        return explicit
    if str(getattr(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "") or "").strip():
        return _internal_endpoint()
    transcription = str(getattr(settings, "FIELD_TRANSCRIPTION_ENDPOINT", "") or "").strip()
    parsed = urlparse(transcription)
    if parsed.scheme == "https" and (parsed.hostname or "").lower() == "api.cloudflare.com" and "/ai/run/" in parsed.path:
        prefix = transcription.split("/ai/run/", 1)[0]
        return f"{prefix}/ai/run/{model}"
    return ""


def _resolved_key() -> str:
    return (
        _env("FIELD_VISION_API_KEY")
        or str(getattr(settings, "FIELD_TRANSCRIPTION_API_KEY", "") or "").strip()
        or str(getattr(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "") or "").strip()
    )


def _endpoint_valid(endpoint: str, model: str) -> bool:
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    internal = urlparse(_internal_endpoint())
    if internal.netloc and parsed.netloc.lower() == internal.netloc.lower():
        return parsed.path.rstrip("/") == internal.path.rstrip("/") and model == DEFAULT_MODEL
    if (parsed.hostname or "").lower() != "api.cloudflare.com":
        return False
    path = parsed.path.rstrip("/")
    return path.startswith("/client/v4/accounts/") and path.endswith(f"/ai/run/{model}")


def _prompt(context: dict[str, Any]) -> str:
    field = str(context.get("field_name") or "unknown field")[:200]
    crop = str(context.get("crop") or "unknown crop")[:200]
    note = str(context.get("note_text") or "")[:1600]
    media_kind = str(context.get("media_kind") or "photo")[:80]
    target_language = str(context.get("language") or "en").strip()[:16] or "en"
    frame_time = context.get("frame_timestamp_seconds")
    frame_label = f"; frame_time_seconds={frame_time}" if frame_time is not None else ""
    return f"""
You are AGRO-AI Field Vision, an evidence-analysis system for agricultural operations.
Analyze this {media_kind} as one piece of evidence, using the operator note only as context.
Context: field={field}; crop={crop}; operator_note={note or "none"}{frame_label}.
Output language: {target_language}. Write every human-readable string value
(summary, labels, evidence, verification, observations, possible issues,
recommended follow-up, and uncertainties) in that language. Keep JSON keys and
the documented enum values exactly as written so the application contract stays stable.

Return JSON only with this exact shape:
{{
  "summary": "concise operational summary",
  "visible_facts": [{{"label": "visible fact", "evidence": "what in the image supports it", "confidence": 0.0}}],
  "hypotheses": [{{"label": "possible condition", "evidence": "visible pattern", "confidence": 0.0, "verification": "how to confirm"}}],
  "observations": ["backward-compatible concise visible observation"],
  "possible_issues": ["cautious issue category"],
  "crop_condition": "healthy|mostly_healthy|stressed|damaged|unknown",
  "coverage_assessment": "adequate|uneven|incomplete|not_visible|unknown",
  "equipment_condition": "normal|attention_needed|unsafe|not_visible|unknown",
  "severity": "info|low|medium|high|critical",
  "confidence": 0.0,
  "recommended_follow_up": "specific safe next inspection or verification step",
  "verification_required": true,
  "uncertainties": ["what cannot be established from this evidence"]
}}

Rules:
- Separate visible facts from hypotheses. Never present a hypothesis as a confirmed diagnosis.
- You may identify visible patterns consistent with crop stress, pest/disease symptoms, weed pressure,
  irrigation/application coverage, equipment problems, completion quality, or unsafe practice.
- Ordinary RGB imagery cannot measure pesticide concentration, residue, active ingredient, dosage,
  soil chemistry, internal plant chemistry, or exact moisture. State that these require records, sensors,
  calibrated equipment data, spectroscopy, or laboratory verification.
- Do not invent field identity, crop, chemical, measurement, treatment, or completion status.
- Do not recommend a pesticide/fertilizer product or dosage. Recommend verification and escalation.
- Confidence must reflect image quality, occlusion, distance, crop context, and ambiguity.
""".strip()


def _extract_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        if payload.get("success") is False:
            return ""
        for key in ("description", "response", "text", "output_text", "answer"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("result", "output", "data"):
            value = payload.get(key)
            text = _extract_text(value)
            if text:
                return text
    if isinstance(payload, list):
        for item in payload:
            text = _extract_text(item)
            if text:
                return text
    return ""


def _json_from_text(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {
        "summary": text[:1200] if text else "",
        "observations": [text[:1200]] if text else [],
        "possible_issue": "none",
        "severity": "info",
        "confidence": 0.25 if text else 0.0,
        "recommended_follow_up": "Review the original image and verify conditions in the field.",
        "uncertainties": ["The provider did not return structured visual output."],
    }


def _bounded_analysis(raw: dict[str, Any]) -> dict[str, Any]:
    severity = str(raw.get("severity") or "info").lower()
    if severity not in SEVERITY_ORDER:
        severity = "info"
    try:
        confidence = max(0.0, min(float(raw.get("confidence") or 0.0), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0

    def strings(value: Any, *, limit: int = 12) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip()[:500] for item in value if str(item).strip()][:limit]

    def findings(value: Any, *, limit: int = 12, hypothesis: bool = False) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in value[:limit]:
            if isinstance(item, str):
                item = {"label": item}
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()[:300]
            if not label:
                continue
            try:
                item_confidence = max(0.0, min(float(item.get("confidence") or 0.0), 1.0))
            except (TypeError, ValueError):
                item_confidence = 0.0
            row: dict[str, Any] = {
                "label": label,
                "evidence": str(item.get("evidence") or "").strip()[:700],
                "confidence": item_confidence,
            }
            if hypothesis:
                row["verification"] = str(item.get("verification") or "").strip()[:700]
            rows.append(row)
        return rows

    allowed_condition = {"healthy", "mostly_healthy", "stressed", "damaged", "unknown"}
    allowed_coverage = {"adequate", "uneven", "incomplete", "not_visible", "unknown"}
    allowed_equipment = {"normal", "attention_needed", "unsafe", "not_visible", "unknown"}
    crop_condition = str(raw.get("crop_condition") or "unknown").lower()
    coverage = str(raw.get("coverage_assessment") or "unknown").lower()
    equipment = str(raw.get("equipment_condition") or "unknown").lower()
    possible_issues = strings(raw.get("possible_issues"))
    legacy_issue = str(raw.get("possible_issue") or "").strip()
    if legacy_issue and legacy_issue.lower() != "none" and legacy_issue not in possible_issues:
        possible_issues.append(legacy_issue[:500])

    return {
        "summary": str(raw.get("summary") or "").strip()[:1600],
        "visible_facts": findings(raw.get("visible_facts")),
        "hypotheses": findings(raw.get("hypotheses"), hypothesis=True),
        "observations": strings(raw.get("observations")),
        "possible_issues": possible_issues[:12],
        "crop_condition": crop_condition if crop_condition in allowed_condition else "unknown",
        "coverage_assessment": coverage if coverage in allowed_coverage else "unknown",
        "equipment_condition": equipment if equipment in allowed_equipment else "unknown",
        "severity": severity,
        "confidence": confidence,
        "recommended_follow_up": str(raw.get("recommended_follow_up") or "").strip()[:1600],
        "verification_required": bool(raw.get("verification_required", True)),
        "uncertainties": strings(raw.get("uncertainties")),
    }


def _analyze_one(image: bytes, content_type: str | None, context: dict[str, Any]) -> FieldVisionResult:
    model = _resolved_model()
    endpoint = _resolved_endpoint(model)
    key = _resolved_key()
    if not endpoint or not key:
        return FieldVisionResult(provider="cloudflare_workers_ai", status="unavailable", model=model, error="vision_provider_not_configured")
    if not _endpoint_valid(endpoint, model):
        return FieldVisionResult(provider="cloudflare_workers_ai", status="failed", model=model, error="vision_endpoint_rejected")
    if not image or len(image) > MAX_IMAGE_BYTES:
        return FieldVisionResult(provider="cloudflare_workers_ai", status="failed", model=model, error="image_outside_provider_bound")

    started = time.monotonic()
    internal = endpoint.rstrip("/") == _internal_endpoint().rstrip("/")
    prompt = _prompt(context)
    body: dict[str, Any]
    if internal:
        body = {
            "model": model,
            "image": base64.b64encode(image).decode("ascii"),
            "content_type": content_type or "application/octet-stream",
            "prompt": prompt,
        }
    else:
        body = {"image": list(image), "prompt": prompt}

    try:
        timeout = max(5.0, float(_env("FIELD_VISION_TIMEOUT_SECONDS") or 60.0))
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return FieldVisionResult(
                provider="cloudflare_workers_ai",
                status="failed",
                model=model,
                latency_ms=latency,
                error=f"provider_http_{response.status_code}",
                retryable=response.status_code in RETRYABLE_HTTP,
            )
        payload = response.json()
        actual_model = str(payload.get("model") or model) if isinstance(payload, dict) else model
        text = _extract_text(payload)
        if not text:
            return FieldVisionResult(
                provider="cloudflare_workers_ai", status="failed", model=model,
                latency_ms=latency, error="provider_returned_empty_visual_analysis",
            )
        analysis = _bounded_analysis(_json_from_text(text))
        analysis["language"] = str(context.get("language") or "en").strip()[:16] or "en"
        return FieldVisionResult(
            provider="cloudflare_workers_ai", status="completed", model=actual_model,
            latency_ms=latency, analysis=analysis,
        )
    except Exception as exc:  # noqa: BLE001 - provider failures are surfaced, not hidden
        name = exc.__class__.__name__
        lower = name.lower()
        retryable = any(token in lower for token in ("timeout", "connect", "network", "pool", "protocol", "read"))
        return FieldVisionResult(
            provider="cloudflare_workers_ai", status="failed", model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=name, retryable=retryable,
        )


def analyze_field_images(images: list[tuple], context: dict[str, Any]) -> FieldVisionResult:
    if not images:
        return FieldVisionResult(provider="none", status="skipped", error="no_photo_assets")

    started = time.monotonic()
    completed: list[dict[str, Any]] = []
    failures: list[str] = []
    model: str | None = None
    provider = "cloudflare_workers_ai"
    for item in images[:MAX_IMAGES]:
        image, content_type = item[0], item[1]
        item_context = dict(context)
        if len(item) > 2 and isinstance(item[2], dict):
            item_context.update(item[2])
        result = _analyze_one(image, content_type, item_context)
        if result.succeeded and len(item) > 2 and isinstance(item[2], dict):
            result.analysis["media_context"] = dict(item[2])
        model = result.model or model
        provider = result.provider or provider
        if result.succeeded:
            completed.append(result.analysis)
        elif result.error:
            failures.append(result.error)

    latency = int((time.monotonic() - started) * 1000)
    if not completed:
        status = "unavailable" if failures and all(item == "vision_provider_not_configured" for item in failures) else "failed"
        return FieldVisionResult(
            provider=provider, status=status, model=model, latency_ms=latency,
            error=";".join(sorted(set(failures)))[:500] or "visual_analysis_failed",
            retryable=any("429" in item or "50" in item for item in failures),
        )

    observations: list[str] = []
    uncertainties: list[str] = []
    summaries: list[str] = []
    follow_ups: list[str] = []
    issues: list[str] = []
    severities: list[str] = []
    confidences: list[float] = []
    visible_facts: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    media_moments: list[dict[str, Any]] = []
    crop_conditions: list[str] = []
    coverage_assessments: list[str] = []
    equipment_conditions: list[str] = []
    for item in completed:
        summaries.extend([item.get("summary")] if item.get("summary") else [])
        observations.extend(item.get("observations") or [])
        uncertainties.extend(item.get("uncertainties") or [])
        visible_facts.extend(item.get("visible_facts") or [])
        hypotheses.extend(item.get("hypotheses") or [])
        if item.get("recommended_follow_up"):
            follow_ups.append(item["recommended_follow_up"])
        issues.extend(item.get("possible_issues") or [])
        severities.append(item.get("severity") or "info")
        confidences.append(float(item.get("confidence") or 0.0))
        crop_conditions.append(item.get("crop_condition") or "unknown")
        coverage_assessments.append(item.get("coverage_assessment") or "unknown")
        equipment_conditions.append(item.get("equipment_condition") or "unknown")
        media_context = item.get("media_context") or {}
        if media_context:
            media_moments.append({
                "media_kind": media_context.get("media_kind"),
                "frame_timestamp_seconds": media_context.get("frame_timestamp_seconds"),
                "summary": item.get("summary"),
                "severity": item.get("severity"),
                "confidence": item.get("confidence"),
                "possible_issues": item.get("possible_issues") or [],
            })

    severity = max(severities or ["info"], key=lambda value: SEVERITY_ORDER.get(value, 0))

    def dominant(values: list[str], default: str = "unknown") -> str:
        useful = [value for value in values if value and value not in {"unknown", "not_visible"}]
        return max(set(useful), key=useful.count) if useful else default

    analysis = {
        "summary": " ".join(dict.fromkeys(summaries))[:2400],
        "visible_facts": visible_facts[:24],
        "hypotheses": hypotheses[:16],
        "observations": list(dict.fromkeys(observations))[:24],
        "possible_issues": list(dict.fromkeys(issues))[:16],
        "crop_condition": dominant(crop_conditions),
        "coverage_assessment": dominant(coverage_assessments),
        "equipment_condition": dominant(equipment_conditions),
        "severity": severity,
        "confidence": round(sum(confidences) / max(len(confidences), 1), 3),
        "recommended_follow_up": " ".join(dict.fromkeys(follow_ups))[:2200],
        "verification_required": True,
        "uncertainties": list(dict.fromkeys(uncertainties))[:24],
        "media_moments": media_moments[:MAX_IMAGES],
        "images_analyzed": len(completed),
        "images_received": min(len(images), MAX_IMAGES),
        "human_review_required": True,
        "language": str(context.get("language") or "en").strip()[:16] or "en",
    }
    return FieldVisionResult(provider=provider, status="completed", model=model, latency_ms=latency, analysis=analysis)
