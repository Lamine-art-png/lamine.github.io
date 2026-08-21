# AGRO-AI AEP Assurance Intelligence V2

Assurance Intelligence turns existing AGRO-AI operational evidence into reviewer-oriented readiness workflows and immutable proof-package snapshots. It is additive to the current Enterprise Portal, canonical evidence store, Field Intelligence, report engine, commercial control plane, and authentication model.

Assurance is decision support. It does not certify an operation, determine legal compliance, submit a filing, grant regulatory approval, or imply that a source is live or complete.

## Customer workflow

1. Create an Assurance Passport for a farm, operation, or selected entity and reporting period.
2. Select versioned rule packs. The first customer-visible packs cover generic water assurance, buyer input records, and operational execution proof.
3. Map existing canonical Evidence Records or Field Intelligence observations to requirements. Assurance stores a mapping and provenance; it does not copy source media.
4. Review mappings with explicit accept, reject, correction, additional-proof, not-applicable, and reopen decisions. Review events are append-only.
5. Turn missing proof into a field task that carries Passport, requirement, workspace, and rule-pack provenance.
6. Run deterministic Assurance Agent triage to classify current mapping state,
   detect gaps/conflicts, and propose human-confirmed next actions. Evidence
   text is untrusted data and human review remains authoritative.
7. Generate versioned proof packages for reviewer evaluation. Each snapshot includes its status, rule-pack versions, evidence references, checksum, disclaimer, and secure authenticated download.

## API boundaries

- Portal APIs: `/v1/workspaces/{workspace_id}/assurance/*`, bearer-authenticated and organization/workspace scoped.
- Historical APIs: `/v1/assurance/*`, API-key authenticated and preserved for compatibility.
- The two identity modes never coerce an Organization ID into the historical `tenants` foreign-key domain.

See [ARCHITECTURE.md](./ARCHITECTURE.md), [EVIDENCE_MODEL.md](./EVIDENCE_MODEL.md), [RULE_PACKS.md](./RULE_PACKS.md), [SECURITY.md](./SECURITY.md), and [ROLLOUT.md](./ROLLOUT.md).

The forensic requirement disposition is in
[ASSURANCE_V2_CERTIFICATION.md](./ASSURANCE_V2_CERTIFICATION.md).
