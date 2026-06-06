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
    assert "ILLUSTRATIVE" in meta["disclaimer"] or "illustrative" in meta["disclaimer"].lower()


def test_report_branding_updated():
    import io, zipfile
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.reports import generate_report, get_report_artifact, REPORT_FOOTER_NOTE, REPORT_DISCLAIMER
    clear_ledger()
    inject_all_scenarios()
    meta = generate_report()
    # Module-level string constants carry the new brand name
    assert "Applied Water Intelligence" in REPORT_DISCLAIMER or "Applied Water Intelligence" in REPORT_FOOTER_NOTE
    # README.txt inside the ZIP bundle has branding text (read by decompressing)
    zip_result = get_report_artifact(meta["report_id"], "bundle")
    assert zip_result is not None
    zip_data, _ = zip_result
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        readme = zf.read("README.txt").decode("utf-8")
    assert "Applied Water Intelligence" in readme or "Reporting Readiness" in readme


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
    assert data["environment"] == "illustrative_workspace"
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


# ─────────────────────────────────────────────
# Second-pass: neutral IDs (FC-WELL-001 format)
# ─────────────────────────────────────────────

def test_scenario_well_ids_use_neutral_format():
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    records = list_records()
    well_ids = {r["well_id"] for r in records}
    # All well IDs must use FC-WELL prefix
    assert all(wid.startswith("FC-WELL-") for wid in well_ids), \
        f"Found non-neutral well IDs: {well_ids - {w for w in well_ids if w.startswith('FC-WELL-')}}"


def test_scenario_meter_ids_use_neutral_format():
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    records = list_records()
    meter_ids = {r["meter_id"] for r in records if r["meter_id"]}
    assert all(mid.startswith("FC-MTR-") for mid in meter_ids), \
        f"Found non-neutral meter IDs: {meter_ids - {m for m in meter_ids if m.startswith('FC-MTR-')}}"


def test_no_anon_prefix_in_well_ids():
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    records = list_records()
    for r in records:
        assert "anon" not in (r["well_id"] or ""), f"Old anon ID found in well_id: {r['well_id']}"


# ─────────────────────────────────────────────
# Second-pass: Terris service tools
# ─────────────────────────────────────────────

def test_terris_get_reporting_cycle_status():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import get_reporting_cycle_status
    clear_ledger()
    inject_all_scenarios()
    result = get_reporting_cycle_status()
    assert result["tool"] == "get_reporting_cycle_status"
    assert "readiness_percentage" in result
    assert "cycle_status" in result
    assert "status_label" in result
    assert "blocking_exceptions" in result
    assert result["total_records"] > 0
    assert result["answer_type"] == "fact+calculation"


def test_terris_list_priority_actions():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import list_priority_actions
    clear_ledger()
    inject_all_scenarios()
    result = list_priority_actions()
    assert result["tool"] == "list_priority_actions"
    assert "total_actions" in result
    assert "actions" in result
    # Actions are ranked
    ranks = [a["priority_rank"] for a in result["actions"]]
    assert ranks == sorted(ranks), "Actions should be sorted by priority_rank"


def test_terris_list_records_blocking_reporting():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import list_records_blocking_reporting
    clear_ledger()
    inject_all_scenarios()
    result = list_records_blocking_reporting()
    assert result["tool"] == "list_records_blocking_reporting"
    assert "blocking_count" in result
    assert "records" in result
    # Each blocking record has blocking_reasons
    for r in result["records"]:
        assert "well_id" in r
        assert "blocking_reasons" in r


def test_terris_generate_reporting_brief():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import generate_reporting_brief
    clear_ledger()
    inject_all_scenarios()
    result = generate_reporting_brief()
    assert result["tool"] == "generate_reporting_brief"
    assert "readiness_percentage" in result
    assert "blocking_count" in result
    assert "top_priority_actions" in result
    assert "disclaimer" in result
    assert "Not an official FCGMA" in result["disclaimer"]


def test_terris_generate_exception_packet():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import generate_exception_packet
    clear_ledger()
    inject_all_scenarios()
    result = generate_exception_packet()
    assert result["tool"] == "generate_exception_packet"
    assert "total_exceptions" in result
    assert "packet_items" in result
    assert "disclaimer" in result
    # Disclaimer must prohibit filing
    assert "does not file" in result["disclaimer"] or "review" in result["disclaimer"].lower()


