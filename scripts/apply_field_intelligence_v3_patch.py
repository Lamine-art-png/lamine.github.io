from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str, *, flags: int = 0) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one regex match, found {count}: {pattern[:100]!r}")
    target.write_text(updated, encoding="utf-8")


EDGE = "cloudflare/edge-gateway/src/edge-main-v3.ts"
replace_once(
    EDGE,
    'const FIELD_VISION_MODEL = "@cf/llava-hf/llava-1.5-7b-hf";\n',
    'const FIELD_VISION_PRIMARY_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct";\n'
    'const FIELD_VISION_FALLBACK_MODEL = "@cf/llava-hf/llava-1.5-7b-hf";\n'
    'const FIELD_VISION_MODELS = new Set([FIELD_VISION_PRIMARY_MODEL, FIELD_VISION_FALLBACK_MODEL]);\n',
)
replace_once(EDGE, "const FIELD_VISION_MAX_PROMPT = 6000;\n", "const FIELD_VISION_MAX_PROMPT = 8000;\n")
replace_once(
    EDGE,
    "  const model = String(payload.model || FIELD_VISION_MODEL).trim();\n",
    "  const model = String(payload.model || FIELD_VISION_PRIMARY_MODEL).trim();\n",
)
replace_once(
    EDGE,
    '  if (model !== FIELD_VISION_MODEL) return json({ success: false, error: "unsupported_model" }, 400);\n',
    '  if (!FIELD_VISION_MODELS.has(model)) return json({ success: false, error: "unsupported_model" }, 400);\n',
)
replace_once(
    EDGE,
    "  try {\n"
    "    const image = Array.from(decodeBase64(payload.image));\n"
    "    const result = await env.AI.run(FIELD_VISION_MODEL, { image, prompt, max_tokens: 900 });\n"
    "    return json({ success: true, result });\n"
    "  } catch {\n"
    "    return json({ success: false, error: \"workers_ai_unavailable\" }, 502);\n"
    "  }\n",
    "  const image = Array.from(decodeBase64(payload.image));\n"
    "  const candidates = model === FIELD_VISION_PRIMARY_MODEL\n"
    "    ? [FIELD_VISION_PRIMARY_MODEL, FIELD_VISION_FALLBACK_MODEL]\n"
    "    : [model];\n"
    "  for (const candidate of candidates) {\n"
    "    try {\n"
    "      const result = await env.AI.run(candidate, { image, prompt, max_tokens: 1400 });\n"
    "      return json({\n"
    "        success: true,\n"
    "        result,\n"
    "        model: candidate,\n"
    "        degraded: candidate !== FIELD_VISION_PRIMARY_MODEL,\n"
    "      });\n"
    "    } catch {\n"
    "      // Try the bounded fallback only when the stronger primary is unavailable.\n"
    "    }\n"
    "  }\n"
    "  return json({ success: false, error: \"workers_ai_unavailable\" }, 502);\n",
)

