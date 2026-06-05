"""Fox Canyon Groundwater Management Agency — public-context rule pack.

Source material: official public FCGMA documents retrieved from fcgma.org.
This pack is NOT a substitute for Fox Canyon's internal procedures and does
not represent validated regulatory logic.  Every rule references the public
URL and retrieval date from which it was derived.

DISCLAIMER: All rules in this file are derived from publicly available
FCGMA documents for demonstration context only.  They must be validated
by Fox Canyon staff before use in any official submission.
"""
from __future__ import annotations

from datetime import date
from typing import Any

PACK_ID = "fcgma-public-context-v0.1"
PACK_VERSION = "0.1.0"
PACK_STATUS = "provisional"
RETRIEVAL_DATE = "2024-01-01"

DISCLAIMER = (
    "This rule pack is derived solely from public FCGMA documents and is "
    "intended for workflow demonstration and gap-analysis purposes only. "
    "It has NOT been validated by Fox Canyon Groundwater Management Agency "
    "and must not be used for regulatory submissions, compliance calculations, "
    "or any official reporting without agency review and approval."
)

RULES: list[dict[str, Any]] = [
    {
        "rule_id": "fcgma-fm-001",
        "category": "flowmeter_requirement",
        "title": "Flowmeter Installation Requirement",
        "summary": (
            "Groundwater extractors in the Fox Canyon Groundwater Management Area are "
            "required to install and maintain approved flowmeters on extraction wells. "
            "AMI (Advanced Metering Infrastructure) meters are required or strongly "
            "encouraged for automated reporting."
        ),
        "source_url": "https://fcgma.org/flowmeter-requirements/",
        "retrieval_date": RETRIEVAL_DATE,
        "pack_version": PACK_VERSION,
        "status": "provisional",
        "validation_required": True,
        "notes": "Specific threshold quantities and exemption criteria require direct agency confirmation.",
    },
    {
        "rule_id": "fcgma-fm-002",
        "category": "ami_requirement",
        "title": "Advanced Metering Infrastructure (AMI) Requirement",
        "summary": (
            "FCGMA Resolution 2018-01 established requirements for AMI meters that "
            "transmit extraction data automatically. Operators must ensure AMI data "
            "flows are configured and validated."
        ),
        "source_url": "https://s42135.pcdn.co/wp-content/uploads/2022/07/Resolution-2018-01.pdf",
        "retrieval_date": RETRIEVAL_DATE,
        "pack_version": PACK_VERSION,
        "status": "provisional",
        "validation_required": True,
        "notes": "Resolution 2018-01 details specific requirements. Review full text for exact provisions.",
    },
    {
        "rule_id": "fcgma-fm-003",
        "category": "meter_failure_workflow",
        "title": "Meter Failure and Backup Estimation",
        "summary": (
            "When a flowmeter fails or produces unreliable readings, operators must "
            "follow the FCGMA-approved backup estimation procedure. Estimated volumes "
            "must be clearly distinguished from metered volumes and reported with the "
            "appropriate methodology documentation."
        ),
        "source_url": "https://fcgma.org/flowmeter-requirements/",
        "retrieval_date": RETRIEVAL_DATE,
        "pack_version": PACK_VERSION,
        "status": "provisional",
        "validation_required": True,
        "notes": "Backup estimation methodology must be pre-approved by FCGMA.",
    },
    {
        "rule_id": "fcgma-fm-004",
        "category": "meter_change_reporting",
        "title": "Meter Change, Reset, Unit, and Multiplier Reporting",
        "summary": (
            "Operators must report meter replacements, resets, unit changes, and "
            "multiplier changes to FCGMA using approved agency forms. Failure to report "
            "these events may result in calculation errors and compliance findings."
        ),
        "source_url": "https://fcgma.org/agency-forms/",
        "retrieval_date": RETRIEVAL_DATE,
        "pack_version": PACK_VERSION,
        "status": "provisional",
        "validation_required": True,
        "notes": "Agency forms page lists current required reporting forms.",
    },
    {
        "rule_id": "fcgma-fm-005",
        "category": "calibration",
        "title": "Flowmeter Calibration",
        "summary": (
            "Flowmeters must be calibrated at FCGMA-specified intervals. Calibration "
            "records are part of the evidence package for compliance reporting. "
            "Out-of-calibration meters produce unreliable readings."
        ),
        "source_url": "https://fcgma.org/flowmeter-requirements/",
        "retrieval_date": RETRIEVAL_DATE,
        "pack_version": PACK_VERSION,
        "status": "provisional",
        "validation_required": True,
        "notes": "Calibration interval and approved calibration methods require agency confirmation.",
    },
    {
        "rule_id": "fcgma-gis-001",
        "category": "gis_mapping",
        "title": "Public GIS Map and CombCode Context",
        "summary": (
            "FCGMA maintains an interactive GIS map of groundwater resources and "
            "management zones. CombCode (combination code) references link extraction "
            "records to specific management zones and parcel locations."
        ),
        "source_url": "https://fcgma.org/interactive-map/",
        "retrieval_date": RETRIEVAL_DATE,
        "pack_version": PACK_VERSION,
        "status": "provisional",
        "validation_required": True,
        "notes": "CombCode mapping must be confirmed with FCGMA for each well/parcel combination.",
    },
    {
        "rule_id": "fcgma-et-001",
        "category": "weather_context",
        "title": "CIMIS Reference Evapotranspiration Context",
        "summary": (
            "California Department of Water Resources CIMIS network provides reference "
            "ET (ETo) for Ventura County stations. ETo context enriches applied-water "
            "analysis but does not directly substitute for metered extraction records."
        ),
        "source_url": "https://et.water.ca.gov/Rest/Index",
        "retrieval_date": RETRIEVAL_DATE,
        "pack_version": PACK_VERSION,
        "status": "informational",
        "validation_required": False,
        "notes": "ETo data is public contextual information. It must not replace flowmeter records.",
    },
    {
        "rule_id": "fcgma-aw-001",
        "category": "applied_water_attribution",
        "title": "Applied-Water Attribution — Provisional Ruleset",
        "summary": (
            "Applied-water attribution links groundwater extraction records to specific "
            "parcels and uses via CombCode and parcel mapping. Attribution remains "
            "provisional until CombCode, parcel mapping, and multiplier are confirmed."
        ),
        "source_url": "https://fcgma.org/flowmeter-requirements/",
        "retrieval_date": RETRIEVAL_DATE,
        "pack_version": PACK_VERSION,
        "status": "provisional",
        "validation_required": True,
        "notes": (
            "This ruleset is a demo illustration only. Real attribution logic requires "
            "Fox Canyon validation and may differ significantly."
        ),
    },
]

