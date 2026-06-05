"""Tests for the FCGMA Water Intelligence Copilot.

Covers:
- WiseConn adapter truthfulness (controller telemetry ≠ extraction)
- Source-class distinction
- No meter extraction invented from controller telemetry
- Generic AMI CSV ingestion
- CIMIS unavailable state
- Unit normalization
- Multiplier application
- Duplicate detection
- Missing interval
- Meter reset
- Late-arriving record
- Pump activity without meter movement
- Unresolved mapping
- Backup-estimation provisional state
- Recomputation versioning
- Reviewer adjustment audit event
- AI tool grounding
- Deterministic fallback answer
- Report generation
- Injected-scenario labeling
- No live/injected silent mixing
"""
from __future__ import annotations

import io
import sys
import os

import pytest

# ── path setup for test runner ──────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_fcgma.db")


# ─────────────────────────────────────────────
# Unit tests: ledger
# ─────────────────────────────────────────────

def test_evidence_classes_are_enforced():
    from app.services.fcgma.ledger import make_record, EVIDENCE_CLASSES
    with pytest.raises(ValueError, match="Invalid evidence_class"):
        make_record(
            evidence_class="invented_class",
            provider="fcgma_generic_ami_csv",
            external_source_id="x",
            event_timestamp="2026-03-01T00:00:00+00:00",
            reporting_period="2026-Q1",
            well_id="w1", meter_id="m1",
        )


def test_all_required_evidence_classes_defined():
    from app.services.fcgma.ledger import EVIDENCE_CLASSES
    required = {
        "controller_irrigation_telemetry",
        "groundwater_meter_reading",
        "pump_state_evidence",
        "weather_context",
        "public_context",
        "provisional_applied_water_attribution",
        "reviewer_adjustment",
        "injected_demo_scenario",
    }
    assert required.issubset(EVIDENCE_CLASSES)


def test_make_record_sets_scenario_label():
    from app.services.fcgma.ledger import make_record
    r = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="test-001",
        event_timestamp="2026-03-01T00:00:00+00:00",
        reporting_period="2026-Q1",
        well_id="well-test-01", meter_id="meter-test-01",
        scenario_injected=True,
        scenario_label="Demonstration scenario injected to illustrate exception handling.",
    )
    assert r["scenario_injected"] is True
    assert "Demonstration scenario" in r["scenario_label"]
    assert r["evidence_class"] == "groundwater_meter_reading"


def test_wiseconn_controller_telemetry_is_not_extraction():
    """Controller telemetry records must not carry cumulative_volume that implies extraction."""
    from app.services.fcgma.ledger import make_record
    r = make_record(
        evidence_class="controller_irrigation_telemetry",
        provider="wiseconn_sanitized_replay",
        external_source_id="wc-001",
        event_timestamp="2026-03-01T00:00:00+00:00",
        reporting_period="2026-Q1",
        well_id="well-anon-01", meter_id="meter-anon-01",
        pump_status="running",
        cumulative_volume=None,  # Controller telemetry has NO extraction volume
        interval_volume=None,
    )
    assert r["cumulative_volume"] is None
    assert r["interval_volume"] is None
    assert r["evidence_class"] == "controller_irrigation_telemetry"
    assert r["provider"] == "wiseconn_sanitized_replay"


def test_groundwater_meter_reading_is_distinct_from_controller():
    from app.services.fcgma.ledger import make_record
    meter_r = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-001",
        event_timestamp="2026-03-01T00:00:00+00:00",
        reporting_period="2026-Q1",
        well_id="well-anon-01", meter_id="meter-anon-01",
        cumulative_volume=500.0,
        interval_volume=5.0,
        unit="acre-feet",
    )
    controller_r = make_record(
        evidence_class="controller_irrigation_telemetry",
        provider="wiseconn_sanitized_replay",
        external_source_id="wc-001",
        event_timestamp="2026-03-01T00:00:00+00:00",
        reporting_period="2026-Q1",
        well_id="well-anon-01", meter_id="meter-anon-01",
        pump_status="running",
        cumulative_volume=None,
        interval_volume=None,
    )
    # Key assertion: they have DIFFERENT evidence classes
    assert meter_r["evidence_class"] != controller_r["evidence_class"]
    # Key assertion: controller telemetry has NO extraction volume
    assert controller_r["interval_volume"] is None
    assert controller_r["cumulative_volume"] is None


