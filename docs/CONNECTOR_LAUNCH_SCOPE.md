# AGRO-AI connector launch scope

Status: engineering decision for the production-hardening release candidate.

A connector logo is not a production connector. Launch scope is intentionally small so each required provider can be reliable, tenant-safe, incrementally synchronized, observable, and truthful.

## Weighted decision matrix

Scores are 1-5. Higher is better. Complexity and operational burden are reverse-scored: 5 means lower burden.

| Provider | Customer value 25% | Intelligence value 20% | ICP fit 20% | Current maturity 10% | Lifecycle simplicity 10% | Incremental sync 5% | Enterprise friction 5% | Ops burden 5% | Weighted | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Dropbox | 4 | 4 | 4 | 5 | 4 | 4 | 4 | 4 | 4.15 | REQUIRED FOR LAUNCH |
| Google Drive | 5 | 5 | 5 | 3 | 4 | 5 | 4 | 4 | 4.55 | REQUIRED FOR LAUNCH |
| Outlook / Microsoft Graph | 5 | 5 | 5 | 2 | 3 | 5 | 3 | 3 | 4.15 | REQUIRED FOR LAUNCH |
| Gmail | 4 | 4 | 4 | 2 | 4 | 4 | 4 | 3 | 3.65 | NEXT AFTER LAUNCH |
| Box | 3 | 4 | 4 | 2 | 3 | 4 | 3 | 3 | 3.30 | NEXT AFTER LAUNCH |
| Slack | 3 | 3 | 2 | 2 | 3 | 3 | 3 | 2 | 2.65 | DEFER |
| Salesforce | 2 | 3 | 2 | 2 | 2 | 4 | 2 | 2 | 2.35 | DEFER |

## REQUIRED FOR LAUNCH

### Dropbox

The branch's most mature account connector. Keep it in launch scope and preserve the hardened authorization and credential-custody path.

### Google Drive

Highest-value new launch connector. Farms, agribusiness teams, consultants, agencies, and networks organize PDFs, spreadsheets, field records, water documentation, audit evidence, and operating reports in shared Drive folders. Drive directly strengthens Evidence, Reports, Assurance, and Intelligence. Its change-token API supports durable incremental synchronization.

### Outlook / Microsoft Graph

Required for enterprise launch because agricultural enterprises, agencies, districts, consultants, and larger operating teams commonly operate in Microsoft 365. Outlook carries operator decisions, vendor records, approvals, attachments, and incident context. Microsoft Graph delta links support incremental synchronization.

## NEXT AFTER LAUNCH

### Gmail

High value, but Google Drive closes the highest-value Google evidence path first. Gmail should reuse the hardened Google lifecycle after launch and add history-based incremental mail sync without delaying the initial release.

### Box

Strong enterprise document fit, especially for compliance-heavy customers, but lower immediate breadth than Drive and Microsoft 365.

## DEFER

### Slack

Useful context, but broad channel ingestion creates permission, retention, and signal-to-noise burden. It is not required to prove AGRO-AI's core operating-system value at launch.

### Salesforce

Important for a narrower customer-success workflow, but it does not materially improve field, water, compliance, or evidence intelligence enough to justify launch complexity.

## Google Earth Engine is a separate AgTech track

Google Earth Engine is not a generic enterprise document connector. It should be designed as a dedicated geospatial intelligence adapter with field-boundary semantics, acquisition-time freshness, provenance, spatial-resolution controls, and quota/cost controls.

## Product truthfulness rule

Until a provider meets the complete lifecycle:

- do not display `connected`;
- do not set `live_sync_enabled`;
- expose `platform_setup_required`, `authorization_required`, `oauth_pending`, `authorized_pending_token_exchange`, `reconnect_required`, `preview`, or `unavailable` as appropriate;
- disable actions that cannot succeed.

## Exit criteria for a required provider

A REQUIRED provider is complete only when it has:

1. one-time tenant/provider/connection-bound authorization;
2. server-side code exchange;
3. encrypted retrievable credential custody;
4. expiry and refresh handling;
5. reconnect behavior after revoked consent;
6. provider identity probe;
7. scope validation;
8. disconnect semantics;
9. durable external-worker synchronization;
10. pagination and incremental cursor semantics;
11. idempotent evidence persistence;
12. rate-limit and retry handling;
13. tenant-isolation tests;
14. truthful connection and sync status.