VISION = "agroai_api/app/services/field_vision.py"
replace_once(VISION, 'DEFAULT_MODEL = "@cf/llava-hf/llava-1.5-7b-hf"\n', 'DEFAULT_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct"\n')
replace_once(VISION, "MAX_IMAGES = 4\n", "MAX_IMAGES = 8\n")
regex_once(
    VISION,
    r"def _prompt\(context: dict\[str, Any\]\) -> str:\n.*?\n\n\ndef _extract_text",
    '''def _prompt(context: dict[str, Any]) -> str:\n    field = str(context.get("field_name") or "unknown field")[:200]\n    crop = str(context.get("crop") or "unknown crop")[:200]\n    note = str(context.get("note_text") or "")[:1600]\n    media_kind = str(context.get("media_kind") or "photo")[:80]\n    frame_time = context.get("frame_timestamp_seconds")\n    frame_label = f"; frame_time_seconds={frame_time}" if frame_time is not None else ""\n    return f"""\nYou are AGRO-AI Field Vision, an evidence-analysis system for agricultural operations.\nAnalyze this {media_kind} as one piece of evidence, using the operator note only as context.\nContext: field={field}; crop={crop}; operator_note={note or "none"}{frame_label}.\n\nReturn JSON only with this exact shape:\n{{\n  "summary": "concise operational summary",\n  "visible_facts": [{{"label": "visible fact", "evidence": "what in the image supports it", "confidence": 0.0}}],\n  "hypotheses": [{{"label": "possible condition", "evidence": "visible pattern", "confidence": 0.0, "verification": "how to confirm"}}],\n  "observations": ["backward-compatible concise visible observation"],\n  "possible_issues": ["cautious issue category"],\n  "crop_condition": "healthy|mostly_healthy|stressed|damaged|unknown",\n  "coverage_assessment": "adequate|uneven|incomplete|not_visible|unknown",\n  "equipment_condition": "normal|attention_needed|unsafe|not_visible|unknown",\n  "severity": "info|low|medium|high|critical",\n  "confidence": 0.0,\n  "recommended_follow_up": "specific safe next inspection or verification step",\n  "verification_required": true,\n  "uncertainties": ["what cannot be established from this evidence"]\n}}\n\nRules:\n- Separate visible facts from hypotheses. Never present a hypothesis as a confirmed diagnosis.\n- You may identify visible patterns consistent with crop stress, pest/disease symptoms, weed pressure,\n  irrigation/application coverage, equipment problems, completion quality, or unsafe practice.\n- Ordinary RGB imagery cannot measure pesticide concentration, residue, active ingredient, dosage,\n  soil chemistry, internal plant chemistry, or exact moisture. State that these require records, sensors,\n  calibrated equipment data, spectroscopy, or laboratory verification.\n- Do not invent field identity, crop, chemical, measurement, treatment, or completion status.\n- Do not recommend a pesticide/fertilizer product or dosage. Recommend verification and escalation.\n- Confidence must reflect image quality, occlusion, distance, crop context, and ambiguity.\n""".strip()\n\n\ndef _extract_text''',
    flags=re.S,
)
regex_once(
    VISION,
    r"def _bounded_analysis\(raw: dict\[str, Any\]\) -> dict\[str, Any\]:\n.*?\n\n\ndef _analyze_one",
    '''def _bounded_analysis(raw: dict[str, Any]) -> dict[str, Any]:\n    severity = str(raw.get("severity") or "info").lower()\n    if severity not in SEVERITY_ORDER:\n        severity = "info"\n    try:\n        confidence = max(0.0, min(float(raw.get("confidence") or 0.0), 1.0))\n    except (TypeError, ValueError):\n        confidence = 0.0\n\n    def strings(value: Any, *, limit: int = 12) -> list[str]:\n        if not isinstance(value, list):\n            return []\n        return [str(item).strip()[:500] for item in value if str(item).strip()][:limit]\n\n    def findings(value: Any, *, limit: int = 12, hypothesis: bool = False) -> list[dict[str, Any]]:\n        if not isinstance(value, list):\n            return []\n        rows: list[dict[str, Any]] = []\n        for item in value[:limit]:\n            if isinstance(item, str):\n                item = {"label": item}\n            if not isinstance(item, dict):\n                continue\n            label = str(item.get("label") or "").strip()[:300]\n            if not label:\n                continue\n            try:\n                item_confidence = max(0.0, min(float(item.get("confidence") or 0.0), 1.0))\n            except (TypeError, ValueError):\n                item_confidence = 0.0\n            row: dict[str, Any] = {\n                "label": label,\n                "evidence": str(item.get("evidence") or "").strip()[:700],\n                "confidence": item_confidence,\n            }\n            if hypothesis:\n                row["verification"] = str(item.get("verification") or "").strip()[:700]\n            rows.append(row)\n        return rows\n\n    allowed_condition = {"healthy", "mostly_healthy", "stressed", "damaged", "unknown"}\n    allowed_coverage = {"adequate", "uneven", "incomplete", "not_visible", "unknown"}\n    allowed_equipment = {"normal", "attention_needed", "unsafe", "not_visible", "unknown"}\n    crop_condition = str(raw.get("crop_condition") or "unknown").lower()\n    coverage = str(raw.get("coverage_assessment") or "unknown").lower()\n    equipment = str(raw.get("equipment_condition") or "unknown").lower()\n    possible_issues = strings(raw.get("possible_issues"))\n    legacy_issue = str(raw.get("possible_issue") or "").strip()\n    if legacy_issue and legacy_issue.lower() != "none" and legacy_issue not in possible_issues:\n        possible_issues.append(legacy_issue[:500])\n\n    return {\n        "summary": str(raw.get("summary") or "").strip()[:1600],\n        "visible_facts": findings(raw.get("visible_facts")),\n        "hypotheses": findings(raw.get("hypotheses"), hypothesis=True),\n        "observations": strings(raw.get("observations")),\n        "possible_issues": possible_issues[:12],\n        "crop_condition": crop_condition if crop_condition in allowed_condition else "unknown",\n        "coverage_assessment": coverage if coverage in allowed_coverage else "unknown",\n        "equipment_condition": equipment if equipment in allowed_equipment else "unknown",\n        "severity": severity,\n        "confidence": confidence,\n        "recommended_follow_up": str(raw.get("recommended_follow_up") or "").strip()[:1600],\n        "verification_required": bool(raw.get("verification_required", True)),\n        "uncertainties": strings(raw.get("uncertainties")),\n    }\n\n\ndef _analyze_one''',
    flags=re.S,
)
replace_once(
    VISION,
    "        payload = response.json()\n        text = _extract_text(payload)\n",
    "        payload = response.json()\n        actual_model = str(payload.get(\"model\") or model) if isinstance(payload, dict) else model\n        text = _extract_text(payload)\n",
)
replace_once(
    VISION,
    '            provider="cloudflare_workers_ai", status="completed", model=model,\n            latency_ms=latency, analysis=_bounded_analysis(_json_from_text(text)),\n',
    '            provider="cloudflare_workers_ai", status="completed", model=actual_model,\n            latency_ms=latency, analysis=_bounded_analysis(_json_from_text(text)),\n',
)
replace_once(
    VISION,
    "def analyze_field_images(images: list[tuple[bytes, str | None]], context: dict[str, Any]) -> FieldVisionResult:\n",
    "def analyze_field_images(images: list[tuple], context: dict[str, Any]) -> FieldVisionResult:\n",
)
replace_once(
    VISION,
    "    for image, content_type in images[:MAX_IMAGES]:\n        result = _analyze_one(image, content_type, context)\n",
    "    for item in images[:MAX_IMAGES]:\n"
    "        image, content_type = item[0], item[1]\n"
    "        item_context = dict(context)\n"
    "        if len(item) > 2 and isinstance(item[2], dict):\n"
    "            item_context.update(item[2])\n"
    "        result = _analyze_one(image, content_type, item_context)\n"
    "        if result.succeeded and len(item) > 2 and isinstance(item[2], dict):\n"
    "            result.analysis[\"media_context\"] = dict(item[2])\n",
)
regex_once(
    VISION,
    r"    observations: list\[str\] = \[\]\n.*?    return FieldVisionResult\(provider=provider, status=\"completed\", model=model, latency_ms=latency, analysis=analysis\)\n",
    '''    observations: list[str] = []\n    uncertainties: list[str] = []\n    summaries: list[str] = []\n    follow_ups: list[str] = []\n    issues: list[str] = []\n    severities: list[str] = []\n    confidences: list[float] = []\n    visible_facts: list[dict[str, Any]] = []\n    hypotheses: list[dict[str, Any]] = []\n    media_moments: list[dict[str, Any]] = []\n    crop_conditions: list[str] = []\n    coverage_assessments: list[str] = []\n    equipment_conditions: list[str] = []\n    for item in completed:\n        summaries.extend([item.get("summary")] if item.get("summary") else [])\n        observations.extend(item.get("observations") or [])\n        uncertainties.extend(item.get("uncertainties") or [])\n        visible_facts.extend(item.get("visible_facts") or [])\n        hypotheses.extend(item.get("hypotheses") or [])\n        if item.get("recommended_follow_up"):\n            follow_ups.append(item["recommended_follow_up"])\n        issues.extend(item.get("possible_issues") or [])\n        severities.append(item.get("severity") or "info")\n        confidences.append(float(item.get("confidence") or 0.0))\n        crop_conditions.append(item.get("crop_condition") or "unknown")\n        coverage_assessments.append(item.get("coverage_assessment") or "unknown")\n        equipment_conditions.append(item.get("equipment_condition") or "unknown")\n        media_context = item.get("media_context") or {}\n        if media_context:\n            media_moments.append({\n                "media_kind": media_context.get("media_kind"),\n                "frame_timestamp_seconds": media_context.get("frame_timestamp_seconds"),\n                "summary": item.get("summary"),\n                "severity": item.get("severity"),\n                "confidence": item.get("confidence"),\n                "possible_issues": item.get("possible_issues") or [],\n            })\n\n    severity = max(severities or ["info"], key=lambda value: SEVERITY_ORDER.get(value, 0))\n\n    def dominant(values: list[str], default: str = "unknown") -> str:\n        useful = [value for value in values if value and value not in {"unknown", "not_visible"}]\n        return max(set(useful), key=useful.count) if useful else default\n\n    analysis = {\n        "summary": " ".join(dict.fromkeys(summaries))[:2400],\n        "visible_facts": visible_facts[:24],\n        "hypotheses": hypotheses[:16],\n        "observations": list(dict.fromkeys(observations))[:24],\n        "possible_issues": list(dict.fromkeys(issues))[:16],\n        "crop_condition": dominant(crop_conditions),\n        "coverage_assessment": dominant(coverage_assessments),\n        "equipment_condition": dominant(equipment_conditions),\n        "severity": severity,\n        "confidence": round(sum(confidences) / max(len(confidences), 1), 3),\n        "recommended_follow_up": " ".join(dict.fromkeys(follow_ups))[:2200],\n        "verification_required": True,\n        "uncertainties": list(dict.fromkeys(uncertainties))[:24],\n        "media_moments": media_moments[:MAX_IMAGES],\n        "images_analyzed": len(completed),\n        "images_received": min(len(images), MAX_IMAGES),\n        "human_review_required": True,\n    }\n    return FieldVisionResult(provider=provider, status="completed", model=model, latency_ms=latency, analysis=analysis)\n''',
    flags=re.S,
)