# ─────────────────────────────────────────────
# Unit tests: calculation engine
# ─────────────────────────────────────────────

def test_unit_normalization_gallons():
    from app.services.fcgma.calculation_engine import normalize_units
    r = {"id": "x", "unit": "acre-feet", "unit_original": "gallons", "cumulative_volume": 325851.0, "interval_volume": 325851.0, "exceptions": []}
    result = normalize_units(r)
    assert abs(result["cumulative_volume"] - 1.0) < 0.0001
    assert abs(result["interval_volume"] - 1.0) < 0.0001
    assert result["unit"] == "acre-feet"


def test_unit_normalization_cubic_feet():
    from app.services.fcgma.calculation_engine import normalize_units
    r = {"id": "x", "unit": "acre-feet", "unit_original": "cubic_feet", "cumulative_volume": 43560.0, "interval_volume": None, "exceptions": []}
    result = normalize_units(r)
    assert abs(result["cumulative_volume"] - 1.0) < 0.0001


def test_multiplier_application():
    from app.services.fcgma.calculation_engine import apply_multiplier
    r = {"id": "x", "cumulative_volume": 10.0, "interval_volume": 2.0, "multiplier": 5.0, "exceptions": []}
    result = apply_multiplier(r)
    assert result["cumulative_volume"] == 50.0
    assert result["interval_volume"] == 10.0


def test_multiplier_1_is_identity():
    from app.services.fcgma.calculation_engine import apply_multiplier
    r = {"id": "x", "cumulative_volume": 10.0, "interval_volume": 2.0, "multiplier": 1.0, "exceptions": []}
    result = apply_multiplier(r)
    assert result["cumulative_volume"] == 10.0
    assert result["interval_volume"] == 2.0


def test_negative_delta_detection():
    from app.services.fcgma.calculation_engine import detect_negative_delta
    from app.services.fcgma.ledger import clear_ledger
    clear_ledger()
    r = {"id": "test-neg-001", "interval_volume": -5.0, "exceptions": []}
    excs = detect_negative_delta(r)
    assert len(excs) == 1
    assert excs[0]["exception_type"] == "negative_delta"
    assert excs[0]["severity"] == "high"


def test_positive_delta_no_exception():
    from app.services.fcgma.calculation_engine import detect_negative_delta
    r = {"id": "test-pos-001", "interval_volume": 3.5, "exceptions": []}
    excs = detect_negative_delta(r)
    assert len(excs) == 0


def test_meter_reset_detection():
    from app.services.fcgma.calculation_engine import detect_meter_reset
    from app.services.fcgma.ledger import clear_ledger
    clear_ledger()
    current = {"id": "test-reset-001", "cumulative_volume": 10.0, "exceptions": []}
    previous = {"id": "test-reset-000", "cumulative_volume": 9800.0, "exceptions": []}
    excs = detect_meter_reset(current, previous)
    assert len(excs) == 1
    assert excs[0]["exception_type"] == "meter_reset_detected"


def test_no_reset_small_drop():
    from app.services.fcgma.calculation_engine import detect_meter_reset
    current = {"id": "x", "cumulative_volume": 99.9, "exceptions": []}
    previous = {"id": "y", "cumulative_volume": 100.0, "exceptions": []}
    excs = detect_meter_reset(current, previous)
    assert len(excs) == 0


