"""Compatibility aliases for post-migration hardening fields.

The canonical mappings live in ``operational_records``. Keeping aliases avoids
multiple SQLAlchemy mappers redefining the same table columns and accidentally
replacing primary-key/default metadata.
"""
from app.models.operational_records import DataSource, EvidenceRecord, IngestionJob, IntelligenceRun

DataSourceIdentity = DataSource
IngestionJobState = IngestionJob
EvidenceFreshnessState = EvidenceRecord
IntelligenceRunProvenanceState = IntelligenceRun

__all__ = [
    "DataSourceIdentity",
    "IngestionJobState",
    "EvidenceFreshnessState",
    "IntelligenceRunProvenanceState",
]