VIDEO_HELPER = r'''"""Bounded preprocessing for Field Intelligence walk-and-talk video."""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

MAX_VIDEO_BYTES = 64 * 1024 * 1024
MAX_FRAME_BYTES = 3 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024


@dataclass
class VideoFramesResult:
    frames: list[tuple[bytes, str, dict]] = field(default_factory=list)
    status: str = "skipped"
    error: str | None = None


@dataclass
class VideoAudioResult:
    audio: bytes | None = None
    content_type: str | None = None
    status: str = "skipped"
    error: str | None = None


def _ffmpeg_path() -> str:
    return str(getattr(settings, "FIELD_MEDIA_FFMPEG_PATH", "") or os.getenv("FIELD_MEDIA_FFMPEG_PATH") or "ffmpeg")


def _run(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=max(2.0, timeout),
    )


def extract_video_audio(video: bytes, *, content_type: str | None = None) -> VideoAudioResult:
    if not video or len(video) > MAX_VIDEO_BYTES:
        return VideoAudioResult(status="failed", error="video_outside_preprocessing_bound")
    suffix = ".mp4" if "mp4" in (content_type or "").lower() else ".webm"
    try:
        with tempfile.TemporaryDirectory(prefix="agroai-fi-video-") as directory:
            source = Path(directory) / f"input{suffix}"
            output = Path(directory) / "audio.mp3"
            source.write_bytes(video)
            completed = _run(
                [
                    _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
                    str(output),
                ],
                timeout=float(getattr(settings, "FIELD_MEDIA_PROBE_TIMEOUT_SECONDS", 20.0) or 20.0) * 2,
            )
            if completed.returncode != 0 or not output.exists():
                return VideoAudioResult(status="failed", error="video_audio_extraction_failed")
            audio = output.read_bytes()
            if not audio or len(audio) > MAX_AUDIO_BYTES:
                return VideoAudioResult(status="failed", error="extracted_audio_outside_bound")
            return VideoAudioResult(audio=audio, content_type="audio/mpeg", status="completed")
    except subprocess.TimeoutExpired:
        return VideoAudioResult(status="failed", error="video_audio_extraction_timeout")
    except Exception as exc:  # noqa: BLE001
        return VideoAudioResult(status="failed", error=exc.__class__.__name__)


def extract_video_frames(
    video: bytes,
    *,
    content_type: str | None = None,
    duration_seconds: float | None = None,
    max_frames: int = 8,
) -> VideoFramesResult:
    if not video or len(video) > MAX_VIDEO_BYTES:
        return VideoFramesResult(status="failed", error="video_outside_preprocessing_bound")
    count = max(1, min(int(max_frames or 1), 8))
    duration = max(float(duration_seconds or 0.0), 1.0)
    interval = max(duration / count, 1.0)
    suffix = ".mp4" if "mp4" in (content_type or "").lower() else ".webm"
    try:
        with tempfile.TemporaryDirectory(prefix="agroai-fi-frames-") as directory:
            source = Path(directory) / f"input{suffix}"
            pattern = Path(directory) / "frame-%03d.jpg"
            source.write_bytes(video)
            completed = _run(
                [
                    _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", str(source),
                    "-vf", f"fps=1/{interval:.3f},scale=1600:-2:force_original_aspect_ratio=decrease",
                    "-frames:v", str(count), "-q:v", "3", str(pattern),
                ],
                timeout=float(getattr(settings, "FIELD_MEDIA_PROBE_TIMEOUT_SECONDS", 20.0) or 20.0) * 3,
            )
            if completed.returncode != 0:
                return VideoFramesResult(status="failed", error="video_frame_extraction_failed")
            rows: list[tuple[bytes, str, dict]] = []
            for index, path in enumerate(sorted(Path(directory).glob("frame-*.jpg"))[:count]):
                payload = path.read_bytes()
                if not payload or len(payload) > MAX_FRAME_BYTES:
                    continue
                rows.append((
                    payload,
                    "image/jpeg",
                    {
                        "media_kind": "video_frame",
                        "frame_timestamp_seconds": round(min((index + 0.5) * interval, duration), 2),
                    },
                ))
            if not rows:
                return VideoFramesResult(status="failed", error="no_video_frames_extracted")
            return VideoFramesResult(frames=rows, status="completed")
    except subprocess.TimeoutExpired:
        return VideoFramesResult(status="failed", error="video_frame_extraction_timeout")
    except Exception as exc:  # noqa: BLE001
        return VideoFramesResult(status="failed", error=exc.__class__.__name__)
'''
(ROOT / "agroai_api/app/services/field_video.py").write_text(VIDEO_HELPER, encoding="utf-8")

