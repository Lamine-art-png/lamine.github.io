# Field Intelligence — Commercial Capability Matrix

This document is the source of truth for Field Intelligence launch packaging.
The rollout gate (`disabled`, `internal`, `canary`, `general`) remains above
commercial packaging. A plan can never bypass a release or security control.

## Record definition

One Field Intelligence record is one new capture completed into a saved field
observation. A record can include voice or typed context, multiple media assets,
location and structured metadata.

The following do **not** consume another record:

- idempotent completion retries;
- transcript corrections;
- reprocessing the same observation;
- task creation from an existing observation; and
- reading, searching or mapping existing observations.

## Launch access

| Plan | Field Intelligence records / month | Operating model |
|---|---:|---|
| Free | 2 | Complete capture and model-assisted analysis experience in one workspace. Intended for evaluation, not ongoing production volume. |
| Professional | 100 | Recurring workflow for commercial farms, advisors and individual operators. |
| Team | 500 | Shared evidence, assignments, roles, approvals and auditability. |
| Network | 2,500 | Multi-workspace programs, network rollups and higher field volume. |
| Enterprise | Contract-configured | Custom capacity, governance, retention, security review and deployment support. |

The organization-level entitlement is
`quota.field_intelligence.records.monthly`. The durable usage metric is
`field_record`.

## Capability model

| Capability | Free | Professional | Team | Network | Enterprise |
|---|---|---|---|---|---|
| Voice and typed capture | Enabled | Enabled | Enabled | Enabled | Enabled |
| Photo evidence and location | Enabled | Enabled | Enabled | Enabled | Enabled |
| Offline queue and synchronization | Enabled | Enabled | Enabled | Enabled | Enabled |
| Model-assisted extraction | Enabled within 2-record cap | Enabled | Enabled | Enabled | Enabled |
| Map, timeline, search and review | Enabled | Enabled | Enabled | Enabled | Enabled |
| Shared assignments and approvals | — | — | Enabled | Enabled | Enabled |
| Field Intelligence audit capability | — | — | Enabled | Enabled | Enabled |
| Cross-workspace and network rollups | — | — | Preview | Enabled | Enabled |
| Custom retention, security and capacity | — | — | — | Requestable | Contract-configured |

## Enforcement

- The API meters a record when a new capture is completed into an observation.
- Metering is server-authoritative. Frontend locks are explanatory UX only.
- The quota reservation is keyed to the capture session, so concurrent or
  repeated completion calls cannot double-charge the organization.
- A quota-exhausted response uses the standard `quota_exceeded` commercial
  boundary and recommends the next appropriate plan.
- Storage, evidence-upload, AI-action and other plan limits continue to apply
  independently.
- Enterprise capacity is contract-configured rather than presented as fake
  unlimited usage.