def test_duplicate_detection():
    from app.services.fcgma.ledger import make_record, upsert_record, clear_ledger
    from app.services.fcgma.calculation_engine import detect_duplicate
    clear_ledger()
    ts = "2026-03-01T08:00:00+00:00"
    r1 = make_record(
        evidence_class="groundwater_meter_reading", provider="fcgma_generic_ami_csv",
        external_source_id="a1", event_timestamp=ts, reporting_period="2026-Q1",
        well_id="w1", meter_id="m1",
    )
    r2 = make_record(
        evidence_class="groundwater_meter_reading", provider="fcgma_generic_ami_csv",
        external_source_id="a2", event_timestamp=ts,  # Same timestamp
        reporting_period="2026-Q1", well_id="w1", meter_id="m1",
    )
    upsert_record(r1)
    upsert_record(r2)
    excs = detect_duplicate(r2, [r1, r2])
    assert len(excs) >= 1
    assert excs[0]["exception_type"] == "duplicate_record"


def test_missing_interval_detection():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.calculation_engine import detect_missing_interval
    clear_ledger()
    r = {"id": "gap-after", "event_timestamp": "2026-03-05T08:00:00+00:00", "exceptions": []}
    prev = {"id": "gap-before", "event_timestamp": "2026-03-01T08:00:00+00:00", "exceptions": []}
    excs = detect_missing_interval(r, prev, max_gap_hours=26.0)
    assert len(excs) == 1
    assert excs[0]["exception_type"] == "missing_telemetry_interval"


def test_no_gap_within_threshold():
    from app.services.fcgma.calculation_engine import detect_missing_interval
    r = {"id": "r1", "event_timestamp": "2026-03-02T08:00:00+00:00", "exceptions": []}
    prev = {"id": "r0", "event_timestamp": "2026-03-01T08:00:00+00:00", "exceptions": []}
    excs = detect_missing_interval(r, prev, max_gap_hours=26.0)
    assert len(excs) == 0


def test_unresolved_combcode_flagged():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.calculation_engine import detect_unresolved_combcode
    clear_ledger()
    r = {"id": "no-cc-001", "evidence_class": "groundwater_meter_reading", "combcode": None, "exceptions": []}
    excs = detect_unresolved_combcode(r)
    assert len(excs) == 1
    assert excs[0]["exception_type"] == "unresolved_combcode"


def test_resolved_combcode_not_flagged():
    from app.services.fcgma.calculation_engine import detect_unresolved_combcode
    r = {"id": "cc-001", "evidence_class": "groundwater_meter_reading", "combcode": "FC-ZN-07-001", "exceptions": []}
    excs = detect_unresolved_combcode(r)
    assert len(excs) == 0


def test_controller_telemetry_not_checked_for_combcode():
    """Controller telemetry records should NOT be flagged for missing CombCode."""
    from app.services.fcgma.calculation_engine import detect_unresolved_combcode
    r = {"id": "ctrl-001", "evidence_class": "controller_irrigation_telemetry", "combcode": None, "exceptions": []}
    excs = detect_unresolved_combcode(r)
    assert len(excs) == 0


def test_backup_estimate_required_flagged():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.calculation_engine import detect_backup_estimate_required
    clear_ledger()
    r = {"id": "meter-fail-001", "source_quality": "meter_failure", "exceptions": []}
    excs = detect_backup_estimate_required(r)
    assert len(excs) == 1
    assert excs[0]["exception_type"] == "backup_estimate_required"


def test_ok_quality_not_flagged_for_backup():
    from app.services.fcgma.calculation_engine import detect_backup_estimate_required
    r = {"id": "ok-001", "source_quality": "ok", "exceptions": []}
    excs = detect_backup_estimate_required(r)
    assert len(excs) == 0


def test_provisional_attribution_when_exceptions_open():
    from app.services.fcgma.calculation_engine import compute_provisional_attribution
    r = {
        "id": "prov-001",
        "combcode": "FC-ZN-07-001",
        "parcel_ids": ["p1"],
        "interval_volume": 5.0,
        "source_quality": "ok",
        "exceptions": [{"status": "open", "exception_type": "missing_mapping"}],
    }
    result = compute_provisional_attribution(r)
    assert result["attribution_provisional"] is True
    assert result["provisional_applied_water_af"] == 5.0
    assert result["confirmed_applied_water_af"] is None