VISION_EXTENSION = r'''"""Install the multimodal Field Intelligence pipeline extension.

The extension preserves the durable voice pipeline, adds walk-and-talk video
transcription and representative-frame analysis, repairs inference precedence,
and keeps every visual conclusion explicitly reviewable.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.models.field_intelligence import FieldCaptureSession, FieldObservation, FieldObservationAsset
from app.services.field_video import MAX_VIDEO_BYTES, extract_video_audio, extract_video_frames
from app.services.field_vision import MAX_IMAGE_BYTES, analyze_field_images

_INSTALLED = False
_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _source_text(observation: FieldObservation, session: FieldCaptureSession | None) -> str:
    return (
        observation.corrected_transcript
        or observation.transcript
        or (session.note_text if session else None)
        or observation.summary
        or ""
    )


def _repair_text_inference(svc: Any, observation: FieldObservation) -> None:
    structured = dict(observation.structured_json or {})
    inferred_event = str(structured.get("event_type") or "observation").lower()
    current_event = str(observation.event_type or "observation").lower()
    if current_event == "observation" and inferred_event not in {"", "observation"}:
        observation.event_type = inferred_event

    inferred_severity = str(structured.get("severity") or "info").lower()
    current_severity = str(observation.severity or "info").lower()
    if _SEVERITY_ORDER.get(inferred_severity, 0) > _SEVERITY_ORDER.get(current_severity, 0):
        observation.severity = inferred_severity

    method = str(structured.get("method") or "").strip()
    provider = str(structured.get("provider") or "").strip()
    model = str(structured.get("model") or "").strip()
    if method:
        observation.model_provider = provider or ("model_router" if method.startswith("model-") else "deterministic")
        observation.model_name = model or method
        provenance = dict(observation.provenance_json or {})
        provenance.update({
            "extraction_method": method,
            "extraction_provider": provider or None,
            "extraction_model": model or None,
        })
        observation.provenance_json = provenance


def install_field_vision_extension(svc: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(svc, "_field_vision_extension_installed", False):
        return

    original_process = svc._process_observation
    original_load_audio = svc._load_capture_audio

    def load_audio_or_video(db, observation):
        audio, asset = original_load_audio(db, observation)
        if audio:
            return audio, asset
        video = (
            db.query(FieldObservationAsset)
            .filter(FieldObservationAsset.tenant_id == observation.tenant_id)
            .filter(FieldObservationAsset.capture_session_id == observation.capture_session_id)
            .filter(FieldObservationAsset.kind == "video")
            .filter(FieldObservationAsset.status == "stored")
            .order_by(FieldObservationAsset.created_at.asc())
            .first()
        )
        if not video or not video.object_ref:
            return None, None
        try:
            payload = svc._object_store().read_bytes(
                video.object_ref,
                max_bytes=MAX_VIDEO_BYTES,
                tenant_id=observation.tenant_id,
                connection_id=observation.capture_session_id,
            )
        except Exception:  # noqa: BLE001
            return None, None
        extracted = extract_video_audio(payload, content_type=video.content_type)
        if extracted.status == "completed" and extracted.audio:
            proxy = SimpleNamespace(
                id=video.id,
                kind="audio_from_video",
                content_type=extracted.content_type,
                duration_seconds=video.duration_seconds,
            )
            return extracted.audio, proxy
        provider_limit = int(getattr(svc.settings, "FIELD_TRANSCRIPTION_MAX_BYTES", 25 * 1024 * 1024) or 25 * 1024 * 1024)
        if len(payload) <= provider_limit:
            return payload, video
        return None, None

    def process_with_vision(db, job, *, heartbeat=None):
        job_input = dict(job.input_json or {})
        pre_observation = db.get(FieldObservation, job_input.get("observation_id"))
        if pre_observation is not None:
            pre_session = db.get(FieldCaptureSession, pre_observation.capture_session_id)
            preview = str(getattr(pre_session, "transcript_preview", None) or "").strip()
            if preview and not job_input.get("corrected_transcript") and not pre_observation.corrected_transcript:
                job_input["corrected_transcript"] = preview
                job.input_json = job_input

        original_process(db, job, heartbeat=heartbeat)

        observation = db.get(FieldObservation, job_input.get("observation_id"))
        if observation is None or observation.status == "deleted":
            return
        session = db.get(FieldCaptureSession, observation.capture_session_id)
        _repair_text_inference(svc, observation)

        assets = (
            db.query(FieldObservationAsset)
            .filter(FieldObservationAsset.tenant_id == observation.tenant_id)
            .filter(FieldObservationAsset.observation_id == observation.id)
            .filter(FieldObservationAsset.kind.in_(["photo", "video"]))
            .filter(FieldObservationAsset.status == "stored")
            .order_by(FieldObservationAsset.created_at.asc())
            .limit(8)
            .all()
        )
        if not assets:
            db.flush()
            return

        if heartbeat is not None:
            heartbeat.check()

        media_inputs: list[tuple] = []
        asset_ids: list[str] = []
        read_errors: list[str] = []
        frame_errors: list[str] = []
        video_frame_count = 0
        store = svc._object_store()
        for asset in assets:
            if not asset.object_ref or not observation.capture_session_id:
                continue
            try:
                max_bytes = MAX_IMAGE_BYTES if asset.kind == "photo" else MAX_VIDEO_BYTES
                payload = store.read_bytes(
                    asset.object_ref,
                    max_bytes=max_bytes,
                    tenant_id=observation.tenant_id,
                    connection_id=observation.capture_session_id,
                )
                asset_ids.append(asset.id)
                if asset.kind == "photo":
                    media_inputs.append((payload, asset.content_type, {"media_kind": "photo", "asset_id": asset.id}))
                else:
                    frames = extract_video_frames(
                        payload,
                        content_type=asset.content_type,
                        duration_seconds=asset.duration_seconds,
                        max_frames=max(2, min(6, 8 - len(media_inputs))),
                    )
                    if frames.status == "completed":
                        for frame, content_type, context in frames.frames:
                            media_inputs.append((frame, content_type, {**context, "asset_id": asset.id}))
                        video_frame_count += len(frames.frames)
                    elif frames.error:
                        frame_errors.append(frames.error)
            except Exception as exc:  # noqa: BLE001
                read_errors.append(exc.__class__.__name__)

        if not media_inputs:
            observation.status = "needs_review"
            provenance = dict(observation.provenance_json or {})
            provenance.update({
                "vision_status": "failed",
                "vision_error": "no_analyzable_media",
                "vision_asset_ids": asset_ids,
            })
            observation.provenance_json = provenance
            svc._audit(
                observation,
                "vision_analysis_unavailable",
                actor="system",
                details={"asset_ids": asset_ids, "read_errors": read_errors, "frame_errors": frame_errors},
            )
            db.flush()
            return

        result = analyze_field_images(
            media_inputs,
            {
                "field_name": observation.field_name,
                "crop": observation.crop,
                "note_text": _source_text(observation, session),
                "media_kind": "mixed_field_evidence",
            },
        )

        svc._record_run(
            db,
            observation,
            stage="vision",
            provider=result.provider,
            stage_status=result.status,
            model=result.model,
            latency_ms=result.latency_ms,
            error=result.error,
            attempt_count=int(job.attempt_count or 1),
            output={
                "asset_ids": asset_ids,
                "media_items_analyzed": int(result.analysis.get("images_analyzed") or 0),
                "video_frames_analyzed": video_frame_count,
                "confidence": result.analysis.get("confidence"),
                "read_errors": read_errors,
                "frame_errors": frame_errors,
                "human_review_required": True,
            },
        )

        provenance = dict(observation.provenance_json or {})
        provenance.update({
            "vision_provider": result.provider,
            "vision_model": result.model,
            "vision_status": result.status,
            "vision_media_analyzed": int(result.analysis.get("images_analyzed") or 0),
            "vision_video_frames_analyzed": video_frame_count,
            "vision_human_review_required": True,
        })
        observation.provenance_json = provenance

        if result.succeeded:
            structured = dict(observation.structured_json or {})
            structured["vision"] = result.analysis
            observation.structured_json = structured

            summary = str(result.analysis.get("summary") or "").strip()
            if summary:
                if not (observation.summary or "").strip():
                    observation.summary = summary
                elif summary.lower() not in str(observation.summary).lower():
                    observation.summary = f"{observation.summary} Visual evidence: {summary}"[:4000]

            follow_up = str(result.analysis.get("recommended_follow_up") or "").strip()
            if follow_up and not (observation.recommended_action or "").strip():
                observation.recommended_action = follow_up

            visual_severity = str(result.analysis.get("severity") or "info").lower()
            current_severity = str(observation.severity or "info").lower()
            if _SEVERITY_ORDER.get(visual_severity, 0) > _SEVERITY_ORDER.get(current_severity, 0):
                observation.severity = visual_severity

            try:
                visual_confidence = float(result.analysis.get("confidence") or 0.0)
            except (TypeError, ValueError):
                visual_confidence = 0.0
            observation.confidence = max(float(observation.confidence or 0.0), min(visual_confidence * 0.85, 0.85))

            uncertainties = list(observation.uncertain_fields_json or [])
            for item in (
                "visual_analysis_requires_human_confirmation",
                *list(result.analysis.get("uncertainties") or []),
            ):
                text = str(item).strip()[:300]
                if text and text not in uncertainties:
                    uncertainties.append(text)
            observation.uncertain_fields_json = uncertainties[:40]

            issues = list(result.analysis.get("possible_issues") or [])
            hypotheses = list(result.analysis.get("hypotheses") or [])
            if issues or hypotheses or _SEVERITY_ORDER.get(visual_severity, 0) >= _SEVERITY_ORDER["medium"]:
                if not observation.event_type or observation.event_type == "observation":
                    observation.event_type = "issue"
                observation.status = "needs_review"

            visual_search = " ".join([
                summary,
                " ".join(result.analysis.get("observations") or []),
                " ".join(issues),
                " ".join(str(item.get("label") or "") for item in hypotheses if isinstance(item, dict)),
                follow_up,
            ]).strip()
            if visual_search:
                observation.search_text = f"{observation.search_text or ''} {visual_search}".strip()[:12000]

            svc._audit(
                observation,
                "vision_analysis_completed",
                actor="system",
                details={
                    "provider": result.provider,
                    "model": result.model,
                    "asset_ids": asset_ids,
                    "media_analyzed": int(result.analysis.get("images_analyzed") or 0),
                    "video_frames_analyzed": video_frame_count,
                    "human_review_required": True,
                },
            )
        else:
            observation.status = "needs_review"
            svc._audit(
                observation,
                "vision_analysis_unavailable",
                actor="system",
                details={
                    "provider": result.provider,
                    "model": result.model,
                    "error": result.error,
                    "asset_ids": asset_ids,
                    "read_errors": read_errors,
                    "frame_errors": frame_errors,
                },
            )

        correlation = svc.correlate_observation(db, observation)
        observation.correlation_json = correlation
        observation.evidence_ids_json = list(dict.fromkeys([
            *(observation.evidence_ids_json or []),
            *list(correlation.get("relevant_evidence_ids", [])),
        ]))
        if not observation.recommended_action:
            observation.recommended_action = correlation.get("recommended_next_action")

        evidence = svc._find_evidence_slow(db, observation)
        if evidence is not None:
            svc._apply_evidence_fields(
                evidence,
                observation,
                source_text=_source_text(observation, session) or "Visual field evidence",
                transcription_ok=bool(observation.corrected_transcript or observation.transcript),
            )

        if heartbeat is not None:
            heartbeat.check()
        db.flush()

    svc._load_capture_audio = load_audio_or_video
    svc._process_observation = process_with_vision
    svc._field_vision_extension_installed = True
    _INSTALLED = True
'''
(ROOT / "agroai_api/app/services/field_intelligence_vision_extension.py").write_text(VISION_EXTENSION, encoding="utf-8")