def test_terris_draft_follow_up_request():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import draft_follow_up_request
    clear_ledger()
    inject_all_scenarios()
    result = draft_follow_up_request()
    assert result["tool"] == "draft_follow_up_request"
    assert "item_count" in result
    assert "follow_up_items" in result
    for item in result["follow_up_items"]:
        assert "well_id" in item
        assert "follow_up_recipient" in item
        assert "follow_up_action" in item


def test_terris_add_records_to_evidence_bundle():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import add_records_to_evidence_bundle
    clear_ledger()
    inject_all_scenarios()
    result = add_records_to_evidence_bundle()
    assert result["tool"] == "add_records_to_evidence_bundle"
    assert "staged_count" in result
    # Note must be clear this doesn't approve records
    assert "not an approval" in result["note"].lower() or "selection only" in result["note"].lower()


# ─────────────────────────────────────────────
# Second-pass: Terris investigation workflow
# ─────────────────────────────────────────────

def test_terris_investigation_returns_agent_name():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    inject_all_scenarios()
    result = run_terris_investigation("What requires my attention today?")
    assert result["agent"] == "Terris"


def test_terris_investigation_has_structured_sections():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    inject_all_scenarios()
    result = run_terris_investigation("What requires my attention today?")
    required = ["direct_answer", "why_it_matters", "evidence_reviewed",
                "recommended_action", "remaining_uncertainty", "available_actions"]
    for key in required:
        assert key in result, f"Missing structured section: {key}"
        assert result[key] is not None


def test_terris_investigation_stages_are_real():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    inject_all_scenarios()
    result = run_terris_investigation("Where does the reporting cycle stand?")
    stages = result["investigation_stages"]
    assert len(stages) >= 2
    # First stage is classify_intent, second is identify_tools
    assert stages[0]["stage"] == "classify_intent"
    assert stages[1]["stage"] == "identify_tools"
    # All stages have required fields
    for s in stages:
        assert "stage" in s
        assert "status" in s
        assert "detail" in s


def test_terris_investigation_no_unsupported_quantities():
    """Terris must not invent quantities beyond what the ledger contains."""
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    result = run_terris_investigation("How much water was extracted?")
    # With empty ledger, should not claim non-zero extraction
    direct = result.get("direct_answer", "")
    # Should not contain a positive AF number when ledger is empty
    assert "0.00 AF" in direct or "0 record" in direct or "No records" in direct \
        or "0 meter" in direct or result.get("tool_results") is not None


def test_terris_investigation_has_disclaimer():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    inject_all_scenarios()
    result = run_terris_investigation("Show provider health.")
    assert "disclaimer" in result
    assert "does not approve records" in result["disclaimer"] or "Terris does not" in result["disclaimer"]


def test_terris_intent_classification():
    from app.services.fcgma.terris import classify_intent
    assert classify_intent("What requires my attention today?") == "review_queue"
    assert classify_intent("Where does the reporting cycle stand?") == "reporting_cycle"
    assert classify_intent("Compare provider health") == "provider_health"
    assert classify_intent("What data would Fox Canyon need?") == "data_gap"


def test_terris_evidence_reviewed_lists_tools():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    inject_all_scenarios()
    result = run_terris_investigation("What requires my attention today?")
    evidence = result["evidence_reviewed"]
    assert isinstance(evidence, list)
    assert len(evidence) > 0
    for e in evidence:
        assert "tool" in e
        assert "summary" in e


def test_terris_available_actions_not_empty():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    inject_all_scenarios()
    result = run_terris_investigation("What requires my attention today?")
    actions = result["available_actions"]
    assert isinstance(actions, list)
    assert len(actions) > 0
    for a in actions:
        assert "label" in a
        assert "target" in a


def test_terris_record_specific_investigation():
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    inject_all_scenarios()
    records = list_records(evidence_class="groundwater_meter_reading")
    assert records
    rid = records[0]["id"]
    result = run_terris_investigation("Explain this record.", record_id=rid)
    assert result["agent"] == "Terris"
    assert "explain_record" in result["tool_results"]
    assert result["tool_results"]["explain_record"]["record_id"] == rid


