# ADR 009: Portal Compatibility Boundary

Decision: Portal `AuthContext` remains authoritative for Portal routes.

Platform API principals are introduced through separate dependencies. Existing Portal traffic is not migrated to Platform API keys, projects, rate limits, or service accounts in this branch.
