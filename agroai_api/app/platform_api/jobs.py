"""Queue worker implementation for logical Platform API jobs."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.operational_records import EvidenceRecord, GeneratedArtifact, IngestionJob, IntelligenceRun


PLATFORM_OPERATION_TASK_TYPE = "platform_api_operation"


def process_platform_operation_job(
    db: Session,
    *,
    job_id: str,
    organization_id: str,
    worker_id: str,
) -> str:
    job = (
        db.query(IngestionJob)
        .filter(IngestionJob.id == job_id, IngestionJob.tenant_id == organization_id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        return "succeeded"
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status
    if job.job_type not in {"platform_observation_ingestion", "platform_recommendation", "platform_report"}:
        raise ValueError("unsupported Platform API job type")
    job.status = "running"
    job.worker_id = worker_id
    job.lease_expires_at = None
    job.last_heartbeat_at = datetime.utcnow()
    job.attempt_count = int(job.attempt_count or 0) + 1
    db.flush()
    try:
        payload = dict(job.input_json or {})
        if job.job_type == "platform_observation_ingestion":
            ids = []
            for item in payload.get("observations") or []:
                row = EvidenceRecord(
                    tenant_id=organization_id,
                    workspace_id=job.workspace_id,
                    data_source_id=job.data_source_id,
                    evidence_type=str(item["type"]),
                    field_id=item.get("field_id"),
                    occurred_at=datetime.fromisoformat(str(item["occurred_at"]).replace("Z", "+00:00")).replace(tzinfo=None),
                    title=str(item.get("title") or item["type"])[:255],
                    summary=str(item.get("summary") or "Platform API observation")[:2000],
                    value_json={"value": item.get("value")},
                    units=item.get("unit"),
                    confidence=float(item.get("confidence", 1.0)),
                    quality_status="usable",
                    citation_label="Platform API ingestion",
                    metadata_json={
                        "platform_api_project_id": payload.get("api_project_id"),
                        "synthetic": bool(payload.get("synthetic")),
                        "provenance": item.get("provenance") or {},
                        "quality_flags": item.get("quality_flags") or [],
                    },
                )
                db.add(row)
                db.flush()
                ids.append(row.id)
            job.output_json = {"observation_ids": ids, "records_processed": len(ids)}
        elif job.job_type == "platform_recommendation":
            run = IntelligenceRun(
                tenant_id=organization_id,
                workspace_id=job.workspace_id,
                run_type="platform_recommendation",
                input_context_json=payload,
                output_json={
                    "summary": "Recommendation computation completed.",
                    "physical_execution_enabled": False,
                },
                citations_json=list(payload.get("evidence_ids") or []),
                provenance_json={"source": "platform_api", "job_id": job.id},
                freshness_json={},
                status="completed",
            )
            db.add(run)
            db.flush()
            job.output_json = {"recommendation_id": run.id}
        else:
            run = IntelligenceRun(
                tenant_id=organization_id,
                workspace_id=job.workspace_id,
                run_type="platform_report",
                input_context_json=payload,
                output_json={"status": "completed"},
                citations_json=list(payload.get("evidence_ids") or []),
                provenance_json={"source": "platform_api", "job_id": job.id},
                freshness_json={},
                status="completed",
            )
            db.add(run)
            db.flush()
            artifact = GeneratedArtifact(
                tenant_id=organization_id,
                workspace_id=job.workspace_id,
                intelligence_run_id=run.id,
                artifact_type="platform_report",
                title=str(payload.get("title") or "AGRO-AI API Report")[:255],
                filename=f"platform-report-{uuid.uuid4().hex[:12]}.txt",
                content_type="text/plain",
                body_text="Customer-safe AGRO-AI Platform API report. Physical irrigation execution is disabled.",
                metadata_json={
                    "platform_api_project_id": payload.get("api_project_id"),
                    "synthetic": bool(payload.get("synthetic")),
                },
            )
            db.add(artifact)
            db.flush()
            job.output_json = {"report_id": artifact.id}
        job.status = "succeeded"
        job.completed_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        db.commit()
        return "succeeded"
    except Exception as exc:
        db.rollback()
        job = db.get(IngestionJob, job_id)
        if job is not None:
            job.status = "failed" if int(job.attempt_count or 0) >= int(job.max_attempts or 5) else "retrying"
            job.error = exc.__class__.__name__
            job.updated_at = datetime.utcnow()
            db.commit()
            return job.status
        raise
