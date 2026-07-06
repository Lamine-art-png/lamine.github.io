# Production release evidence

The Cloudflare production release workflow records immutable evidence by Git SHA after edge and portal deployment.

Required evidence before calling a release complete:

- upstream release contract for the exact Git SHA
- public edge health
- upstream health through the public edge
- authenticated release-health contract through the public edge
- production portal smoke result
- final release summary artifact

Operational notes:

- The backend release contract must report the exact build SHA, current schema, configured durable queue, reachable durable object storage, and production readiness before the public edge changes.
- Queue messages must not be acknowledged unless the backend reports terminal success/failure/cancelled for the corresponding connector job.
- If Worker secrets are absent during bootstrap, queue delivery retries and does not acknowledge the message.
- Rollback requires an explicit Worker version ID or Pages deployment ID from the Cloudflare dashboard/API for the known-good production deployment.
