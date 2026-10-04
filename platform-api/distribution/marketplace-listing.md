# AGRO-AI Platform API — canonical marketplace listing

Updated: 2026-10-04

## Product name
**AGRO-AI Platform API — Agricultural Intelligence Infrastructure**

## One-line description
Build agricultural intelligence into software with APIs for fields, data ingestion, observations, recommendations, reports, provider readiness, usage, and auditable workflows.

## Short description
AGRO-AI gives agricultural software companies, OEMs, enterprise engineering teams, irrigation platforms, geospatial products, and AI developers one API for operational agricultural intelligence. Build on scoped machine identities, deterministic TEST data, asynchronous jobs, request logs, metered usage, and production-grade billing without rebuilding the agricultural intelligence layer internally.

## Long description
AGRO-AI Platform API is infrastructure for developers building agricultural products and workflows.

Use it to create and manage field records, ingest structured agricultural data, write and query observations, generate recommendations and reports, orchestrate supported provider workflows, inspect jobs and request logs, and meter API usage.

The platform is designed for B2B software and enterprise integrations. Authentication uses organization- and project-scoped service accounts and API keys. Write operations support idempotency. Long-running work uses durable jobs. The platform includes rate limits, request IDs, usage accounting, security boundaries, and a deterministic TEST sandbox.

Typical builders include farm-management and agronomy software companies; irrigation, controller, sensor, and equipment OEMs; enterprise agriculture engineering and data teams; geospatial, satellite, weather, and remote-sensing companies; water-management and compliance software providers; systems integrators; and AI-agent developers.

## Core API surfaces
- fields and field boundaries
- sources and uploads
- observations and provenance
- agricultural recommendations
- reports and authorized downloads
- provider readiness and synchronization
- jobs and retries
- usage and request logs
- action planning
- deterministic TEST sandbox

## Security and reliability
- scoped service accounts and API keys
- TEST and LIVE key separation
- idempotency keys for logical writes
- rate-limit headers and request IDs
- organization/project isolation
- safe request logs
- production-readiness and entitlement gates
- fail-closed capability flags for provider and physical execution features

## Direct AGRO-AI pricing

| Plan | Price | Included API credits | Overage |
| --- | ---: | ---: | ---: |
| Developer | $149/month or $1,430/year | 250,000 | $0.75 / 1,000 credits |
| Scale | $749/month or $7,190/year | 2,000,000 | $0.35 / 1,000 credits |
| Enterprise | Custom | Custom | Custom |

Direct Developer and Scale billing is implemented through AGRO-AI's production Stripe billing stack. External marketplaces must use their own required entitlement and transaction path for marketplace-originated customers; never double-bill a marketplace subscriber through direct Stripe checkout.

## URLs
- Product: https://agroai-pilot.com/platform-api/
- Developer console: https://platform.agroai-pilot.com
- API base: https://api.agroai-pilot.com/v1
- API reference: https://agroai-pilot.com/platform-api/reference.html
- Documentation: https://agroai-pilot.com/platform-api/docs/
- OpenAPI import artifact: https://github.com/Lamine-art-png/lamine.github.io/blob/main/platform-api/distribution/marketplace_openapi.json
- Postman import artifact: https://github.com/Lamine-art-png/lamine.github.io/blob/main/platform-api/distribution/AGRO-AI-Platform-API.postman_collection.json

## Search keywords
agriculture API, agtech API, agricultural intelligence, farm API, field intelligence, irrigation intelligence, crop intelligence, agronomy API, agricultural data, farm management integration, geospatial agriculture, agricultural AI, water management API, agricultural recommendations, enterprise agriculture

## Recommended categories
Primary: Developer Tools / Data / Artificial Intelligence  
Secondary: Agriculture / Analytics / Enterprise Integration

## Channel-specific positioning

### Postman
Lead with the shortest path to a first successful call: import the official collection, set `api_key`, call `GET /platform/me` or the TEST sandbox, then move into fields, observations, recommendations, reports, and usage.

### RapidAPI
Import `marketplace_openapi.json`. Keep the listing developer-first. If Rapid Proxy monetization is used, map Rapid plans to AGRO-AI entitlements server-side and do not also charge the same subscriber through direct Stripe.

### AWS Marketplace
Use a SaaS listing with AWS-native subscription entitlement and metering for AWS-originated customers. AGRO-AI's own API remains the service plane; the AWS adapter should translate Marketplace subscription state into AGRO-AI organization/program/plan entitlements.

### Microsoft Marketplace
Use a transactable SaaS offer. The Microsoft adapter should map Marketplace fulfillment/subscription state to AGRO-AI organization/program/plan entitlements and preserve AGRO-AI's existing API-key/service-account model after provisioning.

## Truthful launch boundaries
Do not advertise an external marketplace as live until its publisher account, entitlement adapter, billing path, listing review, and required seller/legal steps have actually passed.

Provider readiness must remain truthful. A marketplace listing must not imply physical irrigation execution or a provider integration is available where the production capability gate is disabled.
