# AGRO-AI Source Library and Intelligence Contract

## Customer-visible custody

Every completed upload must create or resolve a tenant-owned `DataSource` record. The portal must show the source in Evidence and Sources with customer-safe metadata:

- filename
- provider
- source type
- processing state
- parsed-row count when available
- linked-evidence count
- intelligence-readiness state
- import timestamp

Customer APIs must not expose object-store URIs, local filesystem paths, raw credentials, or queue internals.

## Evidence linkage

Derived `EvidenceRecord` rows remain linked to the original source through `data_source_id`. Evidence screens should display the original filename whenever that linkage exists.

A source can remain valid and visible even when it produces zero structured evidence rows. Zero derived rows must not make an uploaded source disappear.

## Intelligence grounding

Ask AGRO-AI receives tenant/workspace-scoped source context through the intelligence context builder. Context is bounded:

- newest commercially permitted sources first
- maximum 4,000 text characters per source
- maximum 24,000 uploaded-source text characters total
- bounded parsed-row previews
- bounded evidence excerpts and values

PDF content is extracted on demand from the tenant-owned stored object when the ingestion-time text representation is missing or binary. Storage locations are never included in model context.

## One-time onboarding

`product_tour_v2` is route-aware. A step must navigate to its actual product route and spotlight a real visible page element or panel. The tour must never explain one section while pointing at an unrelated sidebar item.