UNIT_CONVERSIONS: dict[str, float] = {
    "gallons": 1 / 325851.0,
    "gal": 1 / 325851.0,
    "cubic_feet": 1 / 43560.0,
    "cf": 1 / 43560.0,
    "acre_feet": 1.0,
    "af": 1.0,
    "acre-feet": 1.0,
    "acre-foot": 1.0,
    "million_gallons": 1_000_000 / 325851.0,
    "mgal": 1_000_000 / 325851.0,
}


def unit_to_af(value: float, unit: str) -> float | None:
    """Convert a volume to acre-feet. Returns None if unit unknown."""
    factor = UNIT_CONVERSIONS.get(unit.lower().replace(" ", "_"))
    if factor is None:
        return None
    return round(value * factor, 6)


def get_rules() -> list[dict[str, Any]]:
    return [r.copy() for r in RULES]


def get_rule(rule_id: str) -> dict[str, Any] | None:
    return next((r.copy() for r in RULES if r["rule_id"] == rule_id), None)


PACK_METADATA: dict[str, Any] = {
    "pack_id": PACK_ID,
    "pack_version": PACK_VERSION,
    "pack_status": PACK_STATUS,
    "disclaimer": DISCLAIMER,
    "rule_count": len(RULES),
    "sources": [
        "https://fcgma.org/flowmeter-requirements/",
        "https://fcgma.org/agency-forms/",
        "https://fcgma.org/interactive-map/",
        "https://s42135.pcdn.co/wp-content/uploads/2022/07/Resolution-2018-01.pdf",
        "https://et.water.ca.gov/Rest/Index",
    ],
    "retrieval_date": RETRIEVAL_DATE,
    "validation_status": "NOT validated by Fox Canyon GMA — demonstration context only",
}