QUEUE = "figma-enterprise-v4/src/app/fieldIntelligence/offlineQueue.ts"
replace_once(
    QUEUE,
    "  noteText?: string;\n",
    "  noteText?: string;\n  transcriptPreview?: string;\n  language?: string;\n",
)
replace_once(
    QUEUE,
    "    note_text: record.noteText,\n",
    "    note_text: record.noteText,\n    transcript_preview: record.transcriptPreview,\n",
)
replace_once(
    QUEUE,
    "    const completed = await api.complete(record.serverCaptureId || record.clientCaptureId, {});\n",
    "    const completed = await api.complete(record.serverCaptureId || record.clientCaptureId, {\n"
    "      corrected_transcript: record.transcriptPreview,\n"
    "      language: record.language || \"en\",\n"
    "    });\n",
)

COMPONENT = "figma-enterprise-v4/src/app/components/FieldIntelligenceV2.tsx"
replace_once(COMPONENT, "  Square, Trash2, X,\n", "  Square, Trash2, Video, X,\n")
replace_once(
    COMPONENT,
    "  const [audioUrl, setAudioUrl] = useState<string | null>(null);\n",
    "  const [audioUrl, setAudioUrl] = useState<string | null>(null);\n"
    "  const [walkVideoFile, setWalkVideoFile] = useState<File | null>(null);\n"
    "  const [walkVideoUrl, setWalkVideoUrl] = useState<string | null>(null);\n"
    "  const [videoRecording, setVideoRecording] = useState(false);\n"
    "  const [videoElapsed, setVideoElapsed] = useState(0);\n",
)
replace_once(
    COMPONENT,
    "  const timerRef = useRef<number | null>(null);\n  const elapsedRef = useRef(0);\n",
    "  const timerRef = useRef<number | null>(null);\n"
    "  const elapsedRef = useRef(0);\n"
    "  const videoRecorderRef = useRef<MediaRecorder | null>(null);\n"
    "  const videoStreamRef = useRef<MediaStream | null>(null);\n"
    "  const videoPreviewRef = useRef<HTMLVideoElement | null>(null);\n"
    "  const videoChunksRef = useRef<Blob[]>([]);\n"
    "  const videoStopWaitersRef = useRef<Array<() => void>>([]);\n"
    "  const videoTimerRef = useRef<number | null>(null);\n"
    "  const videoElapsedRef = useRef(0);\n",
)
replace_once(
    COMPONENT,
    "  const clearTimer = useCallback(() => {\n    if (timerRef.current !== null) window.clearInterval(timerRef.current);\n    timerRef.current = null;\n  }, []);\n",
    "  const clearTimer = useCallback(() => {\n"
    "    if (timerRef.current !== null) window.clearInterval(timerRef.current);\n"
    "    timerRef.current = null;\n"
    "  }, []);\n\n"
    "  const releaseVideoStream = useCallback(() => {\n"
    "    videoStreamRef.current?.getTracks().forEach((track) => track.stop());\n"
    "    videoStreamRef.current = null;\n"
    "    if (videoPreviewRef.current) videoPreviewRef.current.srcObject = null;\n"
    "  }, []);\n\n"
    "  const clearVideoTimer = useCallback(() => {\n"
    "    if (videoTimerRef.current !== null) window.clearInterval(videoTimerRef.current);\n"
    "    videoTimerRef.current = null;\n"
    "  }, []);\n\n"
    "  const setRecordedVideo = useCallback((file: File | null) => {\n"
    "    setWalkVideoFile(file);\n"
    "    setWalkVideoUrl((current) => {\n"
    "      if (current) URL.revokeObjectURL(current);\n"
    "      return file ? URL.createObjectURL(file) : null;\n"
    "    });\n"
    "  }, []);\n",
)
replace_once(
    COMPONENT,
    "  useEffect(() => () => {\n    clearTimer();\n    stopRecognition();\n    releaseStream();\n    if (audioUrl) URL.revokeObjectURL(audioUrl);\n  }, [audioUrl, clearTimer, releaseStream, stopRecognition]);\n",
    "  useEffect(() => () => {\n"
    "    clearTimer();\n"
    "    clearVideoTimer();\n"
    "    stopRecognition();\n"
    "    releaseStream();\n"
    "    releaseVideoStream();\n"
    "    if (audioUrl) URL.revokeObjectURL(audioUrl);\n"
    "    if (walkVideoUrl) URL.revokeObjectURL(walkVideoUrl);\n"
    "  }, [audioUrl, clearTimer, clearVideoTimer, releaseStream, releaseVideoStream, stopRecognition, walkVideoUrl]);\n",
)
insert_after_recording = '''\n\n  const stopWalkVideo = useCallback(async () => {\n    const recorder = videoRecorderRef.current;\n    if (!recorder || recorder.state === "inactive") {\n      clearVideoTimer(); stopRecognition(); releaseVideoStream(); setVideoRecording(false); return;\n    }\n    await new Promise<void>((resolve) => {\n      videoStopWaitersRef.current.push(resolve);\n      try { recorder.stop(); } catch { resolve(); }\n    });\n  }, [clearVideoTimer, releaseVideoStream, stopRecognition]);\n\n  const startWalkVideo = useCallback(async () => {\n    setMicError(null);\n    setReviewing(false);\n    setLiveTranscript("");\n    setInterimTranscript("");\n    setRecordedVideo(null);\n    captureLocation(true);\n    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {\n      setMicError(t("fieldIntel.videoUnsupported"));\n      return;\n    }\n    try {\n      const stream = await navigator.mediaDevices.getUserMedia({\n        audio: true,\n        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },\n      });\n      releaseVideoStream();\n      videoStreamRef.current = stream;\n      if (videoPreviewRef.current) {\n        videoPreviewRef.current.srcObject = stream;\n        await videoPreviewRef.current.play().catch(() => undefined);\n      }\n      const preferred = [\n        "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4",\n      ].find((kind) => MediaRecorder.isTypeSupported(kind));\n      const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);\n      videoRecorderRef.current = recorder;\n      videoChunksRef.current = [];\n      recorder.ondataavailable = (event) => { if (event.data.size > 0) videoChunksRef.current.push(event.data); };\n      recorder.onstop = () => {\n        const blob = new Blob(videoChunksRef.current, { type: recorder.mimeType || "video/webm" });\n        const extension = (recorder.mimeType || "").includes("mp4") ? "mp4" : "webm";\n        if (blob.size > 0) setRecordedVideo(new File([blob], `field-walk-${Date.now()}.${extension}`, { type: blob.type }));\n        clearVideoTimer();\n        stopRecognition();\n        releaseVideoStream();\n        setVideoRecording(false);\n        videoStopWaitersRef.current.splice(0).forEach((resolve) => resolve());\n      };\n      recorder.start(1000);\n      startRecognition();\n      setVideoRecording(true);\n      videoElapsedRef.current = 0;\n      setVideoElapsed(0);\n      videoTimerRef.current = window.setInterval(() => {\n        videoElapsedRef.current += 1;\n        setVideoElapsed(videoElapsedRef.current);\n        if (videoElapsedRef.current >= MAX_RECORDING_SECONDS) void stopWalkVideo();\n      }, 1000);\n    } catch (error: any) {\n      releaseVideoStream();\n      setMicError(error?.name === "NotAllowedError" ? t("fieldIntel.videoDenied") : t("fieldIntel.videoUnsupported"));\n    }\n  }, [captureLocation, clearVideoTimer, releaseVideoStream, setRecordedVideo, startRecognition, stopRecognition, stopWalkVideo, t]);\n'''
replace_once(
    COMPONENT,
    "  const addFiles = useCallback(async (files: File[]) => {\n",
    insert_after_recording + "\n  const addFiles = useCallback(async (files: File[]) => {\n",
)
replace_once(
    COMPONENT,
    "    setLiveTranscript(\"\"); setInterimTranscript(\"\"); setReviewing(false); setRecordedAudio(null); setElapsed(0);\n  }, [setRecordedAudio]);\n",
    "    setLiveTranscript(\"\"); setInterimTranscript(\"\"); setReviewing(false); setRecordedAudio(null); setRecordedVideo(null);\n"
    "    setElapsed(0); setVideoElapsed(0);\n"
    "  }, [setRecordedAudio, setRecordedVideo]);\n",
)
replace_once(
    COMPONENT,
    "    const fileAssets = attachments.map((file, index) => ({\n",
    "    const queuedFiles = walkVideoFile ? [...attachments, walkVideoFile] : attachments;\n"
    "    const fileAssets = queuedFiles.map((file, index) => ({\n",
)
replace_once(COMPONENT, '      captureSource: audioFile ? "voice" : "typed",\n', '      captureSource: audioFile || walkVideoFile ? "voice" : "typed",\n')
replace_once(
    COMPONENT,
    "      noteText: note.trim() || transcriptPreview || undefined,\n",
    "      noteText: note.trim() || transcriptPreview || undefined,\n"
    "      transcriptPreview: transcriptPreview || undefined,\n"
    "      language: document.documentElement.lang || navigator.language || \"en\",\n",
)
replace_once(
    COMPONENT,
    "  }, [assignee, attachments, audioFile, blockName, crop, elapsed, eventType, fieldName, liveTranscript, location, note, onSaved, reset, severity, t, workspaceId]);\n",
    "  }, [assignee, attachments, audioFile, blockName, crop, elapsed, eventType, fieldName, liveTranscript, location, note, onSaved, reset, severity, t, walkVideoFile, workspaceId]);\n",
)
replace_once(
    COMPONENT,
    "        {audioUrl && <audio controls src={audioUrl} className=\"mt-4 w-full\" aria-label={t(\"fieldIntel.audioPlayer\")} />}\n",
    "        {audioUrl && <audio controls src={audioUrl} className=\"mt-4 w-full\" aria-label={t(\"fieldIntel.audioPlayer\")} />}\n"
    "        {walkVideoUrl && <video controls playsInline src={walkVideoUrl} className=\"mt-4 max-h-[360px] w-full rounded-xl bg-black\" aria-label={t(\"fieldIntel.videoPlayer\")} />}\n",
)
replace_once(
    COMPONENT,
    "      {audioUrl && !recording && <div className=\"mt-3 flex items-center gap-2 rounded-xl border border-[#D6DDD0] p-2\">\n",
    "      {videoRecording && <div className=\"mt-3 overflow-hidden rounded-xl border border-[#BFD8C9] bg-black\">\n"
    "        <video ref={videoPreviewRef} muted playsInline autoPlay className=\"max-h-[420px] w-full object-cover\" />\n"
    "        <div className=\"flex items-center justify-between bg-[#10231B] px-3 py-2 text-[12px] font-semibold text-white\">\n"
    "          <span>{t(\"fieldIntel.walkRecording\")} {Math.floor(videoElapsed / 60)}:{String(videoElapsed % 60).padStart(2, \"0\")}</span>\n"
    "          <span>{location ? t(\"fieldIntel.locationCaptured\") : t(\"fieldIntel.captureLocation\")}</span>\n"
    "        </div>\n"
    "      </div>}\n"
    "      {walkVideoUrl && !videoRecording && <div className=\"mt-3 rounded-xl border border-[#D6DDD0] p-2\">\n"
    "        <video controls playsInline src={walkVideoUrl} className=\"max-h-[360px] w-full rounded-lg bg-black\" aria-label={t(\"fieldIntel.videoPlayer\")} />\n"
    "        <button type=\"button\" onClick={() => setRecordedVideo(null)} className=\"mt-2 inline-flex items-center gap-1 rounded-lg border border-[#D6DDD0] px-3 py-2 text-[12px] font-semibold text-[#B23B2E]\"><Trash2 className=\"h-4 w-4\" />{t(\"fieldIntel.removeAttachment\")}</button>\n"
    "      </div>}\n"
    "      <button type=\"button\" disabled={recording} onClick={() => videoRecording ? void stopWalkVideo() : void startWalkVideo()}\n"
    "        className=\"mt-3 inline-flex min-h-[50px] w-full items-center justify-center gap-2 rounded-xl px-4 text-[14px] font-semibold text-white disabled:opacity-40\"\n"
    "        style={{ background: videoRecording ? \"#B23B2E\" : \"#1B5E3F\" }}>\n"
    "        {videoRecording ? <Square className=\"h-4 w-4 fill-current\" /> : <Video className=\"h-5 w-5\" />}\n"
    "        {videoRecording ? t(\"fieldIntel.stopWalkVideo\") : t(\"fieldIntel.startWalkVideo\")}\n"
    "      </button>\n"
    "      {audioUrl && !recording && <div className=\"mt-3 flex items-center gap-2 rounded-xl border border-[#D6DDD0] p-2\">\n",
)
replace_once(
    COMPONENT,
    "        if (recording) await stopRecording();\n        setReviewing(true);\n      }} disabled={!note.trim() && !audioFile && attachments.length === 0}\n",
    "        if (recording) await stopRecording();\n"
    "        if (videoRecording) await stopWalkVideo();\n"
    "        setReviewing(true);\n"
    "      }} disabled={!note.trim() && !audioFile && !walkVideoFile && attachments.length === 0}\n",
)

