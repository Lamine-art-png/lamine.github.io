# Platform API Portal Compatibility

The first Platform API branch is additive.

Preserved:

- Portal JWT auth.
- Registration, email verification, login, account recovery, sessions.
- Organization membership and workspace access.
- Billing, Stripe checkout/webhooks, paywalls, entitlements, quotas.
- Existing connector routes, uploads, R2, Queue, outbox, and intelligence routes.

New:

- Platform-admin-only Developers/API page.
- `/v1/platform/...` backend routes.

No current Portal traffic is migrated onto Platform API keys or rate limiting.
