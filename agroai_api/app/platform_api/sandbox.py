"""Deterministic, project-scoped synthetic sandbox fixtures."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.platform_api import ApiProject
from app.models.platform_product import PlatformSandboxState


FIXTURE_VERSION = "2026-07-sandbox-v1"
SYNTHETIC_MARKER = {"synthetic": True, "physical_execution": False, "provider_credentials": False}


def _identifier(project_id: str, kind: str, index: int = 0) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"agroai-sandbox:{FIXTURE_VERSION}:{project_id}:{kind}:{index}"))


def ensure_sandbox_state(db: Session, project: ApiProject) -> PlatformSandboxState:
    if project.environment != "test":
        raise ValueError("sandbox fixtures are available only for test projects")
    row = db.query(PlatformSandboxState).filter(PlatformSandboxState.api_project_id == project.id).first()
    if row is None:
        row = PlatformSandboxState(
            organization_id=project.organization_id,
            api_project_id=project.id,
            fixture_version=FIXTURE_VERSION,
            reset_counter=0,
            seed=hashlib.sha256(f"{FIXTURE_VERSION}:{project.id}".encode()).hexdigest(),
        )
        db.add(row)
        db.flush()
    return row


def sandbox_dataset(project: ApiProject) -> dict:
    base = datetime(2026, 7, 1, 12, 0, 0)
    farm_id = _identifier(project.id, "farm")
    field_ids = [_identifier(project.id, "field", index) for index in range(2)]
    zone_ids = [_identifier(project.id, "zone", index) for index in range(3)]
    source_id = _identifier(project.id, "source")
    observations = [
        {
            "id": _identifier(project.id, "observation", index),
            "field_id": field_ids[index % 2],
            "type": "soil_moisture" if index % 2 == 0 else "weather",
            "occurred_at": (base + timedelta(hours=index * 6)).isoformat() + "Z",
            "value": 0.24 + (index * 0.01) if index % 2 == 0 else 29 + index,
            "unit": "m3/m3" if index % 2 == 0 else "celsius",
            "provenance": {"source_id": source_id, "fixture_version": FIXTURE_VERSION},
            "quality_flags": [],
            **SYNTHETIC_MARKER,
        }
        for index in range(8)
    ]
    recommendation_id = _identifier(project.id, "recommendation")
    report_id = _identifier(project.id, "report")
    job_id = _identifier(project.id, "job")
    webhook_event_id = _identifier(project.id, "webhook")
    return {
        "fixture_version": FIXTURE_VERSION,
        "organization": {"id": project.organization_id, "name": "Synthetic AGRO-AI Sandbox Organization", **SYNTHETIC_MARKER},
        "farm": {"id": farm_id, "name": "Synthetic North Farm", "region": "California", **SYNTHETIC_MARKER},
        "fields": [
            {
                "id": field_ids[0],
                "farm_id": farm_id,
                "name": "Synthetic Almond Block A",
                "area_hectares": 24.6,
                "crop": "almond",
                "season": "2026",
                "boundary": {"type": "Polygon", "coordinates": [[[-120.1, 36.9], [-120.09, 36.9], [-120.09, 36.91], [-120.1, 36.91], [-120.1, 36.9]]]},
                **SYNTHETIC_MARKER,
            },
            {
                "id": field_ids[1],
                "farm_id": farm_id,
                "name": "Synthetic Tomato Field B",
                "area_hectares": 12.2,
                "crop": "tomato",
                "season": "2026",
                "boundary": {"type": "Polygon", "coordinates": [[[-120.2, 36.8], [-120.19, 36.8], [-120.19, 36.81], [-120.2, 36.81], [-120.2, 36.8]]]},
                **SYNTHETIC_MARKER,
            },
        ],
        "management_zones": [
            {"id": zone_ids[index], "field_id": field_ids[0 if index < 2 else 1], "name": f"Synthetic Zone {index + 1}", **SYNTHETIC_MARKER}
            for index in range(3)
        ],
        "irrigation_systems": [
            {"id": _identifier(project.id, "irrigation-system"), "field_id": field_ids[0], "type": "drip", "execution_enabled": False, **SYNTHETIC_MARKER}
        ],
        "source": {"id": source_id, "type": "synthetic_fixture", "status": "ready", **SYNTHETIC_MARKER},
        "observations": observations,
        "irrigation_events": [
            {"id": _identifier(project.id, "irrigation-event"), "field_id": field_ids[0], "occurred_at": base.isoformat() + "Z", "duration_minutes": 75, **SYNTHETIC_MARKER}
        ],
        "anomalies": [
            {"id": _identifier(project.id, "anomaly"), "field_id": field_ids[1], "type": "moisture_decline", "severity": "medium", **SYNTHETIC_MARKER}
        ],
        "recommendations": [
            {
                "id": recommendation_id,
                "field_id": field_ids[0],
                "status": "ready",
                "summary": "Apply a synthetic 18 mm irrigation window within 24 hours.",
                "evidence": [observations[0]["id"], observations[2]["id"]],
                "provenance": {"fixture_version": FIXTURE_VERSION},
                "physical_execution_enabled": False,
                **SYNTHETIC_MARKER,
            }
        ],
        "reports": [{"id": report_id, "status": "ready", "title": "Synthetic Weekly Field Report", **SYNTHETIC_MARKER}],
        "ingestion_jobs": [{"id": job_id, "status": "succeeded", "records_processed": len(observations), **SYNTHETIC_MARKER}],
        "webhook_events": [{"id": webhook_event_id, "type": "sandbox.recommendation.ready", "version": "2026-07-01", **SYNTHETIC_MARKER}],
    }


def reset_sandbox(db: Session, project: ApiProject, *, user_id: str) -> PlatformSandboxState:
    row = ensure_sandbox_state(db, project)
    row.reset_counter = int(row.reset_counter or 0) + 1
    row.last_reset_by_user_id = user_id
    row.last_reset_at = datetime.utcnow()
    row.fixture_version = FIXTURE_VERSION
    return row