I18N = "figma-enterprise-v4/src/app/i18n.ts"
replace_once(
    I18N,
    '  "fieldIntel.recordingReady": "Recording ready",\n',
    '  "fieldIntel.recordingReady": "Recording ready",\n'
    '  "fieldIntel.startWalkVideo": "Start walk-and-talk video",\n'
    '  "fieldIntel.stopWalkVideo": "Stop walk video",\n'
    '  "fieldIntel.walkRecording": "Walk video recording",\n'
    '  "fieldIntel.videoUnsupported": "Walk-and-talk video is not supported on this device.",\n'
    '  "fieldIntel.videoDenied": "Camera or microphone permission was denied.",\n',
)
replace_once(
    I18N,
    '  "fieldIntel.recordingReady": "Prêt à enregistrer",\n',
    '  "fieldIntel.recordingReady": "Prêt à enregistrer",\n'
    '  "fieldIntel.startWalkVideo": "Démarrer la vidéo terrain avec commentaire",\n'
    '  "fieldIntel.stopWalkVideo": "Arrêter la vidéo terrain",\n'
    '  "fieldIntel.walkRecording": "Enregistrement vidéo terrain",\n'
    '  "fieldIntel.videoUnsupported": "La vidéo terrain avec commentaire n’est pas prise en charge sur cet appareil.",\n'
    '  "fieldIntel.videoDenied": "L’autorisation de la caméra ou du microphone a été refusée.",\n',
)

