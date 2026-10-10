"""Install the multimodal Field Intelligence pipeline extension.

The extension preserves the durable voice pipeline, adds walk-and-talk video
transcription and representative-frame analysis, repairs inference precedence,
and keeps every visual conclusion explicitly reviewable.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.models.field_intelligence import FieldCaptureSession, FieldObservation, FieldObservationAsset
from app.services.crop_profiles import resolve_profile
from app.services.decision_fabric import assess_field_observation, field_requires_review, safe_field_follow_up
from app.services.detection_tracking import summarize_counts
from app.services.field_detection import (
    DETECTION_CONTRACT_VERSION, DisabledDetectionProvider, FrameRef, detection_enabled, get_detection_provider,
)
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


_MAX_STORED_DETECTION_FRAMES = 8


def _run_detection(svc: Any, db: Any, observation: FieldObservation, media_inputs: list[tuple], vision_analysis: dict, attempt: int) -> None:
    """Specialized detection lane; runs only when FIELD_DETECTION_ENABLED is set.

    Results are added as reviewable evidence (``structured["detections"]``)
    and never change severity or status on their own. Frames the general
    vision layer judged poor are excluded from counts.
    """
    provenance = dict(observation.provenance_json or {})
    profile = resolve_profile(observation.crop)
    provider = get_detection_provider()
    if isinstance(provider, DisabledDetectionProvider) or profile is None:
        provenance["detection_status"] = "not_run"
        provenance["detection_reason"] = provider.reason if isinstance(provider, DisabledDetectionProvider) else "crop_profile_not_supported"
        observation.provenance_json = provenance
        return

    frame_indexes: dict[str | None, int] = {}
    results = []
    for payload, content_type, context in media_inputs:
        asset_id = context.get("asset_id")
        index = frame_indexes.get(asset_id, 0)
        frame_indexes[asset_id] = index + 1
        frame = FrameRef(
            asset_id=asset_id, media_kind=context.get("media_kind"),
            frame_timestamp_seconds=context.get("frame_timestamp_seconds"), frame_index=index,
        )
        results.append(provider.detect(payload, content_type, profile, frame))

    poor = {
        (moment.get("asset_id"), moment.get("frame_timestamp_seconds"))
        for moment in vision_analysis.get("media_moments") or []
        if moment.get("image_quality") == "poor"
    }
    counts = summarize_counts(results, excluded_frames=poor)
    statuses = sorted({result.status for result in results})
    ok = [result for result in results if result.status == "ok"]
    models = sorted({f"{result.model_id}@{result.model_version or 'unversioned'}" for result in ok if result.model_id})
    structured = dict(observation.structured_json or {})
    structured["detections"] = {
        "contract_version": DETECTION_CONTRACT_VERSION,
        "crop_profile": profile.to_dict(),
        "provider": provider.name,
        "models": models,
        "statuses": statuses,
        "frames": [result.to_dict() for result in results[:_MAX_STORED_DETECTION_FRAMES]],
        "counts": counts,
        "review_status": "unreviewed",
        "validation_status": profile.validation_status,
        "human_review_required": True,
    }
    observation.structured_json = structured
    provenance.update({"detection_status": "completed" if ok else "failed", "detection_models": models})
    observation.provenance_json = provenance
    svc._record_run(
        db, observation, stage="detection", provider=provider.name,
        stage_status="completed" if ok else "failed",
        model=models[0] if models else None, language=None,
        latency_ms=sum(result.latency_ms or 0 for result in results) or None,
        error=";".join(sorted({result.error for result in results if result.error}))[:500] or None,
        attempt_count=attempt,
        output={"frames": len(results), "frames_ok": len(ok), "labels": counts.get("labels", []), "totals": counts.get("totals", [])},
    )


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
        output_language = str(job_input.get("language") or "en").strip()[:16] or "en"
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
        # The original text pipeline may already have mirrored evidence before
        # the extension repairs provider/model provenance. Refresh immediately so
        # text-only captures and transcript corrections remain audit-consistent.
        svc._refresh_linked_evidence(db, observation)

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
            # The failure provenance is also part of the evidence audit trail.
            svc._refresh_linked_evidence(db, observation)
            db.flush()
            return

        result = analyze_field_images(
            media_inputs,
            {
                "field_name": observation.field_name,
                "crop": observation.crop,
                "note_text": _source_text(observation, session),
                "language": output_language,
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
            language=output_language,
            latency_ms=result.latency_ms,
            error=result.error,
            attempt_count=int(job.attempt_count or 1),
            output={
                "asset_ids": asset_ids,
                "media_items_analyzed": int(result.analysis.get("images_analyzed") or 0),
                "media_items_degraded": int(result.analysis.get("images_degraded") or 0),
                "video_frames_analyzed": video_frame_count,
                "analysis_state": result.analysis.get("analysis_state"),
                "confidence": result.analysis.get("confidence"),
                "confidence_kind": result.analysis.get("confidence_kind"),
                "severity": result.analysis.get("severity"),
                "peak_severity": result.analysis.get("peak_severity"),
                "contract_violations": list(result.analysis.get("contract_violations") or []),
                "safety_flags": list(result.analysis.get("safety_flags") or []),
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
            "vision_language": output_language,
            "vision_analysis_state": result.analysis.get("analysis_state") if result.succeeded else None,
            "vision_confidence_kind": result.analysis.get("confidence_kind") if result.succeeded else None,
            "vision_contract_version": result.analysis.get("contract_version") if result.succeeded else None,
        })
        observation.provenance_json = provenance

        if result.succeeded:
            structured = dict(observation.structured_json or {})
            structured["vision"] = result.analysis
            observation.structured_json = structured
            degraded = result.analysis.get("analysis_state") == "degraded"

            summary = str(result.analysis.get("summary") or "").strip()
            if summary:
                # Unstructured provider prose is kept for the reviewer but is
                # labelled as unverified and never replaces the operator's words.
                label = "Unverified visual note" if degraded else "Visual evidence"
                if not (observation.summary or "").strip() and not degraded:
                    observation.summary = summary
                elif summary.lower() not in str(observation.summary or "").lower():
                    observation.summary = f"{observation.summary or ''} {label}: {summary}".strip()[:4000]

            follow_up = str(result.analysis.get("recommended_follow_up") or "").strip()
            if follow_up and not degraded and not (observation.recommended_action or "").strip():
                observation.recommended_action = follow_up

            # ``severity`` is corroborated across frames; an isolated spike is
            # reported as ``peak_severity`` and routed to review, not escalated.
            visual_severity = "info" if degraded else str(result.analysis.get("severity") or "info").lower()
            current_severity = str(observation.severity or "info").lower()
            if _SEVERITY_ORDER.get(visual_severity, 0) > _SEVERITY_ORDER.get(current_severity, 0):
                observation.severity = visual_severity
            peak_severity = str(result.analysis.get("peak_severity") or visual_severity).lower()
            uncorroborated_peak = _SEVERITY_ORDER.get(peak_severity, 0) > _SEVERITY_ORDER.get(visual_severity, 0)

            # Self-reported model confidence is uncalibrated: unknown stays
            # unknown and never raises the observation's confidence.
            visual_confidence = result.analysis.get("confidence")
            if not degraded and isinstance(visual_confidence, (int, float)) and not isinstance(visual_confidence, bool):
                bounded = max(0.0, min(float(visual_confidence), 1.0))
                observation.confidence = max(float(observation.confidence or 0.0), min(bounded * 0.85, 0.85))

            uncertainties = list(observation.uncertain_fields_json or [])
            review_markers = ["visual_analysis_requires_human_confirmation"]
            if degraded:
                review_markers.append("visual_analysis_unstructured_unverified")
            if uncorroborated_peak:
                review_markers.append("visual_severity_uncorroborated_single_frame")
            if result.analysis.get("safety_flags"):
                review_markers.append("visual_unsupported_measurement_removed")
            for item in (
                *review_markers,
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
            if degraded or uncorroborated_peak:
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
                    "media_degraded": int(result.analysis.get("images_degraded") or 0),
                    "video_frames_analyzed": video_frame_count,
                    "analysis_state": result.analysis.get("analysis_state"),
                    "severity": visual_severity,
                    "peak_severity": peak_severity,
                    "safety_flags": list(result.analysis.get("safety_flags") or []),
                    "human_review_required": True,
                },
            )
        else:
            if result.retryable:
                observation.status = "processing"
                raise RuntimeError(f"vision_retryable_failure:{result.error or 'provider'}")
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

        if detection_enabled():
            _run_detection(
                svc, db, observation, media_inputs,
                result.analysis if result.succeeded else {}, int(job.attempt_count or 1),
            )

        correlation = svc.correlate_observation(db, observation)
        observation.correlation_json = correlation
        observation.evidence_ids_json = list(dict.fromkeys([
            *(observation.evidence_ids_json or []),
            *list(correlation.get("relevant_evidence_ids", [])),
        ]))
        if not observation.recommended_action:
            observation.recommended_action = correlation.get("recommended_next_action")

        # Re-evaluate routing after visual evidence has been fused. The base
        # pipeline may have routed the text/audio state already; this second,
        # provider-hidden pass is the multimodal decision point and can only
        # increase caution.
        multimodal_advisory = assess_field_observation(
            confidence=observation.confidence,
            uncertain_count=len(observation.uncertain_fields_json or []),
            evidence_count=len(observation.evidence_ids_json or []),
            severity=observation.severity,
            has_text=bool(_source_text(observation, session).strip()) or bool(result.succeeded),
            has_recommended_action=bool((observation.recommended_action or "").strip()),
            has_correlation=bool(correlation),
        )
        if field_requires_review(multimodal_advisory):
            observation.status = "needs_review"
        if not (observation.recommended_action or "").strip():
            conservative_follow_up = safe_field_follow_up(multimodal_advisory)
            if conservative_follow_up:
                observation.recommended_action = conservative_follow_up
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
