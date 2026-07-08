"""Tenant-safe, commercially scoped intelligence context builder for AGRO-AI routes."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.api.deps import require_workspace_access
from app.models.saas import Organization, User, Workspace
from app.schemas.ai import EvidenceContext, ToolCitation
from app.services.commercial_billing_lifecycle import install_commercial_billing_lifecycle
from app.services.commercial_control import require_feature
from app.services.intelligence_policy import PROFILE_BASE
from app.services.operator_cockpit import build_context, decision_workbench, exceptions, field_intelligence, readiness_summary, report_factory
from app.services.source_content import parsed_rows_preview, source_content_excerpt


# Main imports billing before Brain/intelligence context and includes chat artifacts
# afterward. Install these boundaries here so the already-loaded billing module is
# hardened and the report router is guarded before FastAPI copies its routes.
install_commercial_billing_lifecycle()
from app.api.v1.commercial_route_guards import install_report_commercial_guards  # noqa: E402
install_report_commercial_guards()


SECRET_HINTS = ("secret", "token", "password", "api_key", "apikey", "oauth_code", "credential", "private_key")
MAX_SOURCE_TEXT_CONTEXT_CHARS = 24_000
PER_SOURCE_TEXT_CHARS = 4_000
PER_EVIDENCE_EXCERPT_CHARS = 2_000


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if any(hint in key.lower() for hint in SECRET_HINTS):
                continue
            clean[key] = _redact(item)
        return clean
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _tool_citations(ctx: Any, workspace_id: str | None, max_items: int) -> list[ToolCitation]:
    citations: list[ToolCitation] = []
    for record in ctx.evidence[:max_items]:
        citations.append(
            ToolCitation(
                source_type=record.evidence_type,
                source_id=record.id,
                title=record.title,
                tenant_id=ctx.organization_id,
                workspace_id=workspace_id or record.workspace_id,
                fields=["title", "summary", "evidence_type", "occurred_at"],
                trace={"citation_label": record.citation_label, "data_source_id": record.data_source_id},
            )
        )
    return citations


def _source_rows(ctx: Any, source_limit: int) -> tuple[list[dict[str, Any]], list[ToolCitation]]:
    remaining = MAX_SOURCE_TEXT_CONTEXT_CHARS
    rows: list[dict[str, Any]] = []
    citations: list[ToolCitation] = []

    for source in ctx.sources[:source_limit]:
        excerpt_limit = min(PER_SOURCE_TEXT_CHARS, max(0, remaining))
        excerpt = source_content_excerpt(source, max_chars=excerpt_limit) if excerpt_limit else ""
        remaining -= len(excerpt)
        preview = _redact(parsed_rows_preview(source, limit=12))
        rows.append(
            {
                "id": source.id,
                "provider": source.provider,
                "source_type": source.source_type,
                "filename": source.filename,
                "status": source.status,
                "content_excerpt": excerpt,
                "parsed_rows_preview": preview,
                "metadata_json": _redact(source.metadata_json or {}),
            }
        )
        if source.filename:
            citations.append(
                ToolCitation(
                    source_type=f"data_source:{source.source_type}",
                    source_id=source.id,
                    title=source.filename,
                    tenant_id=ctx.organization_id,
                    workspace_id=ctx.workspace_id or source.workspace_id,
                    fields=["filename", "source_type", "content_excerpt", "parsed_rows_preview"],
                    trace={"provider": source.provider, "status": source.status},
                )
            )
    return rows, citations


def build_intelligence_context(
    *,
    db: Session,
    tenant_id: str,
    user: User | None = None,
    workspace_id: str | None = None,
    field_id: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    org = db.query(Organization).filter(Organization.id == tenant_id).first()
    if org is None:
        raise ValueError("Organization not found")
    effective = require_feature(db, org, "intelligence.ask")
    commercial_profile = str(effective.value("intelligence.profile", "essential"))
    profile_policy = PROFILE_BASE.get(commercial_profile, PROFILE_BASE["essential"])
    source_limit = max(1, int(profile_policy["max_sources"]))

    workspace: Workspace | None = None
    if workspace_id and user is not None:
        workspace, _membership = require_workspace_access(workspace_id, user, db)
        if workspace.organization_id != tenant_id:
            raise ValueError("Workspace tenant mismatch")
    elif workspace_id:
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.organization_id == tenant_id).first()
        if workspace is None:
            raise ValueError("Workspace not found")

    cockpit = build_context(db, tenant_id, workspace)
    readiness = readiness_summary(cockpit)
    fields = field_intelligence(cockpit)
    exception_rows = exceptions(cockpit)
    decisions = decision_workbench(cockpit, field_id=field_id)
    reports = report_factory(cockpit, report_type="executive_brief", audience=audience, field_id=field_id)
    evidence_summary = {
        "sample_mode": bool(readiness.get("sample_mode")),
        "evidence_count": int(readiness.get("evidence_records") or 0),
        "source_count": int(readiness.get("data_sources") or 0),
        "readiness_score": int(readiness.get("readiness_score") or 0),
        "readiness_level": readiness.get("readiness_level"),
        "connected_sources": int(readiness.get("connected_sources") or 0),
        "present_source_types": readiness.get("present_source_types") or [],
        "missing_source_types": readiness.get("missing_source_types") or [],
    }

    data_sources, source_citations = _source_rows(cockpit, source_limit)
    evidence_rows = [
        {
            "id": row.id,
            "data_source_id": row.data_source_id,
            "type": row.evidence_type,
            "title": row.title,
            "summary": row.summary,
            "source_excerpt": str(row.source_excerpt or "")[:PER_EVIDENCE_EXCERPT_CHARS],
            "value_json": _redact(row.value_json or {}),
            "field_id": row.field_id,
            "block_id": row.block_id,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "metadata_json": _redact(row.metadata_json or {}),
        }
        for row in cockpit.evidence[:source_limit]
    ]

    citations = _tool_citations(cockpit, workspace.id if workspace else workspace_id, source_limit) + source_citations
    evidence_context = EvidenceContext(
        organization_id=tenant_id,
        workspace_id=workspace.id if workspace else workspace_id,
        block_id=field_id,
        crop_type=workspace.crop if workspace else None,
        region=workspace.region if workspace else None,
        evidence=[
            {"type": "readiness_summary", "payload": _redact(readiness)},
            {"type": "field_intelligence", "payload": _redact(fields)},
            {"type": "exceptions", "payload": _redact(exception_rows)},
            {"type": "decision_workbench", "payload": _redact(decisions)},
            {"type": "report_factory", "payload": _redact(reports)},
        ]
        + evidence_rows
        + data_sources,
        missing_data=list(
            dict.fromkeys(
                item
                for item in (readiness.get("missing_source_types") or [])
                + [item.get("recommended_action") for item in exception_rows.get("exceptions", []) if item.get("severity") in {"critical", "high"}]
                if item
            )
        ),
        citations=citations,
    )

    return {
        "workspace": {
            "id": workspace.id if workspace else workspace_id,
            "name": workspace.name if workspace else None,
            "crop": workspace.crop if workspace else None,
            "region": workspace.region if workspace else None,
            "mode": workspace.mode if workspace else None,
        },
        "readiness": _redact(readiness),
        "fields": _redact(fields),
        "exceptions": _redact(exception_rows),
        "decisions": _redact(decisions),
        "reports": _redact(reports),
        "sample_mode": evidence_summary["sample_mode"],
        "evidence_summary": evidence_summary,
        "evidence_context": evidence_context,
        "citations": citations,
        "commercial_intelligence": {
            "profile": commercial_profile,
            "max_sources": source_limit,
            "cross_workspace_scope": bool(profile_policy["cross_workspace_scope"]),
            "portfolio_scope": bool(profile_policy["portfolio_scope"]),
        },
    }