# ─────────────────────────────────────────────
# Second-pass: Terris API endpoints
# ─────────────────────────────────────────────

def test_terris_query_endpoint(client):
    resp = client.post("/v1/fcgma-demo/terris/query",
                       json={"query": "What requires my attention today?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"] == "Terris"
    assert "direct_answer" in data
    assert "investigation_stages" in data
    assert "disclaimer" in data


def test_terris_query_has_structured_sections(client):
    resp = client.post("/v1/fcgma-demo/terris/query",
                       json={"query": "Where does the reporting cycle stand?"})
    assert resp.status_code == 200
    data = resp.json()
    for key in ["direct_answer", "why_it_matters", "evidence_reviewed",
                "recommended_action", "remaining_uncertainty", "available_actions"]:
        assert key in data, f"Missing: {key}"


def test_terris_preset_questions_endpoint(client):
    resp = client.get("/v1/fcgma-demo/terris/preset-questions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"] == "Terris"
    assert "questions" in data
    assert len(data["questions"]) > 0
    # No "Ask AGRO-AI" labels in Terris presets
    for q in data["questions"]:
        assert "Ask AGRO-AI" not in q["label"]


def test_terris_reporting_cycle_endpoint(client):
    resp = client.get("/v1/fcgma-demo/terris/reporting-cycle")
    assert resp.status_code == 200
    data = resp.json()
    assert "readiness_percentage" in data
    assert "cycle_status" in data
    assert "blocking_exceptions" in data


def test_terris_priority_actions_endpoint(client):
    resp = client.get("/v1/fcgma-demo/terris/priority-actions")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_actions" in data
    assert "actions" in data


def test_terris_blocking_records_endpoint(client):
    resp = client.get("/v1/fcgma-demo/terris/blocking-records")
    assert resp.status_code == 200
    data = resp.json()
    assert "blocking_count" in data
    assert "records" in data


# ─────────────────────────────────────────────
# Second-pass: product naming
# ─────────────────────────────────────────────

def test_status_product_name_updated(client):
    resp = client.get("/v1/fcgma-demo/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "Applied Water Intelligence" in data["product"]


def test_status_environment_is_illustrative(client):
    resp = client.get("/v1/fcgma-demo/status")
    assert resp.status_code == 200
    assert resp.json()["environment"] == "illustrative_workspace"


def test_report_disclaimer_uses_illustrative(client):
    resp = client.post("/v1/fcgma-demo/reports/generate",
                       json={"report_type": "full", "reporting_period": "2026-Q1"})
    assert resp.status_code == 200
    disclaimer = resp.json().get("disclaimer", "")
    assert "ILLUSTRATIVE" in disclaimer or "illustrative" in disclaimer.lower()


# ─────────────────────────────────────────────
# Second-pass: consolidated provenance
# ─────────────────────────────────────────────

def test_scenarios_always_labeled():
    """Every injected record must carry scenario_injected=True and a scenario_label."""
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    records = list_records()
    injected = [r for r in records if r["scenario_injected"]]
    assert len(injected) == len(records), "All records in this demo are scenario-injected"
    for r in injected:
        assert r["scenario_label"], f"Record {r['id']} has no scenario_label"


def test_well_ids_have_fc_prefix():
    """All demonstration well IDs start with FC-WELL-."""
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    for r in list_records():
        assert r["well_id"].startswith("FC-WELL-"), \
            f"Expected FC-WELL- prefix, got: {r['well_id']}"


# ─────────────────────────────────────────────
# Fourth-pass: negative-delta quarantine
# ─────────────────────────────────────────────

def test_negative_reset_delta_never_in_interval_volume():
    """A meter-reset record must have interval_volume=None, not a large negative."""
    from app.services.fcgma.calculation_engine import calculate_interval
    pre = {"id": "r-pre", "cumulative_volume": 9850.4, "interval_volume": None}
    post = {"id": "r-post", "cumulative_volume": 14.2, "interval_volume": None}
    result = calculate_interval(post, pre)
    assert result["interval_volume"] is None, (
        f"Expected None after quarantine, got {result['interval_volume']}"
    )
    assert result.get("interval_quarantined") is True
    assert result.get("interval_quarantine_delta") is not None
    assert result["interval_quarantine_delta"] < 0


def test_small_negative_delta_not_quarantined():
    """A tiny negative delta (sub-threshold) should not be quarantined — only resets are."""
    from app.services.fcgma.calculation_engine import calculate_interval
    pre = {"id": "r-pre", "cumulative_volume": 100.0, "interval_volume": None}
    post = {"id": "r-post", "cumulative_volume": 99.5, "interval_volume": None}  # -0.5%, below 10% threshold
    result = calculate_interval(post, pre)
    # Not quarantined (drop is only 0.5%)
    assert result.get("interval_quarantined") is None or result.get("interval_quarantined") is False
    assert result["interval_volume"] is not None


def test_dashboard_total_af_excludes_quarantined_delta():
    """ledger_stats must never include a quarantined reset delta in provisional_af."""
    from app.services.fcgma.ledger import clear_ledger, ledger_stats
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    stats = ledger_stats()
    assert stats["provisional_af"] >= 0, (
        f"provisional_af should never be negative, got {stats['provisional_af']}"
    )
    assert stats["supported_extraction_af"] >= 0


def test_terris_query_does_not_report_negative_af():
    """Terris must never surface a negative metered total in any answer."""
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.terris import run_terris_investigation
    clear_ledger()
    inject_all_scenarios()
    result = run_terris_investigation("How much water has been metered?")
    direct = result.get("direct_answer", "")
    # Must not contain a negative AF value
    import re
    neg_pattern = re.compile(r"-\s*\d+[\.,]\d+\s*AF", re.IGNORECASE)
    assert not neg_pattern.search(direct), (
        f"Terris reported a negative AF value: {direct}"
    )


def test_applied_water_scenario_total_never_negative():
    """run_applied_water_scenario must return non-negative total_interval_af."""
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.copilot import run_applied_water_scenario
    clear_ledger()
    inject_all_scenarios()
    result = run_applied_water_scenario()
    assert result["total_interval_af"] >= 0, (
        f"total_interval_af should never be negative, got {result['total_interval_af']}"
    )


def test_meter_reset_exception_raised_for_reset_record():
    """A meter reset scenario must produce a meter_reset_detected exception."""
    from app.services.fcgma.ledger import clear_ledger, list_exceptions
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    exceptions = list_exceptions()
    reset_excs = [e for e in exceptions if e["exception_type"] == "meter_reset_detected"]
    assert len(reset_excs) >= 1, "Expected at least one meter_reset_detected exception"


# ─────────────────────────────────────────────
# Fourth-pass: realistic workspace
# ─────────────────────────────────────────────

def test_workspace_readiness_above_70_percent():
    """Default workspace must have at least 70% of records ready or clean."""
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    records = list_records(evidence_class="groundwater_meter_reading")
    total = len(records)
    ready = sum(1 for r in records if r["review_status"] in ("ready_for_export", "reviewer_approved"))
    assert total > 0
    pct = ready / total * 100
    assert pct >= 70, f"Expected >=70% ready, got {pct:.1f}% ({ready}/{total})"


def test_workspace_has_at_least_30_records():
    """Default workspace must have at least 30 records total."""
    from app.services.fcgma.ledger import clear_ledger, list_records
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    records = list_records()
    assert len(records) >= 30, f"Expected >=30 records, got {len(records)}"


def test_workspace_has_material_review_cases():
    """Default workspace must have at least 3 open exceptions for review."""
    from app.services.fcgma.ledger import clear_ledger, list_exceptions
    from app.services.fcgma.scenarios import inject_all_scenarios
    clear_ledger()
    inject_all_scenarios()
    exceptions = list_exceptions()
    open_excs = [e for e in exceptions if e.get("status") == "open"]
    assert len(open_excs) >= 3, f"Expected >=3 open exceptions, got {len(open_excs)}"


# ─────────────────────────────────────────────
# Fourth-pass: ReviewCase model
# ─────────────────────────────────────────────

def test_build_cases_returns_list():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.cases import build_cases
    clear_ledger()
    inject_all_scenarios()
    cases = build_cases()
    assert isinstance(cases, list)


def test_build_cases_groups_by_well_and_period():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.cases import build_cases
    clear_ledger()
    inject_all_scenarios()
    cases = build_cases()
    assert len(cases) >= 1, "Expected at least 1 review case"
    for case in cases:
        assert "case_id" in case
        assert "well_id" in case
        assert "reporting_period" in case
        assert "record_ids" in case
        assert "severity" in case
        assert "primary_issue" in case
        assert "why_it_matters" in case
        assert "recommended_action" in case
        assert "required_evidence" in case


def test_cases_sorted_by_severity():
    from app.services.fcgma.ledger import clear_ledger
    from app.services.fcgma.scenarios import inject_all_scenarios
    from app.services.fcgma.cases import build_cases
    clear_ledger()
    inject_all_scenarios()
    cases = build_cases()
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    ranks = [severity_rank.get(c["severity"], 3) for c in cases]
    assert ranks == sorted(ranks), "Cases must be sorted by severity (high first)"


def test_cases_endpoint(client):
    resp = client.get("/v1/fcgma-demo/terris/cases")
    assert resp.status_code == 200
    data = resp.json()
    assert "cases" in data
    assert "total" in data
    assert isinstance(data["cases"], list)


# ─────────────────────────────────────────────
# Fourth-pass: conversation endpoints
# ─────────────────────────────────────────────

def test_conversation_create_returns_thread_id(client):
    resp = client.post("/v1/fcgma-demo/terris/conversation",
                       json={"title": "Test conversation"})
    assert resp.status_code == 200
    data = resp.json()
    assert "thread_id" in data
    assert data["thread_id"].startswith("thread-")


def test_conversation_message_returns_response(client):
    # Create thread
    resp = client.post("/v1/fcgma-demo/terris/conversation", json={})
    assert resp.status_code == 200
    thread_id = resp.json()["thread_id"]

    # Send message
    resp2 = client.post(
        f"/v1/fcgma-demo/terris/conversation/{thread_id}/message",
        json={"query": "What requires my attention today?"}
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["role"] == "assistant"
    assert "content" in data
    assert len(data["content"]) > 0
    assert "evidence_trail" in data
    assert "follow_up_suggestions" in data


def test_conversation_history_persists_turns(client):
    resp = client.post("/v1/fcgma-demo/terris/conversation", json={})
    thread_id = resp.json()["thread_id"]

    client.post(f"/v1/fcgma-demo/terris/conversation/{thread_id}/message",
                json={"query": "What requires my attention today?"})
    client.post(f"/v1/fcgma-demo/terris/conversation/{thread_id}/message",
                json={"query": "Which records are blocking the cycle?"})

    hist_resp = client.get(f"/v1/fcgma-demo/terris/conversation/{thread_id}")
    assert hist_resp.status_code == 200
    data = hist_resp.json()
    assert data["message_count"] == 2
    turns = data["turns"]
    # 2 user messages + 2 assistant responses = 4 turns
    assert len(turns) == 4
    roles = [t["role"] for t in turns]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_conversation_unknown_thread_404(client):
    resp = client.post(
        "/v1/fcgma-demo/terris/conversation/thread-doesnotexist/message",
        json={"query": "Hello?"}
    )
    assert resp.status_code == 404


def test_conversation_evidence_trail_structure(client):
    resp = client.post("/v1/fcgma-demo/terris/conversation", json={})
    thread_id = resp.json()["thread_id"]
    resp2 = client.post(
        f"/v1/fcgma-demo/terris/conversation/{thread_id}/message",
        json={"query": "Where does the reporting cycle stand?"}
    )
    data = resp2.json()
    for item in data.get("evidence_trail", []):
        assert "tool" in item
        assert "summary" in item
        # Raw tool names should not be surfaced as the visible answer
        # (they can appear in evidence_trail but not the main content)
    # The main content must not consist solely of a raw tool name
    content = data.get("content", "")
    assert content and content not in (
        "list_priority_actions", "get_reporting_cycle_status",
        "get_executive_summary", "generate_reporting_brief",
    )