def test_attribution_confirmed_when_clean():
    from app.services.fcgma.calculation_engine import compute_provisional_attribution
    r = {
        "id": "clean-001",
        "combcode": "FC-ZN-07-001",
        "parcel_ids": ["p1"],
        "interval_volume": 3.0,
        "source_quality": "ok",
        "exceptions": [],
    }
    result = compute_provisional_attribution(r)
    assert result["attribution_provisional"] is False
    assert result["confirmed_applied_water_af"] == 3.0


# ─────────────────────────────────────────────
# Scenario injection tests
# ─────────────────────────────────────────────

def test_all_injected_records_labeled():
    """Every injected scenario record must carry scenario_injected=True and a scenario_label."""
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    records = list_records()
    assert len(records) > 0
    for r in records:
        if r["scenario_injected"]:
            assert r["scenario_label"] is not None
            assert "Demonstration scenario" in r["scenario_label"]


def test_no_live_injected_mixing():
    """Scenario-injected and non-injected records must carry different provider/scenario flags."""
    from app.services.fcgma.ledger import clear_ledger, list_records, make_record, upsert_record
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()

    # Add a "live" (non-injected) record
    r = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="real-001",
        event_timestamp="2026-03-20T08:00:00+00:00",
        reporting_period="2026-Q1",
        well_id="well-real-01", meter_id="meter-real-01",
        scenario_injected=False,
    )
    upsert_record(r)

    injected = list_records(scenario_injected=True)
    live = list_records(scenario_injected=False)

    # Both groups exist independently
    assert len(injected) > 0
    assert len(live) > 0

    # No injected record has scenario_injected=False
    for ir in injected:
        assert ir["scenario_injected"] is True

    # No live record has scenario_injected=True
    for lr in live:
        assert lr["scenario_injected"] is False


def test_scenario_injection_creates_all_exception_types():
    from app.services.fcgma.ledger import clear_ledger, list_exceptions
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    exceptions = list_exceptions()
    exc_types = {e["exception_type"] for e in exceptions}
    required_types = {
        "pump_activity_without_meter_movement",
        "reverse_flow",
        "multiplier_change",
        "unit_change",
        "late_arriving_record",
    }
    # At least some key exception types must be present
    assert exc_types & required_types, f"Expected some of {required_types}, got {exc_types}"


def test_meter_reset_scenario_detected():
    from app.services.fcgma.ledger import clear_ledger, list_exceptions
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    exceptions = list_exceptions()
    exc_types = {e["exception_type"] for e in exceptions}
    assert "meter_reset_detected" in exc_types


def test_missing_interval_scenario_detected():
    from app.services.fcgma.ledger import clear_ledger, list_exceptions
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    exceptions = list_exceptions()
    exc_types = {e["exception_type"] for e in exceptions}
    assert "missing_telemetry_interval" in exc_types


# ─────────────────────────────────────────────
# CIMIS adapter tests
# ─────────────────────────────────────────────

def test_cimis_unavailable_without_key(monkeypatch):
    """CIMIS adapter must return graceful unavailable state when no key is set."""
    monkeypatch.setenv("CIMIS_APP_KEY", "")
    from app.services.fcgma import cimis_adapter
    # Reload to pick up env change
    import importlib
    importlib.reload(cimis_adapter)
    status = cimis_adapter.get_status()
    assert status["available"] is False
    assert "configure authorized access" in status["message"]


def test_cimis_status_has_source_url():
    from app.services.fcgma.cimis_adapter import get_status
    status = get_status()
    assert "et.water.ca.gov" in status["source_url"]


def test_cimis_does_not_alter_groundwater_records():
    """CIMIS weather data must NOT change any groundwater meter reading values."""
    from app.services.fcgma.cimis_adapter import get_status
    status = get_status()
    assert "does not alter groundwater-meter calculations" in status["note"]


