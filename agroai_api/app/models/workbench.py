from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

SourceKind = Literal[
    "controller_events",
    "controller_logs",
    "crop_profile",
    "field_notes",
    "flow_meter",
    "irrigation_records",
    "satellite_observation",
    "soil_moisture",
    "water_costs",
    "weather",
    "unknown",
]

class WorkbenchSession(BaseModel):
    session_id: str
    workspace_name: str = "Water Command Center"
    mode: Literal["demo", "live", "uploaded"]
    created_at: datetime
    updated_at: datetime
    status: str

class WorkbenchDataArtifact(BaseModel):
    artifact_id: str
    session_id: str
    filename: str
    content_type: str
    source_kind: SourceKind
    rows_detected: int
    columns_detected: List[str]
    parse_status: str
    warnings: List[str] = Field(default_factory=list)
    parsed_rows: List[Dict[str, Any]] = Field(default_factory=list)

class NormalizedSignal(BaseModel):
    signal_id: str
    source_kind: SourceKind
    field_name: str
    canonical_name: str
    value: Any
    unit: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: float = 0.5
    raw_reference: str

class WorkbenchAnalysisRequest(BaseModel):
    session_id: str
    mode: Literal["demo", "live", "uploaded"]
    live_source: Optional[str] = None
    live_entity_id: Optional[str] = None
    crop_type: Optional[str] = None
    soil_type: Optional[str] = None
    irrigation_method: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    language: Optional[str] = None
    user_role: Optional[str] = None
    area: Optional[float] = None
    weather_context: Optional[Dict[str, Any]] = None
    sensor_context: Optional[Dict[str, Any]] = None
    controller_context: Optional[Dict[str, Any]] = None
    recent_irrigation_context: Optional[Dict[str, Any]] = None
    field_observations: List[str] = Field(default_factory=list)
    time_horizon: Optional[str] = None


class WorkbenchLiveAnalysisRequest(BaseModel):
    source: str = "wiseconn"
    entity_id: str = "162803"
    crop_type: Optional[str] = None
    soil_type: Optional[str] = None
    irrigation_method: Optional[str] = None
    area: Optional[float] = None
    location: Optional[Dict[str, Any]] = None
    weather_context: Optional[Dict[str, Any]] = None
    sensor_context: Optional[Dict[str, Any]] = None
    controller_context: Optional[Dict[str, Any]] = None
    recent_irrigation_context: Optional[Dict[str, Any]] = None
    field_observations: List[str] = Field(default_factory=list)
    language: Optional[str] = None
    user_role: Optional[str] = None
    time_horizon: Optional[str] = None


class WorkbenchActionRequest(BaseModel):
    actor: str = "Operations user"
    evidence_summary: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

class ReconciliationResult(BaseModel):
    matched_signals: List[str]
    conflicts_detected: List[str]
    missing_inputs: List[str]
    confidence_score: float
    confidence_label: str
    evidence_completeness: str
    interpretation: str
    planned_vs_applied_variance: Optional[str] = None
    controller_event_validity: Optional[str] = None
    flow_meter_agreement: Optional[str] = None
    weather_demand: Optional[str] = None
    soil_moisture_deficit: Optional[str] = None
    field_observation_support: Optional[str] = None
    satellite_stress_support: Optional[str] = None
    conflicts_resolved: List[str] = Field(default_factory=list)

class ReportArtifact(BaseModel):
    report_id: str
    title: str
    report_type: str
    summary: str
    metrics: Dict[str, Any]
    export_rows: List[Dict[str, Any]]

class WorkbenchAnalysisResult(BaseModel):
    analysis_id: str
    session_id: str
    status: str
    data_sources: Dict[str, Any]
    normalized_context: Dict[str, Any]
    signal_summary: Dict[str, Any]
    reconciliation: ReconciliationResult
    recommendation: Dict[str, Any]
    verification_plan: Dict[str, Any]
    report_summary: Dict[str, Any]
    source_trace: List[Dict[str, Any]]
    analysis_trace: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[str]
    model_status: str
    created_at: datetime
    # Truthful status fields (added in the V2 rebuild).
    backend_status: str = "available"
    analysis_mode: Literal["demo", "live", "uploaded"] = "uploaded"
    recommendation_origin: Literal[
        "representative_fallback",
        "deterministic_engine",
        "live_intelligence_engine",
        "uploaded_intelligence_engine",
        "insufficient_context",
    ] = "deterministic_engine"
    context_origin: Literal["representative", "uploaded", "live"] = "uploaded"
    live_inputs_used: List[str] = Field(default_factory=list)
    uploaded_artifacts_used: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
