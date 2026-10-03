"""Public request contract extensions for ``POST /v1/intelligence``.

Design rules (see docs/INTELLIGENCE_PLATFORM_V1.md):

* Every field here is optional and additive. A request that uses none of them
  is byte-for-byte the pre-platform request and is hashed, priced, and
  answered exactly as before.
* Top-level vocabulary is closed (``extra="forbid"``) so typos fail loudly;
  entity objects inside ``context`` accept additional attributes so callers can
  carry domain detail AGRO-AI has not modelled yet without a breaking change.
  Unmodelled *sections* belong in ``context.extensions``.
* Everything is bounded: counts, string lengths, nesting depth, total bytes.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_CONTEXT_BYTES = 256_000
MAX_SCHEMA_BYTES = 32_000
MAX_ATTACHMENTS = 8
MAX_TOOL_CALLS = 10
MAX_KNOWLEDGE_COLLECTIONS = 5
MAX_METADATA_KEYS = 16

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_COLLECTION = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_TOOL_NAME = re.compile(r"^[a-z0-9][a-z0-9_.]{1,79}$")
_METADATA_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _finite(value: float | None) -> float | None:
    if value is not None and not math.isfinite(float(value)):
        raise ValueError("numbers must be finite")
    return value


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, default=str, separators=(",", ":"), allow_nan=False).encode("utf-8"))


class _Entity(BaseModel):
    """Typed core attributes plus bounded caller extensions."""

    model_config = ConfigDict(extra="allow", str_max_length=4_000)


class Location(_Entity):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    elevation_m: float | None = Field(default=None, ge=-500, le=9_000)
    region: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2, description="ISO 3166-1 alpha-2")
    geometry: dict[str, Any] | None = Field(default=None, description="GeoJSON Point, Polygon or MultiPolygon")

    @field_validator("geometry")
    @classmethod
    def bounded_geojson(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        if value.get("type") not in {"Point", "Polygon", "MultiPolygon", "LineString"}:
            raise ValueError("geometry must be a GeoJSON Point, LineString, Polygon or MultiPolygon")
        if _encoded_size(value) > 64_000:
            raise ValueError("geometry must be 64 KB or smaller")
        return value


class TimeWindow(_Entity):
    start: datetime | None = None
    end: datetime | None = None
    as_of: datetime | None = None

    @model_validator(mode="after")
    def ordered(self) -> "TimeWindow":
        if self.start and self.end:
            if (self.start.tzinfo is None) != (self.end.tzinfo is None):
                raise ValueError("time_window.start and end must both include a UTC offset or both omit it")
            if self.end < self.start:
                raise ValueError("time_window.end must not be before time_window.start")
        return self


class Operation(_Entity):
    id: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    type: str | None = Field(default=None, max_length=80, description="farm, orchard, vineyard, ranch, greenhouse, cooperative, agribusiness, ...")
    area_ha: float | None = Field(default=None, ge=0)


class Soil(_Entity):
    texture: str | None = Field(default=None, max_length=80)
    organic_matter_pct: float | None = Field(default=None, ge=0, le=100)
    ph: float | None = Field(default=None, ge=0, le=14)
    field_capacity_vwc_fraction: float | None = Field(default=None, ge=0, le=1)
    wilting_point_vwc_fraction: float | None = Field(default=None, ge=0, le=1)


class IrrigationSystem(_Entity):
    type: str | None = Field(default=None, max_length=80)
    flow_m3h: float | None = Field(default=None, ge=0)
    efficiency: float | None = Field(default=None, gt=0, le=1)


class WaterSource(_Entity):
    type: str | None = Field(default=None, max_length=80)
    allocation_m3: float | None = Field(default=None, ge=0)
    salinity_ds_m: float | None = Field(default=None, ge=0)


class FieldContext(_Entity):
    id: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    area_ha: float | None = Field(default=None, ge=0)
    soil: Soil | None = None
    irrigation_system: IrrigationSystem | None = None
    water_source: WaterSource | None = None


class Crop(_Entity):
    name: str | None = Field(default=None, max_length=120)
    variety: str | None = Field(default=None, max_length=120)
    season: str | None = Field(default=None, max_length=80)
    cycle_id: str | None = Field(default=None, max_length=200)
    planted_at: datetime | None = None
    growth_stage: str | None = Field(default=None, max_length=120)


class Observation(_Entity):
    id: str | None = Field(default=None, max_length=200)
    type: str = Field(min_length=1, max_length=120)
    value: Any = None
    unit: str | None = Field(default=None, max_length=40)
    observed_at: datetime | None = None
    source: str | None = Field(default=None, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: Any) -> Any:
        if isinstance(value, float):
            _finite(value)
        return value


class WeatherPoint(_Entity):
    at: datetime
    tmax_c: float | None = Field(default=None, ge=-80, le=70)
    tmin_c: float | None = Field(default=None, ge=-90, le=60)
    precipitation_mm: float | None = Field(default=None, ge=0, le=2_000)
    et0_mm: float | None = Field(default=None, ge=0, le=30)
    relative_humidity_pct: float | None = Field(default=None, ge=0, le=100)
    wind_speed_ms: float | None = Field(default=None, ge=0, le=120)
    kind: Literal["observed", "forecast"] = "observed"


class Weather(_Entity):
    source: str | None = Field(default=None, max_length=200)
    series: list[WeatherPoint] = Field(default_factory=list, max_length=400)


class Issue(_Entity):
    type: Literal["pest", "disease", "weed", "nutrient", "abiotic", "water", "equipment", "other"] = "other"
    name: str | None = Field(default=None, max_length=200)
    severity: Literal["unknown", "low", "medium", "high", "critical"] = "unknown"
    observed_at: datetime | None = None
    affected_area_pct: float | None = Field(default=None, ge=0, le=100)


class Treatment(_Entity):
    product: str | None = Field(default=None, max_length=200)
    active_ingredient: str | None = Field(default=None, max_length=200)
    rate: float | None = Field(default=None, ge=0)
    rate_unit: str | None = Field(default=None, max_length=40)
    applied_at: datetime | None = None
    target: str | None = Field(default=None, max_length=200)


class Equipment(_Entity):
    id: str | None = Field(default=None, max_length=200)
    type: str | None = Field(default=None, max_length=120)
    make: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)


class WorkTask(_Entity):
    title: str = Field(min_length=1, max_length=300)
    status: str | None = Field(default=None, max_length=40)
    due_at: datetime | None = None


class Harvest(_Entity):
    expected_yield: float | None = Field(default=None, ge=0)
    actual_yield: float | None = Field(default=None, ge=0)
    yield_unit: str | None = Field(default=None, max_length=40)
    harvested_at: datetime | None = None


class CostItem(_Entity):
    category: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=0)
    basis: Literal["total", "per_ha", "per_unit"] = "total"


class Financial(_Entity):
    currency: str | None = Field(default=None, min_length=3, max_length=3, description="ISO 4217")
    price_per_unit: float | None = Field(default=None, ge=0)
    price_unit: str | None = Field(default=None, max_length=40)
    costs: list[CostItem] = Field(default_factory=list, max_length=100)
    revenue: float | None = Field(default=None, ge=0)
    budget: float | None = Field(default=None, ge=0)


class Market(_Entity):
    commodity: str | None = Field(default=None, max_length=120)
    price: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    as_of: datetime | None = None


class SourceRef(_Entity):
    id: str = Field(min_length=1, max_length=200)
    type: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=200)
    uri: str | None = Field(default=None, max_length=1_000, description="Informational only; AGRO-AI never fetches it.")
    observed_at: datetime | None = None


class AgriculturalContext(BaseModel):
    """Shared agricultural domain context.

    Sections are optional. Use ``extensions`` (namespaced keys such as
    ``"acme.contract"``) for domain data that has no section yet.
    """

    model_config = ConfigDict(extra="forbid")

    operation: Operation | None = None
    field: FieldContext | None = None
    crop: Crop | None = None
    location: Location | None = None
    time_window: TimeWindow | None = None
    observations: list[Observation] = Field(default_factory=list, max_length=200)
    weather: Weather | None = None
    issues: list[Issue] = Field(default_factory=list, max_length=50)
    treatments: list[Treatment] = Field(default_factory=list, max_length=100)
    equipment: list[Equipment] = Field(default_factory=list, max_length=50)
    tasks: list[WorkTask] = Field(default_factory=list, max_length=100)
    harvest: Harvest | None = None
    financial: Financial | None = None
    market: Market | None = None
    sources: list[SourceRef] = Field(default_factory=list, max_length=100)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extensions")
    @classmethod
    def namespaced_extensions(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 32:
            raise ValueError("context.extensions accepts at most 32 namespaces")
        for key in value:
            if not _METADATA_KEY.fullmatch(str(key)):
                raise ValueError("context.extensions keys must be 1-64 safe identifier characters")
        return value

    @model_validator(mode="after")
    def bounded(self) -> "AgriculturalContext":
        if _encoded_size(self.model_dump(mode="json", exclude_none=True)) > MAX_CONTEXT_BYTES:
            raise ValueError("context must be 256 KB or smaller")
        return self


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=200)

    @field_validator("file_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("file_id is not a valid AGRO-AI file id")
        return value


class ResponseFormat(BaseModel):
    """``text`` (default), a built-in AGRO-AI schema, or a caller JSON Schema."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["text", "agroai_schema", "json_schema"] = "text"
    name: str | None = Field(default=None, min_length=1, max_length=64)
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    description: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def consistent(self) -> "ResponseFormat":
        if self.type == "agroai_schema" and not self.name:
            raise ValueError("response_format.name is required for agroai_schema")
        if self.type == "json_schema":
            if not self.schema_:
                raise ValueError("response_format.schema is required for json_schema")
            from app.intelligence_platform.schemas import validate_caller_schema

            validate_caller_schema(self.schema_)
        if self.type == "text" and (self.schema_ or self.name):
            raise ValueError("response_format.type text takes no schema")
        return self


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if not _TOOL_NAME.fullmatch(value):
            raise ValueError("tool name is not a registered AGRO-AI tool identifier")
        return value

    @field_validator("arguments")
    @classmethod
    def bounded_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        if _encoded_size(value) > 32_000:
            raise ValueError("tool arguments must be 32 KB or smaller")
        return value


class KnowledgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collections: list[str] = Field(min_length=1, max_length=MAX_KNOWLEDGE_COLLECTIONS)
    query: str | None = Field(default=None, min_length=2, max_length=1_000)
    max_results: int = Field(default=6, ge=1, le=12)

    @field_validator("collections")
    @classmethod
    def safe_collections(cls, value: list[str]) -> list[str]:
        for name in value:
            if not _COLLECTION.fullmatch(name):
                raise ValueError("collection names are lowercase letters, digits, '.', '_' or '-' (max 64)")
        return list(dict.fromkeys(value))


def validate_metadata(value: dict[str, str]) -> dict[str, str]:
    if len(value) > MAX_METADATA_KEYS:
        raise ValueError(f"metadata accepts at most {MAX_METADATA_KEYS} keys")
    for key, item in value.items():
        if not _METADATA_KEY.fullmatch(str(key)):
            raise ValueError("metadata keys must be 1-64 safe identifier characters")
        if not isinstance(item, str) or len(item) > 256:
            raise ValueError("metadata values must be strings of 256 characters or fewer")
    return value


def valid_identifier(value: str | None) -> bool:
    return bool(value) and bool(_IDENTIFIER.fullmatch(str(value)))


def valid_collection(value: str | None) -> bool:
    return bool(value) and bool(_COLLECTION.fullmatch(str(value)))


# Request fields added by the platform. A legacy-shaped request carries none
# of them, which keeps its idempotency hash identical to pre-platform runs.
PLATFORM_REQUEST_FIELDS: dict[str, Any] = {
    "context": None,
    "attachments": [],
    "response_format": None,
    "tools": [],
    "knowledge": None,
    "session_id": None,
    "metadata": {},
    "stream": False,
}