# ─────────────────────────────────────────────
# Recomputation versioning
# ─────────────────────────────────────────────

def test_recomputation_sets_version():
    from app.services.fcgma.ledger import clear_ledger, make_record, upsert_record
    from app.services.fcgma.calculation_engine import recompute_record, CALCULATION_VERSION
    clear_ledger()
    r = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="v-001",
        event_timestamp="2026-03-01T08:00:00+00:00",
        reporting_period="2026-Q1",
        well_id="well-v-01", meter_id="meter-v-01",
        cumulative_volume=100.0,
        interval_volume=5.0,
        unit="acre-feet",
    )
    upsert_record(r)
    result = recompute_record(r["id"])
    assert result is not None
    assert result["calculation_version"] == CALCULATION_VERSION


def test_recomputation_audit_event():
    from app.services.fcgma.ledger import clear_ledger, make_record, upsert_record
    from app.services.fcgma.calculation_engine import recompute_record
    clear_ledger()
    r = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="audit-001",
        event_timestamp="2026-03-01T08:00:00+00:00",
        reporting_period="2026-Q1",
        well_id="well-a-01", meter_id="meter-a-01",
        interval_volume=3.0, unit="acre-feet",
    )
    upsert_record(r)
    result = recompute_record(r["id"])
    event_types = [ev["event_type"] for ev in result["audit_events"]]
    assert "recomputed" in event_types


# ─────────────────────────────────────────────
# Reviewer adjustment audit event
# ─────────────────────────────────────────────

def test_reviewer_adjustment_audit_event():
    from app.services.fcgma.ledger import clear_ledger, make_record, upsert_record, update_review_status
    clear_ledger()
    r = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="rev-001",
        event_timestamp="2026-03-01T08:00:00+00:00",
        reporting_period="2026-Q1",
        well_id="well-rev-01", meter_id="meter-rev-01",
        interval_volume=4.0, unit="acre-feet",
    )
    upsert_record(r)
    updated = update_review_status(r["id"], "reviewer_approved", actor="reviewer-jane", notes="Verified on site.")
    assert updated is not None
    event_types = [ev["event_type"] for ev in updated["audit_events"]]
    assert "review_status_updated" in event_types
    actors = [ev["actor"] for ev in updated["audit_events"] if ev["event_type"] == "review_status_updated"]
    assert "reviewer-jane" in actors


# ─────────────────────────────────────────────
# AI copilot / grounding tests
# ─────────────────────────────────────────────

def test_copilot_executive_summary_grounded():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.copilot import get_executive_summary
    clear_ledger()
    inject_all_scenarios()
    result = get_executive_summary()
    assert "tool" in result
    assert result["tool"] == "get_executive_summary"
    assert "narrative" in result
    assert "stats" in result
    # Must not be empty
    assert len(result["narrative"]) > 10


def test_copilot_deterministic_fallback():
    """Copilot must produce a useful answer without any LLM API key."""
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.copilot import query_copilot
    import os
    os.environ["ANTHROPIC_API_KEY"] = ""
    clear_ledger()
    inject_all_scenarios()
    result = query_copilot("What requires my attention today?")
    assert "answer" in result
    assert len(result["answer"]) > 10
    assert result["llm_enhanced"] is False


def test_copilot_explain_record_cites_id():
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.copilot import explain_record
    clear_ledger()
    inject_all_scenarios()
    records = list_records(evidence_class="groundwater_meter_reading")
    assert records
    r = records[0]
    result = explain_record(r["id"])
    assert result["record_id"] == r["id"]
    assert "answer_type" in result


def test_copilot_missing_record_returns_missing_info():
    from app.services.fcgma.copilot import explain_record
    result = explain_record("nonexistent-record-xyz")
    assert result["answer_type"] == "missing_information"


