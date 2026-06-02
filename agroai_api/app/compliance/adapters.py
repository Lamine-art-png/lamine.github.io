"""Clean interoperability adapters for compliance provenance inputs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def serialize_qanat_record(record: dict[str, Any]) -> dict[str, Any]:
    """Map a Qanat-like public-domain payload to AGRO-AI fields without reusing AGPL code."""
    return {
        "source_system": "qanat_interop",
        "source_provenance": record.get("source_provenance", {}),
        "parcel": {"parcel_identifier": record.get("parcel_identifier") or record.get("apn"), "apn": record.get("apn"), "geometry_ref": record.get("parcel_geometry_ref")},
        "well": {"well_identifier": record.get("well_identifier"), "latitude": record.get("latitude"), "longitude": record.get("longitude")},
        "extraction_volume": {"value": record.get("extraction_volume"), "unit": record.get("unit", "acre_feet"), "truth_label": record.get("truth_label", "reported")},
        "water_budget": record.get("water_budget", {}),
        "reporting_period": str(record.get("reporting_period")),
    }


class OpenETProvenanceAdapter:
    """Adapter interface for ET estimates; always labels ET as estimated."""

    source_system = "openet"

    def to_measurement(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "measurement_type": "estimated_et",
            "date_window": payload["date_window"],
            "geometry_ref": payload["geometry_ref"],
            "value": float(payload["et_value"]),
            "unit": payload.get("unit", "millimeters"),
            "source_provider": payload.get("source_provider", "OpenET"),
            "source_model": payload.get("source_model", payload.get("ensemble_label", "ensemble")),
            "truth_label": "estimated",
            "source_timestamp": payload.get("source_timestamp", now),
            "ingestion_timestamp": now,
            "methodology_note": payload.get("methodology_note", "OpenET estimate imported for reporting support; not certified measurement."),
        }