MULTI_TEST = "figma-enterprise-v4/tests/field-intelligence-multimodal-contract.mjs"
replace_once(
    MULTI_TEST,
    "assert.match(component, /capture=\"environment\"/);\n",
    "assert.match(component, /capture=\"environment\"/);\n"
    "assert.match(component, /startWalkVideo/);\n"
    "assert.match(component, /video:\\s*\\{\\s*facingMode/);\n"
    "assert.match(component, /video\\/webm;codecs=vp9,opus/);\n"
    "assert.match(component, /transcriptPreview/);\n",
)
replace_once(
    MULTI_TEST,
    "const routes = fs.readFileSync(path.join(root, \"src/app/routes.tsx\"), \"utf8\");\n",
    "const routes = fs.readFileSync(path.join(root, \"src/app/routes.tsx\"), \"utf8\");\n"
    "const queue = fs.readFileSync(path.join(root, \"src/app/fieldIntelligence/offlineQueue.ts\"), \"utf8\");\n",
)
replace_once(
    MULTI_TEST,
    "assert.match(component, /href=\"\\/intelligence\"/);\n",
    "assert.match(component, /href=\"\\/intelligence\"/);\n"
    "assert.match(queue, /transcript_preview/);\n"
    "assert.match(queue, /corrected_transcript: record\\.transcriptPreview/);\n",
)

BACKEND_TEST = r'''from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_field_intelligence_multimodal_v3_source_contract():
    extension = (ROOT / "app/services/field_intelligence_vision_extension.py").read_text()
    video = (ROOT / "app/services/field_video.py").read_text()
    vision = (ROOT / "app/services/field_vision.py").read_text()
    edge = (ROOT.parent / "cloudflare/edge-gateway/src/edge-main-v3.ts").read_text()

    assert "extract_video_audio" in extension
    assert "extract_video_frames" in extension
    assert "transcript_preview" in extension
    assert "_repair_text_inference" in extension
    assert "video_frame_count" in extension
    assert "subprocess.run" in video
    assert "shell=" not in video
    assert "visible_facts" in vision
    assert "hypotheses" in vision
    assert "pesticide concentration" in vision
    assert "@cf/meta/llama-3.2-11b-vision-instruct" in edge
    assert "degraded" in edge
'''
(ROOT / "agroai_api/tests/test_field_intelligence_multimodal_v3.py").write_text(BACKEND_TEST, encoding="utf-8")

print("Field Intelligence multimodal v3 patch applied")
