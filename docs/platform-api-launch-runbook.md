# Platform API staged launch runbook

All stages require exact-head green CI, one Alembic head, PostgreSQL/Redis
proof, security review, smoke tests, monitoring owner, rollback owner, and
explicit configuration review.

1. Internal admin validation: applications/admin flags; no customer navigation.
2. Selected strategic partners: partner/private-beta flags; test only.
3. Approved private-beta developers: control plane and test projects.
4. Verified self-service sandbox: self-service and applications; active Sandbox catalog.
5. Paid plans/live applications: billing, Checkout, meter export, live requests.
6. Approved live projects: live-project flag after full readiness.
7. Public marketing/docs/pricing: marketing, public docs, pricing, SDK downloads.

At every stage, smoke authentication, organization isolation, quota, Queue,
webhook, request logs, provider truth, and disablement. Roll back by disabling
the stage flags first, preserving customer data and durable custody.
