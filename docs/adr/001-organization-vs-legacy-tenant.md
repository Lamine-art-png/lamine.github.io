# ADR 001: Organization Versus Legacy Tenant

Decision: Platform API customers are scoped to `Organization`, not legacy `Tenant`.

Legacy tenant API keys remain supported for legacy routes only. They are not silently upgraded into organization Platform API access. Compatibility migration requires a later reviewed plan.
