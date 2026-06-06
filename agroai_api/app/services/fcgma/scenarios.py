"""Demo scenario injection for the FCGMA Water Intelligence Copilot.

Every injected record carries:
  scenario_injected = True
  scenario_label = "Demonstration scenario injected to illustrate exception handling."

These records are NEVER mixed silently with live or authorized records.

Default workspace: ~42 records across 8 wells, ~80-85% reporting-ready,
5 material review cases illustrating the most common FCGMA exception types.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .ledger import clear_ledger, make_record, upsert_record
from .calculation_engine import run_full_calculation_pass

SCENARIO_LABEL = "Demonstration scenario injected to illustrate exception handling."
REPORTING_PERIOD = "2026-Q1"

# Neutral anonymized well/meter IDs for demonstration
_WELLS = {
    "W001": {"well_id": "FC-WELL-001", "meter_id": "FC-MTR-001", "combcode": "FC-ZN-07-001"},
    "W002": {"well_id": "FC-WELL-002", "meter_id": "FC-MTR-002", "combcode": "FC-ZN-07-002"},
    "W003": {"well_id": "FC-WELL-003", "meter_id": "FC-MTR-003", "combcode": None},  # unresolved CombCode
    "W004": {"well_id": "FC-WELL-004", "meter_id": "FC-MTR-004", "combcode": "FC-ZN-12-001"},
    "W005": {"well_id": "FC-WELL-005", "meter_id": "FC-MTR-005", "combcode": "FC-ZN-12-002"},
    "W006": {"well_id": "FC-WELL-006", "meter_id": "FC-MTR-006", "combcode": "FC-ZN-08-001"},
    "W007": {"well_id": "FC-WELL-007", "meter_id": "FC-MTR-007", "combcode": "FC-ZN-08-002"},
    "W008": {"well_id": "FC-WELL-008", "meter_id": "FC-MTR-008", "combcode": "FC-ZN-15-001"},
}


def _ts(days_ago: int = 0, hours: int = 0) -> str:
    t = datetime(2026, 3, 15, 8, 0, 0, tzinfo=timezone.utc)
    t -= timedelta(days=days_ago, hours=hours)
    return t.isoformat()


def _clean(w: str, external_id: str, days_ago: int, hours: int,
           cumulative: float, interval: float, parcel: str) -> dict[str, Any]:
    """Helper: build a clean, ready-for-export meter reading."""
    well = _WELLS[w]
    return make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id=external_id,
        event_timestamp=_ts(days_ago, hours),
        reporting_period=REPORTING_PERIOD,
        well_id=well["well_id"],
        meter_id=well["meter_id"],
        combcode=well["combcode"],
        parcel_ids=[parcel],
        cumulative_volume=cumulative,
        interval_volume=interval,
        unit="acre-feet",
        unit_original="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        review_status="ready_for_export",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "provider": "fcgma_generic_ami_csv",
            "external_source_id": external_id,
            "retrieval_method": "demo_ami_csv_import",
        },
    )


def inject_all_scenarios() -> dict[str, Any]:
    """Clear the ledger and inject a complete demonstration dataset.

    Default workspace:
    - 8 wells, 42 records total
    - ~35 records are clean/ready (≥80% readiness)
    - 5 material review cases for exception-handling illustration
    - Scenario library accessible via internal provenance-drawer controls only
    """
    clear_ledger()

    records: list[dict[str, Any]] = []

    # ══════════════════════════════════════════════════════════════════
    # SECTION A — CLEAN, REPORTING-READY RECORDS (~35 records)
    # ══════════════════════════════════════════════════════════════════

    # Well 1 — FC-WELL-001 — 6 quarterly readings, all clean
    records += [
        _clean("W001", "ami-q1-001-01", 90, 0, 1100.0, 11.2, "FC-PCL-101"),
        _clean("W001", "ami-q1-001-02", 75, 0, 1111.2, 10.8, "FC-PCL-101"),
        _clean("W001", "ami-q1-001-03", 60, 0, 1122.0, 12.1, "FC-PCL-101"),
        _clean("W001", "ami-q1-001-04", 45, 0, 1134.1, 11.5, "FC-PCL-101"),
        _clean("W001", "ami-q1-001-05", 30, 0, 1145.6, 10.9, "FC-PCL-101"),
        _clean("W001", "ami-q1-001-06", 15, 0, 1156.5, 11.3, "FC-PCL-101"),
    ]

    # Well 4 — FC-WELL-004 — 6 readings, all clean
    records += [
        _clean("W004", "ami-q1-004-01", 88, 0, 420.0, 8.4, "FC-PCL-104"),
        _clean("W004", "ami-q1-004-02", 73, 0, 428.4, 7.9, "FC-PCL-104"),
        _clean("W004", "ami-q1-004-03", 58, 0, 436.3, 8.2, "FC-PCL-104"),
        _clean("W004", "ami-q1-004-04", 43, 0, 444.5, 8.6, "FC-PCL-104"),
        _clean("W004", "ami-q1-004-05", 28, 0, 453.1, 8.1, "FC-PCL-104"),
        _clean("W004", "ami-q1-004-06", 13, 0, 461.2, 8.3, "FC-PCL-104"),
    ]

    # Well 5 — FC-WELL-005 — 6 readings, all clean
    records += [
        _clean("W005", "ami-q1-005-01", 87, 0, 60.0, 4.2, "FC-PCL-105"),
        _clean("W005", "ami-q1-005-02", 72, 0, 64.2, 3.9, "FC-PCL-105"),
        _clean("W005", "ami-q1-005-03", 57, 0, 68.1, 4.1, "FC-PCL-105"),
        _clean("W005", "ami-q1-005-04", 42, 0, 72.2, 4.0, "FC-PCL-105"),
        _clean("W005", "ami-q1-005-05", 27, 0, 76.2, 4.3, "FC-PCL-105"),
        _clean("W005", "ami-q1-005-06", 12, 0, 80.5, 4.1, "FC-PCL-105"),
    ]

    # Well 6 — FC-WELL-006 — 5 readings, all clean
    records += [
        _clean("W006", "ami-q1-006-01", 85, 0, 800.0, 9.8, "FC-PCL-106"),
        _clean("W006", "ami-q1-006-02", 70, 0, 809.8, 9.5, "FC-PCL-106"),
        _clean("W006", "ami-q1-006-03", 55, 0, 819.3, 10.1, "FC-PCL-106"),
        _clean("W006", "ami-q1-006-04", 40, 0, 829.4, 9.7, "FC-PCL-106"),
        _clean("W006", "ami-q1-006-05", 25, 0, 839.1, 9.9, "FC-PCL-106"),
    ]

    # Well 7 — FC-WELL-007 — 5 readings, all clean
    records += [
        _clean("W007", "ami-q1-007-01", 84, 0, 340.0, 6.8, "FC-PCL-107"),
        _clean("W007", "ami-q1-007-02", 69, 0, 346.8, 6.5, "FC-PCL-107"),
        _clean("W007", "ami-q1-007-03", 54, 0, 353.3, 7.0, "FC-PCL-107"),
        _clean("W007", "ami-q1-007-04", 39, 0, 360.3, 6.7, "FC-PCL-107"),
        _clean("W007", "ami-q1-007-05", 24, 0, 367.0, 6.9, "FC-PCL-107"),
    ]

    # Well 8 — FC-WELL-008 — 4 readings, all clean
    records += [
        _clean("W008", "ami-q1-008-01", 82, 0, 220.0, 5.5, "FC-PCL-108"),
        _clean("W008", "ami-q1-008-02", 67, 0, 225.5, 5.3, "FC-PCL-108"),
        _clean("W008", "ami-q1-008-03", 52, 0, 230.8, 5.6, "FC-PCL-108"),
        _clean("W008", "ami-q1-008-04", 37, 0, 236.4, 5.4, "FC-PCL-108"),
    ]

    # ── WiseConn controller telemetry (clean, illustrative only) ──
    r_wc1 = make_record(
        evidence_class="controller_irrigation_telemetry",
        provider="wiseconn_sanitized_replay",
        external_source_id="wc-irr-2026-w001",
        event_timestamp=_ts(20, 6),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        pump_status="running",
        cumulative_volume=None,
        interval_volume=None,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "provider": "wiseconn_sanitized_replay",
            "note": (
                "WiseConn controller telemetry — anonymized sanitized replay. "
                "Records irrigation schedule events only. "
                "Does NOT represent groundwater extraction volumes."
            ),
        },
    )
    records.append(r_wc1)

    r_wc2 = make_record(
        evidence_class="controller_irrigation_telemetry",
        provider="wiseconn_sanitized_replay",
        external_source_id="wc-irr-2026-w006",
        event_timestamp=_ts(22, 4),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W006"]["well_id"],
        meter_id=_WELLS["W006"]["meter_id"],
        pump_status="running",
        cumulative_volume=None,
        interval_volume=None,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "provider": "wiseconn_sanitized_replay",
            "note": "WiseConn controller telemetry — anonymized sanitized replay.",
        },
    )
    records.append(r_wc2)

    # ══════════════════════════════════════════════════════════════════
    # SECTION B — REVIEW CASES (5 material exceptions)
    # Each case is a coherent group illustrating a real FCGMA exception type.
    # ══════════════════════════════════════════════════════════════════

    # ── Case 1: METER RESET — Well 2 ──────────────────────────────
    # Pre-reset reading
    r_reset_pre = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case1-reset-pre",
        event_timestamp=_ts(20),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W002"]["well_id"],
        meter_id=_WELLS["W002"]["meter_id"],
        combcode=_WELLS["W002"]["combcode"],
        parcel_ids=["FC-PCL-102"],
        cumulative_volume=9850.4,
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case1_meter_reset_pre_reading"},
    )
    records.append(r_reset_pre)

    # Post-reset reading — cumulative drops from 9850.4 to 14.2 (meter replaced)
    # The large negative delta will be quarantined by calculate_interval.
    r_reset_post = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case1-reset-post",
        event_timestamp=_ts(19),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W002"]["well_id"],
        meter_id=_WELLS["W002"]["meter_id"],
        combcode=_WELLS["W002"]["combcode"],
        parcel_ids=["FC-PCL-102"],
        cumulative_volume=14.2,  # Meter replaced — reset to near-zero
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        review_status="requires_attention",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case1_meter_reset_post_reading"},
        exceptions=[{
            "id": "exc-case1-reset-01",
            "exception_type": "meter_reset_detected",
            "severity": "high",
            "detail": (
                "Cumulative volume dropped from 9850.4 to 14.2 AF (99.9% drop). "
                "Likely meter replacement. Agency notification required per FCGMA rule fcgma-fm-004. "
                "Demonstration scenario injected to illustrate exception handling."
            ),
            "rule_id": "fcgma-fm-004",
            "status": "open",
        }],
    )
    records.append(r_reset_post)

    # Two clean post-replacement readings for Well 2
    records += [
        _clean("W002", "ami-case1-clean-01", 15, 0, 22.5, 8.3, "FC-PCL-102"),
        _clean("W002", "ami-case1-clean-02", 10, 0, 30.8, 7.9, "FC-PCL-102"),
    ]

    # ── Case 2: TELEMETRY GAP — Well 1, mid-cycle ─────────────────
    # Normal reading before gap (at day 35 — outside the clean series which ends at day 15)
    r_gap_pre = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case2-gap-pre",
        event_timestamp=_ts(35, 0),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        combcode=_WELLS["W001"]["combcode"],
        parcel_ids=["FC-PCL-101"],
        cumulative_volume=1100.0,
        interval_volume=6.1,
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case2_gap_pre"},
    )
    records.append(r_gap_pre)

    # Reading after 18-day (432-hour) gap — triggers missing_telemetry_interval exception.
    # 432 hours > 400-hour threshold used in recompute_record.
    r_gap_post = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case2-gap-post",
        event_timestamp=_ts(17, 0),  # 18-day gap from r_gap_pre
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        combcode=_WELLS["W001"]["combcode"],
        parcel_ids=["FC-PCL-101"],
        cumulative_volume=1125.0,
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        review_status="requires_attention",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case2_gap_post"},
        exceptions=[{
            "id": "exc-case2-gap-01",
            "exception_type": "missing_telemetry_interval",
            "severity": "high",
            "detail": (
                "432.0-hour gap between meter readings. Expected maximum gap is 16 days. "
                "Extraction may have occurred during the gap period. "
                "Demonstration scenario injected to illustrate exception handling."
            ),
            "rule_id": "fcgma-fm-001",
            "status": "open",
        }],
    )
    records.append(r_gap_post)

    # Pump state evidence during the gap period
    r_pump_gap = make_record(
        evidence_class="pump_state_evidence",
        provider="wiseconn_sanitized_replay",
        external_source_id="wc-pump-case2-gap",
        event_timestamp=_ts(26, 12),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        pump_status="running",
        cumulative_volume=None,
        interval_volume=None,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "provider": "wiseconn_sanitized_replay",
            "scenario": "case2_pump_during_gap",
            "note": "Pump was running during the meter telemetry gap. Extraction estimate may be required.",
        },
        exceptions=[{
            "id": "exc-case2-pump-01",
            "exception_type": "pump_activity_without_meter_movement",
            "severity": "high",
            "detail": (
                "Pump status 'running' recorded during telemetry gap for FC-WELL-001. "
                "No corresponding meter volume available for this period. "
                "Demonstration scenario injected to illustrate exception handling."
            ),
            "rule_id": "fcgma-fm-001",
            "status": "open",
        }],
        review_status="requires_attention",
    )
    records.append(r_pump_gap)

    # ── Case 3: UNRESOLVED COMBCODE — Well 3 ──────────────────────
    r_cc1 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case3-cc-01",
        event_timestamp=_ts(5),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W003"]["well_id"],
        meter_id=_WELLS["W003"]["meter_id"],
        combcode=None,  # Not resolved
        parcel_ids=["FC-PCL-103"],
        cumulative_volume=620.5,
        interval_volume=4.5,
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case3_unresolved_combcode"},
    )
    records.append(r_cc1)

    r_cc2 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case3-cc-02",
        event_timestamp=_ts(4),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W003"]["well_id"],
        meter_id=_WELLS["W003"]["meter_id"],
        combcode=None,  # Not resolved
        parcel_ids=["FC-PCL-103"],
        cumulative_volume=625.2,
        interval_volume=4.7,
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case3_unresolved_combcode_02"},
    )
    records.append(r_cc2)

    # Late-arriving record for Well 3 in prior period
    r_late = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case3-late",
        event_timestamp=_ts(45),
        reporting_period="2025-Q4",
        well_id=_WELLS["W003"]["well_id"],
        meter_id=_WELLS["W003"]["meter_id"],
        combcode=None,
        parcel_ids=["FC-PCL-103"],
        cumulative_volume=610.2,
        interval_volume=3.1,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case3_late_arriving_record"},
        exceptions=[{
            "id": "exc-case3-late-01",
            "exception_type": "late_arriving_record",
            "severity": "low",
            "detail": (
                "Record arrived 45 days after event timestamp. May affect prior-period totals. "
                "Demonstration scenario injected to illustrate exception handling."
            ),
            "rule_id": None,
            "status": "open",
        }],
        review_status="requires_attention",
    )
    records.append(r_late)

    # ── Case 4: MULTIPLIER CHANGE — Well 4 (one anomalous record mid-series) ──
    r_mult = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case4-mult",
        event_timestamp=_ts(11),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W004"]["well_id"],
        meter_id=_WELLS["W004"]["meter_id"],
        combcode=_WELLS["W004"]["combcode"],
        parcel_ids=["FC-PCL-104"],
        cumulative_volume=415.2,
        interval_volume=9.0,
        unit="acre-feet",
        multiplier=10.0,  # Changed from 1.0 — anomalous
        source_quality="ok",
        review_status="requires_attention",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case4_multiplier_change"},
        exceptions=[{
            "id": "exc-case4-mult-01",
            "exception_type": "multiplier_change",
            "severity": "medium",
            "detail": (
                "Meter multiplier changed from 1.0 to 10.0. "
                "Agency notification required per FCGMA rule fcgma-fm-004. "
                "Demonstration scenario injected to illustrate exception handling."
            ),
            "rule_id": "fcgma-fm-004",
            "status": "open",
        }],
    )
    records.append(r_mult)

    # ── Case 5: BACKUP ESTIMATE REQUIRED — Well 3, meter failure ──
    r_backup = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-case5-backup",
        event_timestamp=_ts(3),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W003"]["well_id"],
        meter_id=_WELLS["W003"]["meter_id"],
        combcode=_WELLS["W003"]["combcode"],
        parcel_ids=["FC-PCL-103"],
        cumulative_volume=None,  # Meter failure — no reading available
        interval_volume=None,
        unit="acre-feet",
        source_quality="meter_failure",
        review_status="requires_attention",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "case5_backup_estimate_required"},
    )
    records.append(r_backup)

    # ── Reviewer-approved record (one for W005 to show resolved path) ──
    r_approved = make_record(
        evidence_class="reviewer_adjustment",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-approved-w005",
        event_timestamp=_ts(2),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W005"]["well_id"],
        meter_id=_WELLS["W005"]["meter_id"],
        combcode=_WELLS["W005"]["combcode"],
        parcel_ids=["FC-PCL-105"],
        cumulative_volume=85.1,
        interval_volume=4.6,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "scenario": "approved_reviewer_adjustment",
            "note": "Reviewer confirmed multiplier as 1.0 after site visit. Interval volume validated.",
        },
        review_status="reviewer_approved",
        reviewer_notes="Multiplier confirmed as 1.0 after site visit. Interval volume validated.",
    )
    records.append(r_approved)

    # Insert all records
    for r in records:
        upsert_record(r)

    # Run calculation pass — this quarantines reset deltas and detects exceptions
    calc_result = run_full_calculation_pass()

    return {
        "scenario_count": len(records),
        "records_injected": [r["id"] for r in records],
        "calculation_result": calc_result,
        "disclaimer": SCENARIO_LABEL,
    }