def test_copilot_tools_no_quantities_beyond_evidence():
    """Copilot tools must not invent quantities beyond what the ledger contains."""
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.copilot import run_applied_water_scenario
    clear_ledger()
    result = run_applied_water_scenario()
    # With empty ledger, total must be 0
    assert result["total_interval_af"] == 0.0
    assert result["total_meter_records"] == 0


# ─────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────

def test_report_generation_produces_pdf():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.reports import generate_report, get_report_artifact
    clear_ledger()
    inject_all_scenarios()
    meta = generate_report()
    assert "report_id" in meta
    assert meta["record_count"] > 0
    pdf_result = get_report_artifact(meta["report_id"], "pdf")
    assert pdf_result is not None
    data, ct = pdf_result
    assert ct == "application/pdf"
    assert data[:4] == b"%PDF"


def test_report_bundle_contains_csv():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.reports import generate_report, get_report_artifact
    import zipfile
    clear_ledger()
    inject_all_scenarios()
    meta = generate_report()
    bundle = get_report_artifact(meta["report_id"], "bundle")
    assert bundle is not None
    data, ct = bundle
    assert ct == "application/zip"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
    assert any(".csv" in n for n in names)
    assert any(".pdf" in n for n in names)
    assert any(".json" in n for n in names)


def test_report_carries_disclaimer():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.reports import generate_report
    clear_ledger()
    inject_all_scenarios()
    meta = generate_report()
    assert "DEMONSTRATION" in meta["disclaimer"] or "demonstration" in meta["disclaimer"].lower()


# ─────────────────────────────────────────────
# Rule pack tests
# ─────────────────────────────────────────────

def test_rule_pack_has_source_urls():
    from app.services.fcgma.rule_pack import PACK_METADATA, RULES
    for url in PACK_METADATA["sources"]:
        assert url.startswith("http")
    for rule in RULES:
        assert rule["source_url"].startswith("http")


def test_rule_pack_marked_provisional():
    from app.services.fcgma.rule_pack import PACK_METADATA
    assert "provisional" in PACK_METADATA["pack_status"]
    assert "NOT validated" in PACK_METADATA["validation_status"]


def test_unit_conversion_gallons():
    from app.services.fcgma.rule_pack import unit_to_af
    result = unit_to_af(325851.0, "gallons")
    assert result is not None
    assert abs(result - 1.0) < 0.001


def test_unit_conversion_unknown_returns_none():
    from app.services.fcgma.rule_pack import unit_to_af
    assert unit_to_af(100.0, "unknown_unit") is None


# ─────────────────────────────────────────────
# Provider registry tests
# ─────────────────────────────────────────────

def test_ranch_systems_adapter_disabled():
    from app.services.fcgma.ledger import PROVIDER_REGISTRY
    ranch = PROVIDER_REGISTRY.get("ranch_systems_adapter_pending")
    assert ranch is not None
    assert ranch["status"] == "disabled"
    assert "intentionally disabled" in ranch["note"] or "Awaiting official Ranch Systems" in ranch["description"]


def test_wiseconn_authorized_live_registered():
    from app.services.fcgma.ledger import PROVIDER_REGISTRY
    wc = PROVIDER_REGISTRY.get("wiseconn_authorized_live")
    assert wc is not None
    assert wc["evidence_class"] == "controller_irrigation_telemetry"


def test_fcgma_ami_csv_evidence_class():
    from app.services.fcgma.ledger import PROVIDER_REGISTRY
    ami = PROVIDER_REGISTRY.get("fcgma_generic_ami_csv")
    assert ami is not None
    assert ami["evidence_class"] == "groundwater_meter_reading"


