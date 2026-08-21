"""Evidence graph and deterministic science checks for Ask AGRO-AI.

This module never asks a language model to decide what is true. It converts the
existing tenant-scoped EvidenceContext into a compact, provenance-bearing graph
that higher-level reasoning can use. Derived values are produced only by
versioned deterministic rules and always retain their inputs.

The first science rules are deliberately narrow. They cover calculations that
are broadly accepted and can be computed safely from explicit inputs:
- FAO crop evapotranspiration identity: ETc = Kc * ETo.
- Irrigation volume from measured flow and runtime.
- Applied depth from measured volume and explicit acreage.

No rule guesses missing agronomic parameters, crop coefficients, efficiency,
root-zone depth, allowable depletion, or regulatory constraints.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.ai import EvidenceContext


GRAPH_SCHEMA_VERSION = "agroai-intelligence-graph/1.0.0"
SCIENCE_RULESET_VERSION = "agroai-agronomy-science/1.0.0"

_DIRECT_TYPES = {
    "field_observation",
    "uploaded_file",
    "telemetry",
    "telemetry_recent",
    "weather",
    "weather_observation",
    "sensor",
    "meter_reading",
    "operator_note",
    "image_observation",
}
_AGGREGATE_TYPES = {
    "readiness_summary",
    "field_intelligence",
    "exceptions",
    "decision_workbench",
    "report_factory",
}
_QUALITY_WEIGHTS = {
    "verified": 1.0,
    "accepted": 0.95,
    "validated": 0.95,
    "live": 0.95,
    "good": 0.9,
    "ok": 0.85,
    "complete": 0.9,
    "partial": 0.65,
    "warning": 0.55,
    "needs_review": 0.5,
    "stale": 0.4,
    "failed": 0.15,
    "invalid": 0.1,
}
_SOURCE_WEIGHTS = {
    "telemetry": 0.96,
    "telemetry_recent": 0.96,
    "meter_reading": 0.95,
    "weather": 0.92,
    "weather_observation": 0.92,
    "sensor": 0.92,
    "field_observation": 0.88,
    "image_observation": 0.82,
    "operator_note": 0.82,
    "uploaded_file": 0.78,
    "data_source": 0.76,
}

_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "eto_mm": ("eto_mm", "et0_mm", "reference_et_mm", "reference_evapotranspiration_mm"),
    "kc": ("kc", "crop_coefficient", "crop_coefficient_kc"),
    "soil_moisture_pct": (
        "soil_moisture_pct",
        "soil_moisture_percent",
        "volumetric_water_content_pct",
        "vwc_pct",
    ),
    "flow_rate_gpm": ("flow_rate_gpm", "flow_gpm", "gpm"),
    "runtime_minutes": ("runtime_minutes", "irrigation_duration_minutes", "duration_minutes"),
    "applied_water_gallons": ("applied_water_gallons", "water_gallons", "gallons"),
    "acreage": ("acreage", "acres", "field_acres"),
}

_CONFLICT_THRESHOLDS = {
    "eto_mm": ("relative", 0.25),
    "kc": ("absolute", 0.20),
    "soil_moisture_pct": ("absolute", 5.0),
    "flow_rate_gpm": ("relative", 0.20),
    "runtime_minutes": ("relative", 0.30),
    "applied_water_gallons": ("relative", 0.20),
    "acreage": ("relative", 0.05),
}


class EvidenceSignal(BaseModel):
    evidence_id: str
    source_type: str
    classification: Literal["observed", "derived", "source", "unknown"]
    title: str
    statement: str
    field_id: str | None = None
    block_id: str | None = None
    observed_at: str | None = None
    freshness_score: float = 0.5
    quality_score: float = 0.7
    confidence_score: float = 0.5
    provenance: dict[str, Any] = Field(default_factory=dict)


class EvidenceConflict(BaseModel):
    metric: str
    evidence_ids: list[str]
    values: list[float]
    severity: Literal["review", "high"] = "review"
    reason: str


class ScienceResult(BaseModel):
    rule_id: str
    name: str
    status: Literal["computed", "not_computable"]
    value: float | None = None
    unit: str | None = None
    inputs: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    formula: str
    assumptions: list[str] = Field(default_factory=list)
    confidence_score: float = 0.0


class IntelligenceGroundingPacket(BaseModel):
    schema_version: str = GRAPH_SCHEMA_VERSION
    science_ruleset_version: str = SCIENCE_RULESET_VERSION
    generated_at: str
    organization_id: str
    workspace_id: str | None = None
    field_id: str | None = None
    crop_type: str | None = None
    region: str | None = None
    observed_facts: list[EvidenceSignal] = Field(default_factory=list)
    derived_context: list[EvidenceSignal] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    science_checks: list[ScienceResult] = Field(default_factory=list)
    source_health: dict[str, Any] = Field(default_factory=dict)
    grounding_confidence: float = 0.0
    decision_constraints: list[str] = Field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _freshness(value: Any, *, now: datetime) -> float:
    dt = _parse_datetime(value)
    if dt is None:
        return 0.50
    age_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
    if age_hours <= 24:
        return 1.0
    if age_hours <= 72:
        return 0.90
    if age_hours <= 24 * 7:
        return 0.78
    if age_hours <= 24 * 30:
        return 0.58
    if age_hours <= 24 * 90:
        return 0.42
    return 0.28


def _quality(value: Any) -> float:
    text = str(value or "").strip().lower()
    if not text:
        return 0.70
    for key, score in _QUALITY_WEIGHTS.items():
        if key in text:
            return score
    return 0.70


def _source_weight(source_type: str) -> float:
    normalized = (source_type or "").strip().lower()
    if normalized.startswith("data_source:"):
        return _SOURCE_WEIGHTS["data_source"]
    return _SOURCE_WEIGHTS.get(normalized, 0.72)


def _bounded_confidence(explicit: Any, *, source_type: str, freshness: float, quality: float) -> float:
    try:
        supplied = float(explicit)
        if math.isfinite(supplied):
            supplied = max(0.0, min(supplied, 1.0))
        else:
            supplied = 0.5
    except (TypeError, ValueError):
        supplied = 0.5
    structural = _source_weight(source_type) * freshness * quality
    return round(max(0.0, min(1.0, 0.55 * structural + 0.45 * supplied)), 3)


def _text(value: Any, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _evidence_id(row: dict[str, Any], index: int) -> str:
    raw = row.get("id") or row.get("source_id") or row.get("filename")
    return _text(raw, 180) or f"context-{index + 1}"


def _classification(source_type: str) -> Literal["observed", "derived", "source", "unknown"]:
    normalized = source_type.strip().lower()
    if normalized in _AGGREGATE_TYPES:
        return "derived"
    if normalized.startswith("data_source:") or normalized == "data_source":
        return "source"
    if normalized in _DIRECT_TYPES or row_looks_observed_type(normalized):
        return "observed"
    return "unknown"


def row_looks_observed_type(source_type: str) -> bool:
    return any(token in source_type for token in ("observation", "telemetry", "sensor", "meter", "weather"))


def _statement(row: dict[str, Any]) -> str:
    payload = row.get("payload")
    if isinstance(payload, dict):
        headline = payload.get("summary") or payload.get("status") or payload.get("recommendation")
        if headline:
            return _text(headline)
        keys = ", ".join(str(key) for key in list(payload.keys())[:8])
        return f"Structured AGRO-AI context available ({keys})" if keys else "Structured AGRO-AI context available"
    return _text(
        row.get("summary")
        or row.get("source_excerpt")
        or row.get("content_excerpt")
        or row.get("parsed_preview")
        or row.get("filename")
        or row.get("title")
        or row.get("type")
    )


def _observed_at(row: dict[str, Any]) -> Any:
    metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
    return (
        row.get("occurred_at")
        or row.get("observed_at")
        or row.get("timestamp")
        or metadata.get("occurred_at")
        or metadata.get("timestamp")
        or metadata.get("captured_at")
    )


def _signal(row: dict[str, Any], index: int, *, now: datetime) -> EvidenceSignal:
    source_type = _text(row.get("type") or row.get("source_type") or row.get("provider") or "unknown", 100)
    classification = _classification(source_type)
    observed_at = _observed_at(row)
    freshness = _freshness(observed_at, now=now)
    quality_value = row.get("quality_status") or row.get("status")
    quality = _quality(quality_value)
    confidence = _bounded_confidence(
        row.get("confidence"),
        source_type=source_type,
        freshness=freshness,
        quality=quality,
    )
    evidence_id = _evidence_id(row, index)
    title = _text(row.get("title") or row.get("filename") or source_type, 200)
    provenance = {
        key: value
        for key, value in {
            "data_source_id": row.get("data_source_id"),
            "provider": row.get("provider"),
            "quality_status": quality_value,
            "method": row.get("method"),
            "model": row.get("model"),
        }.items()
        if value not in (None, "")
    }
    parsed_observed_at = _parse_datetime(observed_at)
    return EvidenceSignal(
        evidence_id=evidence_id,
        source_type=source_type,
        classification=classification,
        title=title,
        statement=_statement(row),
        field_id=_text(row.get("field_id"), 160) or None,
        block_id=_text(row.get("block_id"), 160) or None,
        observed_at=parsed_observed_at.isoformat() if parsed_observed_at else None,
        freshness_score=freshness,
        quality_score=quality,
        confidence_score=confidence,
        provenance=provenance,
    )


def _flatten_numeric(value: Any, prefix: str = "", out: list[tuple[str, float]] | None = None) -> list[tuple[str, float]]:
    result = out if out is not None else []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _flatten_numeric(item, path, result)
    elif isinstance(value, list):
        for index, item in enumerate(value[:30]):
            _flatten_numeric(item, f"{prefix}[{index}]", result)
    elif isinstance(value, bool):
        return result
    elif isinstance(value, (int, float)) and math.isfinite(float(value)):
        result.append((prefix.lower(), float(value)))
    elif isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if re.fullmatch(r"-?\d+(?:\.\d+)?", stripped):
            try:
                result.append((prefix.lower(), float(stripped)))
            except ValueError:
                pass
    return result


def _canonical_metric(path: str) -> str | None:
    leaf = re.split(r"[.\[]", path)[-1].rstrip("]").lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", leaf).strip("_")
    for canonical, aliases in _METRIC_ALIASES.items():
        if normalized in aliases:
            return canonical
    return None


def _numeric_metrics(row: dict[str, Any]) -> dict[str, list[float]]:
    values: dict[str, list[float]] = defaultdict(list)
    candidates = [row.get("value_json"), row.get("metadata_json"), row.get("payload"), row]
    for candidate in candidates:
        for path, value in _flatten_numeric(candidate):
            metric = _canonical_metric(path)
            if metric is not None and value not in values[metric]:
                values[metric].append(value)
    return dict(values)


def _within_day(a: str | None, b: str | None) -> bool:
    da, db = _parse_datetime(a), _parse_datetime(b)
    if da is None or db is None:
        return False
    return abs((da - db).total_seconds()) <= 24 * 3600


def _is_conflict(metric: str, a: float, b: float) -> bool:
    kind, threshold = _CONFLICT_THRESHOLDS.get(metric, ("relative", 0.25))
    if kind == "absolute":
        return abs(a - b) > threshold
    denominator = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denominator > threshold


def _detect_conflicts(rows: list[dict[str, Any]], signals: list[EvidenceSignal]) -> list[EvidenceConflict]:
    readings: dict[str, list[tuple[float, EvidenceSignal]]] = defaultdict(list)
    for row, signal in zip(rows, signals):
        if signal.classification not in {"observed", "source"}:
            continue
        for metric, values in _numeric_metrics(row).items():
            for value in values[:3]:
                readings[metric].append((value, signal))

    conflicts: list[EvidenceConflict] = []
    seen: set[tuple[str, str, str]] = set()
    for metric, entries in readings.items():
        for index, (left_value, left_signal) in enumerate(entries):
            for right_value, right_signal in entries[index + 1:]:
                if left_signal.evidence_id == right_signal.evidence_id:
                    continue
                if left_signal.field_id and right_signal.field_id and left_signal.field_id != right_signal.field_id:
                    continue
                if left_signal.block_id and right_signal.block_id and left_signal.block_id != right_signal.block_id:
                    continue
                if not _within_day(left_signal.observed_at, right_signal.observed_at):
                    continue
                if not _is_conflict(metric, left_value, right_value):
                    continue
                ids = sorted([left_signal.evidence_id, right_signal.evidence_id])
                key = (metric, ids[0], ids[1])
                if key in seen:
                    continue
                seen.add(key)
                severity = "high" if metric in {"soil_moisture_pct", "flow_rate_gpm"} else "review"
                conflicts.append(
                    EvidenceConflict(
                        metric=metric,
                        evidence_ids=ids,
                        values=[left_value, right_value],
                        severity=severity,
                        reason="Comparable recent sources disagree beyond the configured tolerance; resolve before relying on this metric.",
                    )
                )
    return conflicts[:20]


def _metric_candidates(rows: list[dict[str, Any]], signals: list[EvidenceSignal], metric: str) -> list[tuple[float, EvidenceSignal]]:
    result: list[tuple[float, EvidenceSignal]] = []
    for row, signal in zip(rows, signals):
        if signal.classification not in {"observed", "source"}:
            continue
        values = _numeric_metrics(row).get(metric) or []
        for value in values[:3]:
            result.append((value, signal))
    return sorted(result, key=lambda item: item[1].confidence_score, reverse=True)


def _compatible_scope(a: EvidenceSignal, b: EvidenceSignal) -> bool:
    if a.field_id and b.field_id and a.field_id != b.field_id:
        return False
    if a.block_id and b.block_id and a.block_id != b.block_id:
        return False
    if a.observed_at and b.observed_at and not _within_day(a.observed_at, b.observed_at):
        return False
    return True


def _science_checks(rows: list[dict[str, Any]], signals: list[EvidenceSignal]) -> list[ScienceResult]:
    checks: list[ScienceResult] = []

    eto = _metric_candidates(rows, signals, "eto_mm")
    kc = _metric_candidates(rows, signals, "kc")
    computed_etc = False
    for eto_value, eto_signal in eto:
        if not (0.0 <= eto_value <= 30.0):
            continue
        for kc_value, kc_signal in kc:
            if not (0.05 <= kc_value <= 2.0) or not _compatible_scope(eto_signal, kc_signal):
                continue
            confidence = min(eto_signal.confidence_score, kc_signal.confidence_score)
            checks.append(
                ScienceResult(
                    rule_id="fao56.etc.single_kc.v1",
                    name="Crop evapotranspiration",
                    status="computed",
                    value=round(eto_value * kc_value, 4),
                    unit="mm",
                    inputs={"eto_mm": eto_value, "kc": kc_value},
                    evidence_ids=sorted(set([eto_signal.evidence_id, kc_signal.evidence_id])),
                    formula="ETc = Kc × ETo",
                    assumptions=[
                        "ETo and Kc refer to a compatible crop/field and time basis.",
                        "Kc was supplied by evidence; AGRO-AI did not infer a crop coefficient.",
                        "This computes crop evapotranspiration only, not a complete irrigation schedule.",
                    ],
                    confidence_score=round(confidence, 3),
                )
            )
            computed_etc = True
            break
        if computed_etc:
            break

    flow = _metric_candidates(rows, signals, "flow_rate_gpm")
    runtime = _metric_candidates(rows, signals, "runtime_minutes")
    computed_volume = False
    for flow_value, flow_signal in flow:
        if flow_value < 0:
            continue
        for runtime_value, runtime_signal in runtime:
            if runtime_value < 0 or not _compatible_scope(flow_signal, runtime_signal):
                continue
            confidence = min(flow_signal.confidence_score, runtime_signal.confidence_score)
            checks.append(
                ScienceResult(
                    rule_id="irrigation.measured_volume.v1",
                    name="Measured irrigation volume",
                    status="computed",
                    value=round(flow_value * runtime_value, 3),
                    unit="gallons",
                    inputs={"flow_rate_gpm": flow_value, "runtime_minutes": runtime_value},
                    evidence_ids=sorted(set([flow_signal.evidence_id, runtime_signal.evidence_id])),
                    formula="Volume = flow rate × runtime",
                    assumptions=[
                        "The supplied flow rate represents the relevant irrigation interval.",
                        "No distribution-uniformity or application-efficiency correction is inferred.",
                    ],
                    confidence_score=round(confidence, 3),
                )
            )
            computed_volume = True
            break
        if computed_volume:
            break

    gallons = _metric_candidates(rows, signals, "applied_water_gallons")
    acreage = _metric_candidates(rows, signals, "acreage")
    for gallons_value, gallons_signal in gallons:
        if gallons_value < 0:
            continue
        for acres_value, acres_signal in acreage:
            if acres_value <= 0 or not _compatible_scope(gallons_signal, acres_signal):
                continue
            inches = gallons_value / (27154.2857 * acres_value)
            checks.append(
                ScienceResult(
                    rule_id="irrigation.depth_from_volume.v1",
                    name="Applied water depth",
                    status="computed",
                    value=round(inches, 5),
                    unit="inches",
                    inputs={"applied_water_gallons": gallons_value, "acreage": acres_value},
                    evidence_ids=sorted(set([gallons_signal.evidence_id, acres_signal.evidence_id])),
                    formula="Depth(in) = gallons ÷ (27,154.2857 × acres)",
                    assumptions=[
                        "Volume and acreage refer to the same irrigated area.",
                        "This is gross applied depth; no efficiency correction is inferred.",
                    ],
                    confidence_score=round(min(gallons_signal.confidence_score, acres_signal.confidence_score), 3),
                )
            )
            return checks[:12]

    return checks[:12]


def build_intelligence_grounding(
    context: EvidenceContext,
    *,
    field_id: str | None = None,
    now: datetime | None = None,
) -> IntelligenceGroundingPacket:
    current = now.astimezone(timezone.utc) if now and now.tzinfo else (now.replace(tzinfo=timezone.utc) if now else _now())
    rows = [row for row in context.evidence if isinstance(row, dict)]
    signals = [_signal(row, index, now=current) for index, row in enumerate(rows)]
    observed = [signal for signal in signals if signal.classification in {"observed", "source"}]
    derived = [signal for signal in signals if signal.classification in {"derived", "unknown"}]
    conflicts = _detect_conflicts(rows, signals)
    checks = _science_checks(rows, signals)

    scores = [signal.confidence_score for signal in observed if signal.statement]
    source_score = sum(scores) / len(scores) if scores else 0.35
    conflict_penalty = min(0.35, 0.12 * len(conflicts))
    missing_penalty = min(0.25, 0.03 * len(context.missing_data))
    grounding_confidence = round(max(0.05, min(0.98, source_score - conflict_penalty - missing_penalty)), 3)

    fresh_count = sum(1 for signal in observed if signal.freshness_score >= 0.78)
    stale_count = sum(1 for signal in observed if signal.freshness_score < 0.5)
    low_quality_count = sum(1 for signal in observed if signal.quality_score < 0.6)

    return IntelligenceGroundingPacket(
        generated_at=current.isoformat(),
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        field_id=field_id or context.block_id,
        crop_type=context.crop_type,
        region=context.region,
        observed_facts=observed[:40],
        derived_context=derived[:20],
        unknowns=list(dict.fromkeys(str(item) for item in context.missing_data if str(item).strip()))[:30],
        conflicts=conflicts,
        science_checks=checks,
        source_health={
            "direct_or_source_count": len(observed),
            "derived_context_count": len(derived),
            "fresh_count": fresh_count,
            "stale_count": stale_count,
            "low_quality_count": low_quality_count,
            "conflict_count": len(conflicts),
        },
        grounding_confidence=grounding_confidence,
        decision_constraints=[
            "Treat observed evidence, derived calculations, hypotheses, and unknowns as different classes.",
            "Do not assert a number unless it appears in source evidence, the user's question, or a versioned deterministic science result.",
            "Do not infer missing crop coefficients, irrigation efficiency, root-zone depth, allowable depletion, pesticide labels, or legal/compliance status.",
            "Material irrigation, chemical, equipment, regulatory, or external-submission actions require explicit human approval.",
            "Every recommended action must include a verification condition so the result can be checked after execution.",
            "Conflicted measurements must be resolved or explicitly carried as uncertainty before a high-confidence decision.",
        ],
    )


def compact_grounding_packet(packet: IntelligenceGroundingPacket, *, max_chars: int = 18000) -> str:
    """Stable valid JSON for model context, bounded independently from raw evidence."""
    import json

    data = packet.model_dump(mode="python", exclude_none=True)
    text = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    if len(text) <= max_chars:
        return text

    data["observed_facts"] = data.get("observed_facts", [])[:16]
    data["derived_context"] = data.get("derived_context", [])[:8]
    text = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    if len(text) <= max_chars:
        return text

    for row in data.get("observed_facts", []):
        if isinstance(row, dict):
            row["statement"] = str(row.get("statement") or "")[:280]
            row["provenance"] = {
                key: value
                for key, value in (row.get("provenance") or {}).items()
                if key in {"data_source_id", "provider", "quality_status", "method"}
            }
    for row in data.get("derived_context", []):
        if isinstance(row, dict):
            row["statement"] = str(row.get("statement") or "")[:180]
    return json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
