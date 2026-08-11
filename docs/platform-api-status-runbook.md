# Platform API status runbook

Public status is feature-flagged and makes no uptime or SLA claim. Components
cover Platform API, authentication, Developer Console, webhooks, usage,
billing, ingestion, recommendations, reports, and providers.

Platform administrators create incidents as `investigating`, then publish
customer-safe `identified`, `monitoring`, and `resolved` updates. Do not expose
provider credentials, infrastructure identifiers, request bodies, customer
names, or exploit details. Notification hooks remain disabled until a reviewed
delivery policy exists.