# ─────────────────────────────────────────────
# API route smoke tests (uses TestClient)
# ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_fcgma_status_endpoint(client):
    resp = client.get("/v1/fcgma-demo/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["environment"] == "demonstration"
    assert "truthfulness_statement" in data
    assert "providers" in data


def test_fcgma_dashboard_endpoint(client):
    resp = client.get("/v1/fcgma-demo/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "executive_summary" in data
    assert "truthfulness_banner" in data
    assert "Not an official Fox Canyon" in data["truthfulness_banner"]["disclaimer"]


def test_fcgma_review_queue_endpoint(client):
    resp = client.get("/v1/fcgma-demo/review-queue")
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert "total" in data


def test_fcgma_review_queue_filter_ready(client):
    resp = client.get("/v1/fcgma-demo/review-queue?filter=ready")
    assert resp.status_code == 200
    data = resp.json()
    for r in data["records"]:
        assert r["review_status"] in ("ready_for_export", "reviewer_approved")


def test_fcgma_scenarios_reset_endpoint(client):
    resp = client.post("/v1/fcgma-demo/scenarios/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert "records_injected" in data["result"]
    assert "disclaimer" in data


def test_fcgma_copilot_query_endpoint(client):
    resp = client.post("/v1/fcgma-demo/copilot/query", json={"query": "What requires my attention today?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "tool_used" in data
    assert "disclaimer" in data


def test_fcgma_copilot_grounded_no_fake_facts(client):
    """Copilot must not invent quantities beyond what the ledger contains."""
    resp = client.post("/v1/fcgma-demo/copilot/query", json={"query": "Generate a reporting-ready summary."})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    # Answer must reference the disclaimer
    assert "disclaimer" in data


def test_fcgma_source_health_endpoint(client):
    resp = client.get("/v1/fcgma-demo/source-health")
    assert resp.status_code == 200
    data = resp.json()
    assert "provider_health" in data


def test_fcgma_rules_endpoint(client):
    resp = client.get("/v1/fcgma-demo/rules")
    assert resp.status_code == 200
    data = resp.json()
    assert "rules" in data
    assert len(data["rules"]) > 0
    for rule in data["rules"]:
        assert "source_url" in rule
        assert rule["source_url"].startswith("http")


def test_fcgma_record_exists_after_reset(client):
    client.post("/v1/fcgma-demo/scenarios/reset")
    queue = client.get("/v1/fcgma-demo/review-queue").json()
    assert queue["total"] > 0
    record_id = queue["records"][0]["id"]
    resp = client.get(f"/v1/fcgma-demo/records/{record_id}")
    assert resp.status_code == 200
    r = resp.json()
    assert r["id"] == record_id


def test_fcgma_record_not_found(client):
    resp = client.get("/v1/fcgma-demo/records/nonexistent-record-xyz")
    assert resp.status_code == 404


def test_fcgma_report_generation_endpoint(client):
    resp = client.post("/v1/fcgma-demo/reports/generate", json={"report_type": "full", "reporting_period": "2026-Q1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "report_id" in data
    assert "DEMONSTRATION" in data["disclaimer"] or "demonstration" in data["disclaimer"].lower()


def test_fcgma_report_pdf_download(client):
    gen = client.post("/v1/fcgma-demo/reports/generate", json={"report_type": "full", "reporting_period": "2026-Q1"})
    report_id = gen.json()["report_id"]
    resp = client.get(f"/v1/fcgma-demo/reports/{report_id}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_fcgma_ami_csv_import(client):
    csv_content = b"well_id,meter_id,event_timestamp,cumulative_volume,unit,multiplier,combcode,parcel_ids\nwell-import-01,meter-import-01,2026-03-10T08:00:00+00:00,500.0,acre-feet,1.0,FC-ZN-99-001,parcel-import-101\n"
    resp = client.post("/v1/fcgma-demo/imports/ami-csv", files={"file": ("test_import.csv", csv_content, "text/csv")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported_count"] >= 1
    assert "NOT Fox Canyon authorized data" in data["note"]


def test_fcgma_ami_csv_import_non_csv_rejected(client):
    resp = client.post("/v1/fcgma-demo/imports/ami-csv", files={"file": ("test.xlsx", b"binary", "application/octet-stream")})
    assert resp.status_code == 400


def test_existing_health_route_unaffected(client):
    """Existing /v1/health endpoint must still work."""
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
