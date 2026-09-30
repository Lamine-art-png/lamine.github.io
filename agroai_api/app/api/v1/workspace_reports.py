"""Workspace reports that are real documents.

``POST /reports/generate`` builds an evidence-grounded report from the
workspace (the same engine as the Report Factory), stores it as a
``GeneratedArtifact`` and returns the preview. ``GET /artifacts/{id}/download``
serves the stored report as PDF or Markdown. An empty workspace produces a
report that says so; it never contains sample fields.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import GeneratedArtifact, IntelligenceRun
from app.models.saas import Organization
from app.services.commercial_control import require_feature

router = APIRouter(tags=["reports"])

REPORT_AUDIENCES = {
    "evidence_summary": "owner",
    "water_decision": "operator",
    "assurance_packet": "agency",
    "water_agency_packet": "agency",
    "lender_risk_packet": "lender",
    "farmer_summary": "grower",
}
ReportType = Literal["evidence_summary", "water_decision", "assurance_packet", "water_agency_packet", "lender_risk_packet", "farmer_summary"]


class ReportGenerateRequest(BaseModel):
    report_type: ReportType = "evidence_summary"
    format: Literal["pdf", "markdown"] = "pdf"
    workspace_id: str | None = None


def _organization(db: Session, tenant_id: str) -> Organization:
    org = db.get(Organization, tenant_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


def _label(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("title") or row.get("recommendation") or row.get("summary") or row.get("field_name") or row.get("label") or row.get("id") or "")
    return str(row)


def report_markdown(report: dict[str, Any]) -> str:
    lines = [f"# {report.get('title', 'AGRO-AI Report')}", "", f"Generated: {report.get('generated_at') or ''}", "", "## Executive summary", "", str(report.get("executive_summary") or "")]
    sections = [
        ("Key findings", report.get("key_findings")),
        ("Field summary", report.get("field_summary")),
        ("Exceptions", report.get("exceptions")),
        ("Decisions", report.get("decisions")),
        ("Missing evidence", report.get("missing_evidence")),
        ("Recommended next actions", report.get("recommended_next_actions")),
        ("Evidence appendix", report.get("evidence_appendix")),
    ]
    for heading, rows in sections:
        lines += ["", f"## {heading}", ""]
        items = [label for label in (_label(row) for row in rows or []) if label]
        lines += [f"- {item}" for item in items] or ["None listed."]
    return "\n".join(lines) + "\n"


def _public_artifact(row: GeneratedArtifact) -> dict[str, Any]:
    metadata = dict(row.metadata_json or {})
    metadata.pop("report", None)
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "title": row.title,
        "filename": row.filename,
        "artifact_type": row.artifact_type,
        "content_type": row.content_type,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "metadata_json": metadata,
    }


@router.post("/reports/generate")
def generate_report(payload: ReportGenerateRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.api.v1.operator_cockpit import _workspace
    from app.services.operator_cockpit import build_context, report_factory

    org = _organization(db, tenant_id)
    require_feature(db, org, "reports.generate", recommended_plan="professional")
    if payload.format == "pdf":
        require_feature(db, org, "reports.pdf_export", recommended_plan="professional")
    workspace = _workspace(db, org.id, payload.workspace_id)
    result = report_factory(build_context(db, org.id, workspace), report_type=payload.report_type, audience=REPORT_AUDIENCES[payload.report_type])
    report = json.loads(json.dumps(result["report"], default=str))
    sample_mode = bool(result.get("sample_mode"))
    markdown = report_markdown(report)
    run = IntelligenceRun(
        tenant_id=org.id, workspace_id=workspace.id if workspace else None, run_type="report_generate",
        question=payload.report_type, input_context_json=payload.model_dump(),
        output_json={"title": report["title"], "sample_mode": sample_mode}, citations_json=[], status="completed",
    )
    db.add(run)
    db.flush()
    extension, content_type = ("pdf", "application/pdf") if payload.format == "pdf" else ("md", "text/markdown")
    artifact = GeneratedArtifact(
        tenant_id=org.id, workspace_id=workspace.id if workspace else None, intelligence_run_id=run.id,
        artifact_type=payload.report_type, title=report["title"],
        filename=f"agro-ai-{payload.report_type.replace('_', '-')}-{datetime.utcnow():%Y%m%d-%H%M}.{extension}",
        content_type=content_type, body_text=markdown,
        metadata_json={"format": payload.format, "sample_mode": sample_mode, "audience": report.get("audience"), "report": report},
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return {"status": "generated", "sample_mode": sample_mode, "report": {"id": run.id, "title": report["title"]}, "artifact": _public_artifact(artifact), "preview": markdown}


@router.post("/reports/export")
def export_report(payload: ReportGenerateRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    return generate_report(payload, tenant_id, db)


@router.get("/reports")
def list_reports(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = (
        db.query(GeneratedArtifact)
        .filter(GeneratedArtifact.tenant_id == tenant_id, GeneratedArtifact.artifact_type.in_(list(REPORT_AUDIENCES)))
        .order_by(GeneratedArtifact.created_at.desc())
        .limit(50)
        .all()
    )
    return {"status": "ok", "reports": [_public_artifact(row) for row in rows]}


def _owned_artifact(db: Session, tenant_id: str, artifact_id: str) -> GeneratedArtifact:
    row = db.query(GeneratedArtifact).filter(GeneratedArtifact.id == artifact_id, GeneratedArtifact.tenant_id == tenant_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return row


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"status": "ok", "artifact": _public_artifact(_owned_artifact(db, tenant_id, artifact_id))}


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> Response:
    from app.api.v1.operator_cockpit import _factory_pdf_bytes

    row = _owned_artifact(db, tenant_id, artifact_id)
    report = (row.metadata_json or {}).get("report")
    if row.content_type == "application/pdf":
        if not isinstance(report, dict):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "artifact_content_unavailable", "message": "This artifact has no stored report content to render."})
        content, media_type = _factory_pdf_bytes(report), "application/pdf"
    elif row.body_text:
        content, media_type = row.body_text.encode("utf-8"), row.content_type or "text/plain"
    else:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "artifact_content_unavailable", "message": "This artifact has no stored content to download."})
    safe_name = "".join(ch for ch in row.filename if ch.isalnum() or ch in "-_.") or "agro-ai-report"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})
