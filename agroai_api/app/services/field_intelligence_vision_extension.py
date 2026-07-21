"""Install the multimodal Field Intelligence pipeline extension.

This module wraps the existing proven transcription/extraction/correlation
pipeline instead of forking it. Visual analysis runs only after the durable
pipeline succeeds, so a vision-provider outage never loses a voice observation.
"""
from __future__ import annotations

from typing import Any

from app.models.field_intelligence import FieldCaptureSession, FieldObservation, FieldObservationAsset
from app.services.field_vision import MAX_IMAGE_BYTES, analyze_field_images

_INSTALLED = False
_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def install_field_vision_extension(svc: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(svc, "_field_vision_extension_installed", False):
        return

    original = svc._process_observation

    def process_with_vision(db, job, *, heartbeat=None):
        original(db, job, heartbeat=heartbeat)

        job_input = job.input_json or {}
        observation = db.get(FieldObservation, job_input.get("observation_id"))
        if observation is None or observation.status == "deleted":
            return

        photos = (
            db.query(FieldObservationAsset)
            .filter(FieldObservationAsset.tenant_id == observation.tenant_id)
            .filter(FieldObservationAsset.observation_id == observation.id)
            .filter(FieldObservationAsset.kind == "photo")
            .filter(FieldObservationAsset.status == "stored")
            .order_by(FieldObservationAsset.created_at.asc())
            .limit(4)
            .all()
        )
        if not photos:
            return

        if heartbeat is not None:
            heartbeat.check()

        images: list[tuple[bytes, str | None]] = []
        asset_ids: list[str] = []
        read_errors: list[str] = []
        store = svc._object_store()
        for asset in photos:
            if not asset.object_ref or not observation.capture_session_id:
                continue
            try:
                payload = store.read_bytes(
                    asset.object_ref,
                    max_bytes=MAX_IMAGE_BYTES,
                    tenant_id=observation.tenant_id,
                    connection_id=observation.capture_session_id,
                )
                images.append((payload, asset.content_type))
                asset_ids.append(asset.id)
            except Exception as exc:  # noqa: BLE001 - one bad image must not discard the capture
                read_errors.append(exc.__class__.__name__)

        session = db.get(FieldCaptureSession, observation.capture_session_id)
        result = analyze_field_images(
            images,
            {
                "field_name": observation.field_name,
                "crop": observation.crop,
                "note_text": (
                    observation.corrected_transcript
                    or observation.transcript
                    or (session.note_text if session else None)
                    or ""
                ),
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
                "images_analyzed": int(result.analysis.get("images_analyzed") or 0),
                "confidence": result.analysis.get("confidence"),
                "read_errors": read_errors,
                "human_review_required": True,
            },
        )

        provenance = dict(observation.provenance_json or {})
        provenance.update(
            {
                "vision_provider": result.provider,
                "vision_model": result.model,
                "vision_status": result.status,
                "vision_images_analyzed": int(result.analysis.get("images_analyzed") or 0),
                "vision_human_review_required": True,
            }
        )
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
            observation.confidence = max(float(observation.confidence or 0.0), min(visual_confidence * 0.8, 0.8))

            uncertainties = list(observation.uncertain_fields_json or [])
            for item in ("visual_analysis_requires_human_confirmation", *list(result.analysis.get("uncertainties") or [])):
                text = str(item).strip()[:300]
                if text and text not in uncertainties:
                    uncertainties.append(text)
            observation.uncertain_fields_json = uncertainties[:30]

            if visual_severity in {"medium", "high", "critical"} and (not observation.event_type or observation.event_type == "observation"):
                observation.event_type = "issue"

            visual_search = " ".join(
                [
                    summary,
                    " ".join(result.analysis.get("observations") or []),
                    " ".join(result.analysis.get("possible_issues") or []),
                    follow_up,
                ]
            ).strip()
            if visual_search:
                observation.search_text = f"{observation.search_text or ''} {visual_search}".strip()[:12000]

            # Visual-only captures must become reviewable evidence rather than
            # remaining unusable merely because no spoken or typed text exists.
            evidence = svc._find_evidence_slow(db, observation)
            if evidence is not None:
                confirmed_context = (
                    observation.corrected_transcript
                    or observation.transcript
                    or (session.note_text if session else None)
                    or summary
                    or visual_search
                )
                svc._apply_evidence_fields(
                    evidence,
                    observation,
                    source_text=confirmed_context or "Visual field evidence",
                    transcription_ok=bool(observation.corrected_transcript or observation.transcript),
                )

            issue_count = len(result.analysis.get("possible_issues") or [])
            if issue_count or _SEVERITY_ORDER.get(visual_severity, 0) >= _SEVERITY_ORDER["medium"] or visual_confidence < 0.7:
                observation.status = "needs_review"

            svc._audit(
                observation,
                "vision_analysis_completed",
                actor="system",
                details={
                    "provider": result.provider,
                    "model": result.model,
                    "asset_ids": asset_ids,
                    "images_analyzed": int(result.analysis.get("images_analyzed") or 0),
                    "human_review_required": True,
                },
            )
        else:
            if result.retryable:
                observation.status = "processing"
                raise RuntimeError(f"vision_retryable_failure:{result.error or 'provider'}")
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
                },
            )

        if heartbeat is not None:
            heartbeat.check()
        db.flush()

    svc._process_observation = process_with_vision
    svc._field_vision_extension_installed = True
    _INSTALLED = True
