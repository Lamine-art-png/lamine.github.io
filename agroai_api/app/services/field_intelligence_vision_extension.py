"""Install the multimodal Field Intelligence pipeline extension.

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
