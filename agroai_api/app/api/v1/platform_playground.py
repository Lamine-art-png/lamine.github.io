from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import get_db
from app.models.platform_api import ApiProject
from app.platform_api.deps import require_developer_control_plane
from app.platform_api.product_audit import record_product_audit
from app.platform_api.sandbox import ensure_sandbox_state, sandbox_dataset


router = APIRouter(tags=["platform-playground"])

PlaygroundOperation = Literal[
    "sandbox_summary",
    "list_fields",
    "get_field",
    "list_observations",
    "list_recommendations",
    "list_reports",
    "list_jobs",
]


class PlaygroundExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=128)
    operation: PlaygroundOperation
    resource_id: str | None = Field(default=None, max_length=200)


_OPERATION_CONTRACTS: dict[str, dict[str, Any]] = {
    "sandbox_summary": {
        "method": "GET",
        "path": "/v1/platform/sandbox",
        "scope": "projects:read",
        "description": "Inspect the deterministic synthetic dataset attached to the selected test project.",
    },
    "list_fields": {
        "method": "GET",
        "path": "/v1/platform/fields",
        "scope": "fields:read",
        "description": "List synthetic fields using the same public response shape as a test API key.",
    },
    "get_field": {
        "method": "GET",
        "path": "/v1/platform/fields/{field_id}",
        "scope": "fields:read",
        "description": "Retrieve one synthetic field from the selected test project.",
    },
    "list_observations": {
        "method": "GET",
        "path": "/v1/platform/observations",
        "scope": "observations:read",
        "description": "List deterministic synthetic observations and their provenance markers.",
    },
    "list_recommendations": {
        "method": "GET",
        "path": "/v1/platform/recommendations",
        "scope": "recommendations:read",
        "description": "Inspect advisory-only synthetic recommendations. Physical execution stays disabled.",
    },
    "list_reports": {
        "method": "GET",
        "path": "/v1/platform/reports",
        "scope": "reports:read",
        "description": "List synthetic report artifacts for the selected project.",
    },
    "list_jobs": {
        "method": "GET",
        "path": "/v1/platform/jobs",
        "scope": "jobs:read",
        "description": "List deterministic ingestion jobs for the selected project.",
    },
}


def _project(db: Session, *, organization_id: str, project_id: str) -> ApiProject:
    project = (
        db.query(ApiProject)
        .filter(
            ApiProject.id == project_id,
            ApiProject.organization_id == organization_id,
            ApiProject.status == "active",
        )
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "api_project_not_found"})
    if project.environment != "test":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "playground_test_project_required",
                "message": "The browser Playground is available only for test projects.",
            },
        )
    return project


def _page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": items, "next_cursor": None, "has_more": False, "synthetic": True}


def _execute(operation: PlaygroundOperation, dataset: dict[str, Any], resource_id: str | None) -> tuple[str, dict[str, Any]]:
    if operation == "sandbox_summary":
        return "/v1/platform/sandbox", {
            "fixture_version": dataset["fixture_version"],
            "organization": dataset["organization"],
            "farm": dataset["farm"],
            "counts": {
                "fields": len(dataset["fields"]),
                "observations": len(dataset["observations"]),
                "recommendations": len(dataset["recommendations"]),
                "reports": len(dataset["reports"]),
                "jobs": len(dataset["ingestion_jobs"]),
            },
            "synthetic": True,
            "physical_execution": False,
            "provider_credentials": False,
        }
    if operation == "list_fields":
        return "/v1/platform/fields", _page(list(dataset["fields"]))
    if operation == "get_field":
        selected = resource_id or str(dataset["fields"][0]["id"])
        field = next((item for item in dataset["fields"] if str(item["id"]) == selected), None)
        if field is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "sandbox_field_not_found"})
        return f"/v1/platform/fields/{selected}", {"field": field}
    if operation == "list_observations":
        return "/v1/platform/observations", _page(list(dataset["observations"]))
    if operation == "list_recommendations":
        return "/v1/platform/recommendations", _page(list(dataset["recommendations"]))
    if operation == "list_reports":
        return "/v1/platform/reports", _page(list(dataset["reports"]))
    if operation == "list_jobs":
        return "/v1/platform/jobs", _page(list(dataset["ingestion_jobs"]))
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "unsupported_playground_operation"})


def _snippets(path: str) -> dict[str, str]:
    url = f"https://api.agroai-pilot.com{path}"
    return {
        "curl": f'curl "{url}" \\\n  -H "Authorization: Bearer $AGROAI_API_KEY"',
        "python": (
            "import os, requests\n\n"
            f'response = requests.get("{url}", headers={{"Authorization": f"Bearer {{os.environ[\'AGROAI_API_KEY\']}}"}}, timeout=30)\n'
            "response.raise_for_status()\n"
            "print(response.json())"
        ),
        "typescript": (
            f'const response = await fetch("{url}", {{\n'
            "  headers: { Authorization: `Bearer ${process.env.AGROAI_API_KEY}` },\n"
            "});\n"
            "if (!response.ok) throw new Error(`AGRO-AI ${response.status}`);\n"
            "console.log(await response.json());"
        ),
    }


@router.get("/platform/developer/playground/operations")
def playground_operations(ctx=Depends(require_developer_control_plane)) -> dict[str, Any]:
    return {
        "operations": [
            {"id": key, **value}
            for key, value in _OPERATION_CONTRACTS.items()
        ],
        "execution_mode": "portal_session_synthetic",
        "permanent_api_key_in_browser": False,
        "live_projects_allowed": False,
        "physical_execution": False,
    }


@router.post("/platform/developer/playground/execute")
def execute_playground(
    payload: PlaygroundExecuteRequest,
    request: Request,
    ctx=Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not bool(getattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", False)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    started = time.perf_counter()
    project = _project(db, organization_id=ctx.organization.id, project_id=payload.project_id)
    ensure_sandbox_state(db, project)
    dataset = sandbox_dataset(project)
    path, response_body = _execute(payload.operation, dataset, payload.resource_id)
    request_id = str(getattr(request.state, "request_id", "") or uuid.uuid4())
    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))

    record_product_audit(
        db,
        event_type="platform.playground.executed",
        subject_type="api_project",
        subject_id=project.id,
        organization_id=ctx.organization.id,
        actor_user_id=ctx.user.id,
        metadata={
            "operation": payload.operation,
            "execution_mode": "portal_session_synthetic",
            "synthetic": True,
            "physical_execution": False,
        },
        request_id=request_id,
    )
    db.commit()

    contract = _OPERATION_CONTRACTS[payload.operation]
    return {
        "request_id": request_id,
        "project_id": project.id,
        "environment": "test",
        "execution_mode": "portal_session_synthetic",
        "synthetic": True,
        "physical_execution": False,
        "provider_credentials": False,
        "latency_ms": elapsed_ms,
        "credit_cost": 0,
        "request": {
            "method": contract["method"],
            "path": path,
            "required_scope": contract["scope"],
        },
        "response": {"status": 200, "body": response_body},
        "code": _snippets(path),
    }
