"""Demo scenario injection for the FCGMA Water Intelligence Copilot.

Every injected record carries:
  scenario_injected = True
  scenario_label = "Demonstration scenario injected to illustrate exception handling."

These records are NEVER mixed silently with live or authorized records.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .ledger import clear_ledger, make_record, upsert_record
from .calculation_engine import run_full_calculation_pass

SCENARIO_LABEL = "Demonstration scenario injected to illustrate exception handling."
REPORTING_PERIOD = "2026-Q1"

# Anonymized well/meter IDs for demonstration
_WELLS = {
    "W001": {"well_id": "well-anon-001", "meter_id": "meter-anon-001", "combcode": "FC-ZN-07-001"},
    "W002": {"well_id": "well-anon-002", "meter_id": "meter-anon-002", "combcode": "FC-ZN-07-002"},
    "W003": {"well_id": "well-anon-003", "meter_id": "meter-anon-003", "combcode": None},  # unresolved CombCode
    "W004": {"well_id": "well-anon-004", "meter_id": "meter-anon-004", "combcode": "FC-ZN-12-001"},
    "W005": {"well_id": "well-anon-005", "meter_id": "meter-anon-005", "combcode": "FC-ZN-12-002"},
}


def _ts(days_ago: int = 0, hours: int = 0) -> str:
    t = datetime(2026, 3, 15, 8, 0, 0, tzinfo=timezone.utc)
    t -= timedelta(days=days_ago, hours=hours)
    return t.isoformat()


def inject_all_scenarios() -> dict[str, Any]:
    """Clear the ledger and inject a complete demonstration dataset."""
    clear_ledger()

    records: list[dict[str, Any]] = []

    # ── 1. Clean record (baseline) ──
    r1 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-001",
        event_timestamp=_ts(10),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        meter_serial="SN-ANON-0001",
        combcode=_WELLS["W001"]["combcode"],
        parcel_ids=["parcel-anon-101"],
        cumulative_volume=1250.0,
        interval_volume=12.4,
        unit="acre-feet",
        unit_original="acre-feet",
        multiplier=1.0,
        pump_status="running",
        source_quality="ok",
        review_status="pending_review",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "provider": "fcgma_generic_ami_csv",
            "external_source_id": "ami-2026-001",
            "retrieval_method": "demo_ami_csv_import",
            "scenario": "01_clean_record_baseline",
        },
    )
    records.append(r1)

    # ── 2. Missing telemetry interval (gap > 24 h) ──
    r2a = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-002a",
        event_timestamp=_ts(8, 0),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        combcode=_WELLS["W001"]["combcode"],
        parcel_ids=["parcel-anon-101"],
        cumulative_volume=1256.0,
        interval_volume=6.0,
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "provider": "fcgma_generic_ami_csv",
            "external_source_id": "ami-2026-002a",
            "scenario": "02a_pre_gap_record",
        },
    )
    records.append(r2a)

    # Gap record — 38 hours later (should trigger missing_telemetry_interval)
    r2b = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-002b",
        event_timestamp=_ts(6, 14),  # 38 h gap
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        combcode=_WELLS["W001"]["combcode"],
        parcel_ids=["parcel-anon-101"],
        cumulative_volume=1272.0,
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "provider": "fcgma_generic_ami_csv",
            "external_source_id": "ami-2026-002b",
            "scenario": "02b_post_gap_record",
        },
    )
    records.append(r2b)

    # ── 3. Meter reset ──
    r3a = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-003a",
        event_timestamp=_ts(7),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W002"]["well_id"],
        meter_id=_WELLS["W002"]["meter_id"],
        combcode=_WELLS["W002"]["combcode"],
        parcel_ids=["parcel-anon-102"],
        cumulative_volume=9850.4,
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "03a_pre_reset_reading"},
    )
    records.append(r3a)

    r3b = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-003b",
        event_timestamp=_ts(6),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W002"]["well_id"],
        meter_id=_WELLS["W002"]["meter_id"],
        combcode=_WELLS["W002"]["combcode"],
        parcel_ids=["parcel-anon-102"],
        cumulative_volume=12.1,  # Reset — meter replaced and restarted from near-zero
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "03b_post_reset_reading"},
    )
    records.append(r3b)

    # ── 4. Multiplier change ──
    r4 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-004",
        event_timestamp=_ts(5),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W004"]["well_id"],
        meter_id=_WELLS["W004"]["meter_id"],
        combcode=_WELLS["W004"]["combcode"],
        parcel_ids=["parcel-anon-104"],
        cumulative_volume=450.0,
        interval_volume=9.0,
        unit="acre-feet",
        multiplier=10.0,  # Changed from 1.0 — should flag
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "04_multiplier_change"},
        exceptions=[{
            "id": "exc-scenario-mult-01",
            "exception_type": "multiplier_change",
            "severity": "medium",
            "detail": "Meter multiplier changed from 1.0 to 10.0. Agency notification required per FCGMA rule fcgma-fm-004.",
            "rule_id": "fcgma-fm-004",
            "status": "open",
        }],
        review_status="requires_attention",
    )
    records.append(r4)

    # ── 5. Unit change (gallons to acre-feet) ──
    r5 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-005",
        event_timestamp=_ts(4),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W005"]["well_id"],
        meter_id=_WELLS["W005"]["meter_id"],
        combcode=_WELLS["W005"]["combcode"],
        parcel_ids=["parcel-anon-105"],
        cumulative_volume=4_500_000.0,  # In gallons — will normalize to ~13.8 AF
        unit_original="gallons",
        unit="acre-feet",
        multiplier=1.0,
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "05_unit_change_gallons"},
        exceptions=[{
            "id": "exc-scenario-unit-01",
            "exception_type": "unit_change",
            "severity": "medium",
            "detail": "Unit changed from 'gallons' to 'acre-feet'. Verify conversion is correct for this meter.",
            "rule_id": "fcgma-fm-004",
            "status": "open",
        }],
        review_status="requires_attention",
    )
    records.append(r5)

    # ── 6. Duplicate records ──
    r6a = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-006",
        event_timestamp=_ts(3),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        combcode=_WELLS["W001"]["combcode"],
        parcel_ids=["parcel-anon-101"],
        cumulative_volume=1290.0,
        interval_volume=8.2,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "06a_original_record"},
    )
    records.append(r6a)

    r6b = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-006-dup",
        event_timestamp=_ts(3),  # Same timestamp = duplicate
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        combcode=_WELLS["W001"]["combcode"],
        parcel_ids=["parcel-anon-101"],
        cumulative_volume=1290.0,
        interval_volume=8.2,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "06b_duplicate_record"},
    )
    records.append(r6b)

    # ── 7. Late-arriving record ──
    r7 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-007",
        event_timestamp=_ts(45),  # 45 days ago — very late arrival
        reporting_period="2025-Q4",
        well_id=_WELLS["W003"]["well_id"],
        meter_id=_WELLS["W003"]["meter_id"],
        combcode=None,
        parcel_ids=["parcel-anon-103"],
        cumulative_volume=610.2,
        interval_volume=3.1,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "07_late_arriving_record"},
        exceptions=[{
            "id": "exc-scenario-late-01",
            "exception_type": "late_arriving_record",
            "severity": "low",
            "detail": "Record arrived 45 days after event timestamp. May affect prior-period reporting.",
            "rule_id": None,
            "status": "open",
        }],
        review_status="requires_attention",
    )
    records.append(r7)

    # ── 8. Pump activity without meter movement ──
    r8_pump = make_record(
        evidence_class="pump_state_evidence",
        provider="wiseconn_sanitized_replay",
        external_source_id="wc-pump-2026-008",
        event_timestamp=_ts(2),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W002"]["well_id"],
        meter_id=_WELLS["W002"]["meter_id"],
        pump_status="running",
        cumulative_volume=None,
        interval_volume=None,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "provider": "wiseconn_sanitized_replay",
            "scenario": "08_pump_without_meter",
            "note": "WiseConn controller telemetry — anonymized replay capture.",
        },
        exceptions=[{
            "id": "exc-scenario-pump-01",
            "exception_type": "pump_activity_without_meter_movement",
            "severity": "high",
            "detail": "Pump status 'running' with no corresponding meter volume movement. Possible meter malfunction or unmetered extraction.",
            "rule_id": "fcgma-fm-001",
            "status": "open",
        }],
        review_status="requires_attention",
    )
    records.append(r8_pump)

    # ── 9. Reverse flow ──
    r9 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-009",
        event_timestamp=_ts(1, 12),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W004"]["well_id"],
        meter_id=_WELLS["W004"]["meter_id"],
        combcode=_WELLS["W004"]["combcode"],
        parcel_ids=["parcel-anon-104"],
        cumulative_volume=440.0,  # Lower than previous — negative delta
        interval_volume=-10.0,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "09_reverse_flow"},
        exceptions=[{
            "id": "exc-scenario-rev-01",
            "exception_type": "reverse_flow",
            "severity": "medium",
            "detail": "Negative interval volume (-10.0 AF) detected. Possible reverse flow, meter malfunction, or data error.",
            "rule_id": "fcgma-fm-001",
            "status": "open",
        }],
        review_status="requires_attention",
    )
    records.append(r9)

    # ── 10. Unresolved CombCode ──
    r10 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-010",
        event_timestamp=_ts(1),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W003"]["well_id"],
        meter_id=_WELLS["W003"]["meter_id"],
        combcode=None,  # Not resolved
        parcel_ids=["parcel-anon-103"],
        cumulative_volume=620.5,
        interval_volume=4.5,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "10_unresolved_combcode"},
    )
    records.append(r10)

    # ── 11. Unresolved parcel mapping ──
    r11 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-011",
        event_timestamp=_ts(0, 18),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W005"]["well_id"],
        meter_id=_WELLS["W005"]["meter_id"],
        combcode=_WELLS["W005"]["combcode"],
        parcel_ids=[],  # Not resolved
        cumulative_volume=88.4,
        interval_volume=2.2,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "11_unresolved_parcel_mapping"},
    )
    records.append(r11)

    # ── 12. One well → multiple parcels ──
    r12 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-012",
        event_timestamp=_ts(0, 12),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W002"]["well_id"],
        meter_id=_WELLS["W002"]["meter_id"],
        combcode=_WELLS["W002"]["combcode"],
        parcel_ids=["parcel-anon-102", "parcel-anon-102b"],  # Two parcels
        cumulative_volume=14.0,
        interval_volume=14.0,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "12_one_well_multiple_parcels"},
    )
    records.append(r12)

    # ── 13. Multiple wells → one parcel ──
    r13a = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-013a",
        event_timestamp=_ts(0, 6),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W001"]["well_id"],
        meter_id=_WELLS["W001"]["meter_id"],
        combcode=_WELLS["W001"]["combcode"],
        parcel_ids=["parcel-anon-shared-200"],  # Shared parcel
        cumulative_volume=1300.0,
        interval_volume=5.5,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "13a_well_one_to_shared_parcel"},
    )
    records.append(r13a)

    r13b = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-013b",
        event_timestamp=_ts(0, 5),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W004"]["well_id"],
        meter_id=_WELLS["W004"]["meter_id"],
        combcode=_WELLS["W004"]["combcode"],
        parcel_ids=["parcel-anon-shared-200"],  # Same shared parcel
        cumulative_volume=450.0,
        interval_volume=3.2,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "13b_well_two_to_shared_parcel"},
    )
    records.append(r13b)

    # ── 14. Backup estimate required ──
    r14 = make_record(
        evidence_class="groundwater_meter_reading",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-014",
        event_timestamp=_ts(0, 2),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W003"]["well_id"],
        meter_id=_WELLS["W003"]["meter_id"],
        combcode=_WELLS["W003"]["combcode"],
        parcel_ids=["parcel-anon-103"],
        cumulative_volume=None,  # Meter failure — no reading
        interval_volume=None,
        unit="acre-feet",
        source_quality="meter_failure",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={"scenario": "14_backup_estimate_required"},
        review_status="requires_attention",
    )
    records.append(r14)

    # ── 15. Reviewer adjustment ──
    r15 = make_record(
        evidence_class="reviewer_adjustment",
        provider="fcgma_generic_ami_csv",
        external_source_id="ami-2026-015-adj",
        event_timestamp=_ts(0, 1),
        reporting_period=REPORTING_PERIOD,
        well_id=_WELLS["W005"]["well_id"],
        meter_id=_WELLS["W005"]["meter_id"],
        combcode=_WELLS["W005"]["combcode"],
        parcel_ids=["parcel-anon-105"],
        cumulative_volume=92.0,
        interval_volume=2.8,
        unit="acre-feet",
        source_quality="ok",
        scenario_injected=True,
        scenario_label=SCENARIO_LABEL,
        source_lineage={
            "scenario": "15_reviewer_adjustment",
            "note": "Reviewer manually adjusted interval volume from 2.2 to 2.8 AF after confirming multiplier correction.",
        },
        review_status="reviewer_approved",
        reviewer_notes="Multiplier confirmed as 1.0 after site visit. Adjusted interval volume accordingly.",
    )
    records.append(r15)

    # ── WiseConn controller telemetry (sanitized replay, not Fox Canyon data) ──
    r_wc = make_record(
        evidence_class="controller_irrigation_telemetry",
        provider="wiseconn_sanitized_replay",
        external_source_id="wc-irr-2026-101",
        event_timestamp=_ts(3, 6),
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
                "WiseConn controller telemetry from anonymized sanitized replay. "
                "Controller telemetry records irrigation schedule events only. "
                "They do NOT represent groundwater extraction volumes."
            ),
        },
    )
    records.append(r_wc)

    # Insert all records
    for r in records:
        upsert_record(r)

    # Run calculation pass
    calc_result = run_full_calculation_pass()

    return {
        "scenario_count": len(records),
        "records_injected": [r["id"] for r in records],
        "calculation_result": calc_result,
        "disclaimer": SCENARIO_LABEL,
    }
