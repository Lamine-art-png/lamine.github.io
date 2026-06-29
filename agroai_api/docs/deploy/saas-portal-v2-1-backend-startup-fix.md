# SaaS Portal v2.1 backend startup fix

The production API can appear unavailable if Render cannot bind the web port before its health check timeout.

The SaaS Portal v2.1 migration originally added verification and team tables with foreign-key and index DDL. Render starts the web service with Alembic first, then Uvicorn. Because Uvicorn starts only after Alembic finishes, lock-prone migration DDL can make Render fail the deploy before the API opens the health endpoint.

This fix keeps the v2.1 migration startup-safe:

- add only the required email verification columns
- create the required verification and team tables if missing
- avoid foreign-key creation during startup
- avoid index DDL during startup
- leave stricter constraints and indexes for a later online migration

After merging, verify that Render deploys live, the API health endpoint responds, and the portal login no longer shows Backend unavailable.
