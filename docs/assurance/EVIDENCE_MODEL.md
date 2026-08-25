# Assurance evidence model

## Canonical source rule

Assurance does not create a second uploaded-file store. The canonical file and parsed-record path remains:

`DataSource -> EvidenceRecord -> AssuranceEvidenceArtifact mapping -> Passport requirement`

For field evidence, the path is:

`FieldCaptureSession -> FieldObservation -> FieldObservationAsset reference -> AssuranceEvidenceArtifact mapping`

`AssuranceEvidenceArtifact` is therefore a compatibility-named mapping layer. Its `canonical_evidence_id` or `field_observation_id` points to the source of truth. `source_kind` and `source_id` make that provenance explicit. The mapping captures classification needed for the Passport—evidence type, proof domain, truth label, reporting period, confidence, data quality, freshness threshold, and any unresolved issue—without copying raw evidence or binary media.

## Provenance fields

- source system, kind, and canonical ID;
- event and ingestion timestamps;
- measured/reported/estimated/calculated/AI-inferred truth label;
- confidence and data-quality status;
- reporting period and staleness threshold;
- checksum where the canonical source provides one;
- linked rule-pack requirement keys.

Field media responses include asset IDs and safe descriptors only. Private object keys are not copied into or returned by Assurance.

## Review and correction

Source records are not silently rewritten from Assurance. A reviewer may correct only mapping metadata. The previous and next mapping/checklist state is recorded in `AssuranceReviewEvent`; the material action is also recorded in `AssuranceAuditEvent`. Rejecting a mapping or requesting additional proof requires a human reason.

## Freshness and conflicts

A mapping becomes stale after `stale_after`. An unresolved issue makes it conflicting. Stale, conflicting, and rejected mappings do not contribute usable coverage. The readiness response names these states instead of collapsing them into a misleading binary.
