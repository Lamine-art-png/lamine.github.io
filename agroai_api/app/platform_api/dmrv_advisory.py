"""Read-only, deterministic TEST UAT preview for agricultural DMRV integrations.

The preview runs the evidence-grounded DMRV engine: the location is resolved
against a versioned gazetteer, and recommendations are computed from public
reference data (NASA POWER climate normals, ISRIC SoilGrids), cited FAO-56
crop parameters and the scientific tool registry. It never invokes a model,
spends credits, fetches anything at request time, writes to providers, or
reads customer production records. Optional measurements must be declared
synthetic UAT data.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.intelligence_platform.contract import AgriculturalContext
from app.intelligence_platform.dmrv_engine import AREAS as ENGINE_AREAS, ENGINE_VERSION, build_dmrv_analysis, load_reference
from app.intelligence_platform.schemas import BUILTIN_SCHEMAS, validation_errors
from app.models.platform_api import ApiProject
from app.platform_api.sandbox import FIXTURE_VERSION

Area = Literal["irrigation", "nutrients", "soil", "monitoring", "sustainability"]
AREAS: tuple[Area, ...] = ENGINE_AREAS  # type: ignore[assignment]
CONTRACT_VERSION = "dmrv-uat/2"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UatSoilTest(_Strict):
    available_n_kg_ha: float | None = Field(default=None, ge=0, le=5_000)
    available_p_kg_ha: float | None = Field(default=None, ge=0, le=1_000)
    available_k_kg_ha: float | None = Field(default=None, ge=0, le=5_000)
    organic_carbon_pct: float | None = Field(default=None, ge=0, le=60)
    ph: float | None = Field(default=None, ge=2, le=12)
    ec_ds_m: float | None = Field(default=None, ge=0, le=100)
    sampled_at: date | None = None


class UatSoilWater(_Strict):
    field_capacity_vwc_fraction: float | None = Field(default=None, gt=0, lt=1)
    wilting_point_vwc_fraction: float | None = Field(default=None, gt=0, lt=1)
    current_vwc_fraction: float | None = Field(default=None, ge=0, le=1)
    measured_at: date | None = None


class UatIrrigationSystem(_Strict):
    type: str | None = Field(default=None, max_length=80)
    efficiency: float | None = Field(default=None, gt=0, le=1)


class UatMeasurements(_Strict):
    """Caller-supplied UAT measurements. Must be synthetic in TEST."""

    data_classification: Literal["synthetic"]
    soil_test: UatSoilTest | None = None
    soil_water: UatSoilWater | None = None
    irrigation_system: UatIrrigationSystem | None = None
    field_area_ha: float | None = Field(default=None, gt=0, le=10_000)
    root_zone_depth_m: float | None = Field(default=None, gt=0, le=5)
    stage_lengths_days: list[int] | None = Field(default=None, min_length=4, max_length=4)

    @model_validator(mode="after")
    def bounded_stage_lengths(self) -> "UatMeasurements":
        if self.stage_lengths_days and any(day < 1 or day > 400 for day in self.stage_lengths_days):
            raise ValueError("stage_lengths_days must be four integers between 1 and 400")
        return self


class DmrvAdvisoryPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: AgriculturalContext
    areas: list[Area] = Field(default_factory=lambda: list(AREAS), min_length=1, max_length=5)
    as_of: date | None = Field(default=None, description="Evaluation date for stage calculation; never defaulted to server time.")
    measurements: UatMeasurements | None = None

    @model_validator(mode="after")
    def test_selectors_only(self) -> "DmrvAdvisoryPreviewRequest":
        location, crop = self.context.location, self.context.crop
        if not location or not location.country or not (location.state or location.region) or not location.district:
            raise ValueError("TEST preview requires country (ISO alpha-2), state/region, and district")
        if not crop or not crop.name or not crop.name.strip():
            raise ValueError("TEST preview requires a crop name")
        if location.country != location.country.upper() or not location.country.isalpha():
            raise ValueError("country must be a two-letter uppercase ISO code")
        # Production field records do not belong in TEST. Synthetic UAT values go
        # in the explicitly classified ``measurements`` block instead.
        disallowed = (
            "operation", "field", "time_window", "observations", "weather",
            "issues", "treatments", "equipment", "tasks", "harvest",
            "financial", "market", "sources", "extensions",
        )
        if any(getattr(self.context, field) for field in disallowed):
            raise ValueError("TEST preview accepts location and crop selectors only; put synthetic UAT values in measurements")
        if any(
            getattr(location, field) is not None
            for field in ("geometry", "latitude", "longitude", "elevation_m")
        ):
            raise ValueError("TEST preview does not accept precise real-world location evidence")
        if location.model_extra or crop.model_extra:
            raise ValueError("TEST preview does not accept unrecognized location or crop data")
        if crop.cycle_id is not None:
            raise ValueError("TEST preview does not accept production crop cycle identifiers")
        if location.state and location.region and location.state.strip().casefold() != location.region.strip().casefold():
            raise ValueError("state and region cannot conflict")
        if not all(label.strip() for label in (location.state or location.region, location.district)):
            raise ValueError("state/region and district cannot be empty")
        labels = [location.country, location.state, location.region, location.district, crop.name, crop.variety, crop.season, crop.growth_stage]
        if any(label and any(ord(ch) < 32 or ord(ch) == 127 for ch in label) for label in labels):
            raise ValueError("location and crop labels must not contain control characters")
        if len(self.areas) != len(set(self.areas)):
            raise ValueError("areas must be unique")
        return self


def simulate_dmrv_preview(payload: DmrvAdvisoryPreviewRequest, project: ApiProject) -> dict[str, Any]:
    """Return a deterministic, evidence-grounded UAT analysis; never uses live inference.

    Raises ``DmrvInputError`` for locations or crops the engine cannot ground.
    """
    if project.environment != "test":
        raise ValueError("DMRV UAT preview requires a TEST project")

    location, crop = payload.context.location, payload.context.crop
    assert location is not None and crop is not None
    selected = list(dict.fromkeys(payload.areas))
    measurements = payload.measurements.model_dump(mode="json", exclude_none=True) if payload.measurements else {}
    reference = load_reference()
    analysis = build_dmrv_analysis(
        country=location.country, state=location.state or location.region, district=location.district,
        crop_name=crop.name, variety=crop.variety, season=crop.season, growth_stage=crop.growth_stage,
        planted_at=crop.planted_at.date() if crop.planted_at else None, as_of=payload.as_of,
        areas=selected, measurements=measurements, reference=reference,
    )
    canonical = json.dumps(
        {
            "project": project.id,
            "context": payload.context.model_dump(mode="json", exclude_none=True),
            "areas": selected,
            "as_of": payload.as_of.isoformat() if payload.as_of else None,
            "measurements": measurements,
            "engine": ENGINE_VERSION,
            "dataset": reference.sha256,
        },
        sort_keys=True, separators=(",", ":"),
    )
    scenario_id = "uat_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    output = analysis["structured_output"]
    if validation_errors(output, BUILTIN_SCHEMAS["dmrv_advisory"]):
        raise RuntimeError("Internal DMRV contract validation failed")
    known = {item["id"] for item in analysis["evidence"]} | {item["id"] for item in analysis["calculations"]}
    if any(evidence_id not in known for rec in output["recommendations"] for evidence_id in rec["evidence_ids"]):
        raise RuntimeError("Internal DMRV evidence reference failed")
    geo = analysis["geography"]
    return {
        "id": scenario_id,
        "object": "agroai.dmrv_advisory.preview",
        "contract_version": CONTRACT_VERSION,
        "status": "simulated",
        "environment": "test",
        "model_executed": False,
        "synthetic": True,
        "physical_execution": False,
        "provider_credentials": False,
        "billing": {"charged_cents": 0},
        "fixture_version": FIXTURE_VERSION,
        "engine_version": analysis["engine_version"],
        "reference_dataset": analysis["reference_dataset"],
        "normalized_context": {
            "country": geo["country"],
            "state_or_region": geo["state"],
            "district": geo["district"],
            "crop": analysis["crop"]["crop_id"],
            "variety": crop.variety,
            "season": analysis["calendar"]["season"],
            "growth_stage": crop.growth_stage,
            "current_stage": analysis["calendar"]["current_stage"],
            "location_verified": False,
            "location_resolved": True,
            "location_precision": geo["precision"],
        },
        "geography": geo,
        "crop": analysis["crop"],
        "calendar": analysis["calendar"],
        "water_balance": analysis["water_balance"],
        "soil_reference": analysis["soil_reference"],
        "measured_soil_water": analysis["measured_soil_water"],
        "soil_test": analysis["soil_test"],
        "heat_risk": analysis["heat_risk"],
        "coverage": analysis["coverage"],
        "structured_output_status": "valid",
        "structured_output": output,
        "evidence": analysis["evidence"],
        "calculations": analysis["calculations"],
        "provenance": {
            "fixture_version": FIXTURE_VERSION,
            "evidence_ids": [item["id"] for item in analysis["evidence"]],
            "source": "agroai_reference_data_and_scientific_tools",
            "reference_dataset_sha256": reference.sha256,
            "customer_field_data_used": False,
            "uat_measurements_used": bool(measurements),
        },
    }
