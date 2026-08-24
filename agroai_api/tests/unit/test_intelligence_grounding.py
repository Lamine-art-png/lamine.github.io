from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.ai import EvidenceContext
from app.services.intelligence_grounding import build_intelligence_grounding


NOW = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)


def _context(rows, missing=None):
    return EvidenceContext(
        organization_id="org-1",
        workspace_id="ws-1",
        block_id="field-1",
        crop_type="almond",
        region="California",
        evidence=rows,
        missing_data=missing or [],
        citations=[],
    )


def test_science_graph_computes_fao_etc_only_from_explicit_inputs():
    context = _context(
        [
            {
                "id": "weather-1",
                "type": "weather_observation",
                "title": "CIMIS ETo",
                "field_id": "field-1",
                "occurred_at": "2026-08-21T18:00:00Z",
                "quality_status": "verified",
                "confidence": 0.95,
                "value_json": {"eto_mm": 5.0},
            },
            {
                "id": "crop-1",
                "type": "field_observation",
                "title": "Approved crop coefficient",
                "field_id": "field-1",
                "occurred_at": "2026-08-21T18:30:00Z",
                "quality_status": "verified",
                "confidence": 0.95,
                "value_json": {"kc": 0.8},
            },
        ]
    )

    packet = build_intelligence_grounding(context, now=NOW)
    result = next(row for row in packet.science_checks if row.rule_id == "fao56.etc.single_kc.v1")

    assert result.value == 4.0
    assert result.unit == "mm"
    assert result.inputs == {"eto_mm": 5.0, "kc": 0.8}
    assert result.evidence_ids == ["crop-1", "weather-1"]


def test_science_graph_never_infers_missing_crop_coefficient():
    context = _context(
        [
            {
                "id": "weather-1",
                "type": "weather_observation",
                "title": "ETo",
                "field_id": "field-1",
                "occurred_at": "2026-08-21T18:00:00Z",
                "value_json": {"eto_mm": 6.2},
            }
        ]
    )

    packet = build_intelligence_grounding(context, now=NOW)

    assert not any(row.rule_id == "fao56.etc.single_kc.v1" for row in packet.science_checks)


def test_recent_conflicting_soil_moisture_is_carried_as_conflict():
    context = _context(
        [
            {
                "id": "probe-a",
                "type": "telemetry",
                "title": "Probe A",
                "field_id": "field-1",
                "occurred_at": "2026-08-21T18:00:00Z",
                "value_json": {"soil_moisture_pct": 18.0},
            },
            {
                "id": "probe-b",
                "type": "telemetry",
                "title": "Probe B",
                "field_id": "field-1",
                "occurred_at": "2026-08-21T18:10:00Z",
                "value_json": {"soil_moisture_pct": 31.0},
            },
        ]
    )

    packet = build_intelligence_grounding(context, now=NOW)

    assert len(packet.conflicts) == 1
    assert packet.conflicts[0].metric == "soil_moisture_pct"
    assert packet.conflicts[0].severity == "high"
    assert packet.grounding_confidence < 0.7


def test_stale_and_failed_sources_do_not_receive_high_grounding_confidence():
    context = _context(
        [
            {
                "id": "old-1",
                "type": "telemetry",
                "title": "Old probe",
                "field_id": "field-1",
                "occurred_at": "2025-01-01T00:00:00Z",
                "quality_status": "failed",
                "confidence": 0.99,
                "value_json": {"soil_moisture_pct": 22.0},
            }
        ],
        missing=["current weather", "recent irrigation"],
    )

    packet = build_intelligence_grounding(context, now=NOW)

    assert packet.observed_facts[0].freshness_score < 0.5
    assert packet.observed_facts[0].quality_score < 0.2
    assert packet.grounding_confidence < 0.4


def test_flow_runtime_produces_measured_volume_without_efficiency_guess():
    context = _context(
        [
            {
                "id": "meter-1",
                "type": "meter_reading",
                "field_id": "field-1",
                "occurred_at": "2026-08-21T19:00:00Z",
                "value_json": {"flow_rate_gpm": 120.0, "runtime_minutes": 30.0},
            }
        ]
    )

    packet = build_intelligence_grounding(context, now=NOW)
    result = next(row for row in packet.science_checks if row.rule_id == "irrigation.measured_volume.v1")

    assert result.value == 3600.0
    assert result.unit == "gallons"
    assert "efficiency" in " ".join(result.assumptions).lower()


def test_wrong_workspace_and_tenant_rows_are_excluded_before_reasoning():
    context = _context(
        [
            {"id": "wrong-org", "type": "telemetry", "organization_id": "org-2", "field_id": "field-1", "summary": "foreign"},
            {"id": "wrong-ws", "type": "telemetry", "workspace_id": "ws-2", "field_id": "field-1", "summary": "foreign"},
            {"id": "right", "type": "telemetry", "organization_id": "org-1", "workspace_id": "ws-1", "field_id": "field-1", "summary": "local"},
        ]
    )

    packet = build_intelligence_grounding(context, now=NOW)

    assert [row.evidence_id for row in packet.observed_facts] == ["right"]
    assert packet.source_health["out_of_tenant_count"] == 2
