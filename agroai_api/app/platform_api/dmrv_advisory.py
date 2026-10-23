"""Read-only, deterministic TEST UAT preview for agricultural DMRV integrations.

This adapter exercises the public geographic/crop input and structured-output
contract without invoking models, spending credits, fetching live geography or
accepting production data. It is NOT a substitute for the LIVE Intelligence API.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.intelligence_platform.contract import AgriculturalContext
from app.intelligence_platform.schemas import BUILTIN_SCHEMAS, validation_errors
from app.models.platform_api import ApiProject
from app.platform_api.sandbox import FIXTURE_VERSION

Area = Literal["irrigation", "nutrients", "soil", "monitoring", "sustainability"]
AREAS: tuple[Area, ...] = ("irrigation", "nutrients", "soil", "monitoring", "sustainability")


class DmrvAdvisoryPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: AgriculturalContext
    areas: list[Area] = Field(default_factory=lambda: list(AREAS), min_length=1, max_length=5)

    @model_validator(mode="after")
    def test_selectors_only(self) -> "DmrvAdvisoryPreviewRequest":
        location, crop = self.context.location, self.context.crop
        if not location or not location.country or not (location.state or location.region) or not location.district:
            raise ValueError("TEST preview requires country (ISO alpha-2), state/region, and district")
        if not crop or not crop.name or not crop.name.strip():
            raise ValueError("TEST preview requires a crop name")
        if location.country != location.country.upper() or not location.country.isalpha():
            raise ValueError("country must be a two-letter uppercase ISO code")
        # A sandbox selector is not a substitute for real agronomic evidence.
        # Prevent accidental ingestion of actual customer field/soil observations.
        disallowed = (
            "operation", "field", "time_window", "observations", "weather",
            "issues", "treatments", "equipment", "tasks", "harvest",
            "financial", "market", "sources", "extensions",
        )
        if any(getattr(self.context, field) for field in disallowed):
            raise ValueError("TEST preview accepts location and crop selectors only; do not submit production data")
        if any(
            getattr(location, field) is not None
            for field in ("geometry", "latitude", "longitude", "elevation_m")
        ):
            raise ValueError("TEST preview does not accept precise real-world location evidence")
        if location.model_extra or crop.model_extra:
            raise ValueError("TEST preview does not accept unrecognized location or crop data")
        if any(getattr(crop, field) is not None for field in ("variety", "season", "cycle_id", "planted_at")):
            raise ValueError("TEST preview allows only crop name and optional growth stage")
        if location.state and location.region and location.state.strip().casefold() != location.region.strip().casefold():
            raise ValueError("state and region cannot conflict")
        if not all(label.strip() for label in (location.state or location.region, location.district)):
            raise ValueError("state/region and district cannot be empty")
        if len(self.areas) != len(set(self.areas)):
            raise ValueError("areas must be unique")
        return self


_ACTIONS: dict[str, tuple[str, str, list[str]]] = {
    "irrigation": (
        "Review soil moisture, recent rainfall, ET0 and irrigation-system capacity before scheduling water.",
        "Water timing and depth require local measurements; this simulation supplies no irrigation prescription.",
        ["soil moisture observations", "dated rainfall and ET0", "irrigation efficiency and water rights"],
    ),
    "nutrients": (
        "Review soil/tissue laboratory analysis and crop stage before planning nutrient inputs.",
        "Fertilizer quantities cannot be determined from crop and district labels alone.",
        ["soil/tissue laboratory results", "nutrient management baseline", "crop stage"],
    ),
    "soil": (
        "Document soil condition, ground cover, erosion risk and management history.",
        "Soil management must be supported by site measurements and historical evidence.",
        ["soil sampling", "management history", "field observations"],
    ),
    "monitoring": (
        "Capture dated, georeferenced crop observations and link them to field-specific evidence.",
        "Monitoring results need a documented data source and a verifiable audit trail.",
        ["field observations", "source timestamps", "sampling protocol"],
    ),
    "sustainability": (
        "Record baseline and activity evidence against the applicable approved DMRV methodology.",
        "A recommendation alone does not establish verified climate impact or carbon credits.",
        ["approved methodology", "baseline records", "independent verification evidence"],
    ),
}


def simulate_dmrv_preview(payload: DmrvAdvisoryPreviewRequest, project: ApiProject) -> dict[str, Any]:
    """Return an isolated synthetic contract preview; never uses live inference."""
    if project.environment != "test":
        raise ValueError("DMRV UAT preview requires a TEST project")

    location, crop = payload.context.location, payload.context.crop
    assert location is not None and crop is not None
    selected = list(dict.fromkeys(payload.areas))
    canonical = json.dumps(
        {"project": project.id, "context": payload.context.model_dump(mode="json", exclude_none=True), "areas": selected},
        sort_keys=True, separators=(",", ":"),
    )
    scenario_id = "uat_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    recommendations = [
        {
            "category": area,
            "action": _ACTIONS[area][0],
            "rationale": _ACTIONS[area][1],
            "priority": "medium",
            "timing": "review before field implementation",
            "requires_human_approval": True,
            "evidence_ids": [],
            "required_evidence": _ACTIONS[area][2],
        }
        for area in selected
    ]
    output = {
        "summary": "Synthetic DMRV advisory preview. These are evidence-collection prompts, not validated location-specific prescriptions.",
        "recommendations": recommendations,
        "confidence": "low",
        "missing_data": sorted({item for area in selected for item in _ACTIONS[area][2]}),
        "limitations": [
            "No live weather, agronomic datasets, local regulations, or soil measurements were retrieved.",
            "Country, region, and district are caller-provided labels and have not been geocoded or independently verified.",
            "No fertilizer dose, irrigation quantity, carbon claim, or climate impact has been calculated.",
            "Production evidence-based intelligence requires a separately approved LIVE integration.",
        ],
    }
    errors = validation_errors(output, BUILTIN_SCHEMAS["dmrv_advisory"])
    if errors:
        raise RuntimeError("Internal synthetic DMRV contract validation failed")
    return {
        "id": scenario_id,
        "status": "simulated",
        "environment": "test",
        "model_executed": False,
        "synthetic": True,
        "physical_execution": False,
        "provider_credentials": False,
        "billing": {"charged_cents": 0},
        "fixture_version": FIXTURE_VERSION,
        "normalized_context": {
            "country": location.country,
            "state_or_region": location.state or location.region,
            "district": location.district,
            "crop": crop.name,
            "growth_stage": crop.growth_stage,
            "location_verified": False,
        },
        "structured_output_status": "valid",
        "structured_output": output,
        "provenance": {
            "fixture_version": FIXTURE_VERSION,
            "evidence_ids": [],
            "source": "static_synthetic_template",
            "customer_field_data_used": False,
        },
    }
