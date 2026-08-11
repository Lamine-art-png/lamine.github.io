# Self-service developer platform

Implemented, disabled by default:

- server-authoritative owner/admin Developer console;
- test project, service-account, scoped key, CIDR, provider, resource, webhook,
  usage, safe request-log, billing, live-access, support, and docs surfaces;
- deterministic project-scoped synthetic sandbox;
- fields, sources/uploads, observations, recommendations, reports, jobs, usage,
  request logs, and curated provider readiness;
- package-quality unpublished Python and TypeScript server SDKs.

Test projects cannot read live credentials, live customer records, or perform
physical actions. Live projects require the live-project flag, active enrollment
environment, approved live-access request, eligible API subscription/contract,
and full Platform API readiness. Test projects are never promoted in place.

Activation requires the staged launch runbook, active catalog version, reviewed
terms, operational secrets, monitoring, smoke tests, and an explicit flag
change. None of those activation steps are performed by this branch.
