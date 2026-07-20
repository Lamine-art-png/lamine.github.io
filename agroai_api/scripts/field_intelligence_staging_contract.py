"""Fail-closed staging configuration contract for Field Intelligence.

Validates that a staging deployment can never touch production. Run inside the
staging workflow (and locally) with staging values in the environment. Prints a
redacted JSON report; exits nonzero on any violation or missing resource.

Never prints secret values — only presence/absence and redacted hosts.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse

# Production surfaces this workflow must never target. api-preview and the
# Render "preview" service ARE production (the public edge routes to them).
PRODUCTION_HOSTNAMES = {
    "app.agroai-pilot.com",
    "api.agroai-pilot.com",
    "api-preview.agroai-pilot.com",
    "agroai-api-preview.onrender.com",
    "agroai-pilot.com",
    "www.agroai-pilot.com",
}
PRODUCTION_PORTAL_PROJECTS = {"agroai-portal"}
PRODUCTION_BUCKET_HINT = "CONNECTOR_OBJECT_BUCKET"  # production bucket name, if known to the runner

REQUIRED = [
    "FIELD_STAGING_API_URL",
    "FIELD_STAGING_DATABASE_URL",
    "FIELD_STAGING_OBJECT_STORAGE_BACKEND",
    "FIELD_STAGING_OBJECT_BUCKET",
    "FIELD_STAGING_OBJECT_ENDPOINT_URL",
    "FIELD_STAGING_R2_ACCESS_KEY_ID",
    "FIELD_STAGING_R2_SECRET_ACCESS_KEY",
    "FIELD_STAGING_TRANSCRIPTION_PROVIDER",
    "FIELD_STAGING_INTERNAL_ORGANIZATION_IDS",
]
OPTIONAL = [
    "FIELD_STAGING_PORTAL_URL",
    "FIELD_STAGING_DEPLOY_HOOK",
    "FIELD_STAGING_WORKER_DEPLOY_HOOK",
    "FIELD_STAGING_OBJECT_REGION",
    "FIELD_STAGING_TRANSCRIPTION_ENDPOINT",
    "FIELD_STAGING_TRANSCRIPTION_API_KEY",
    "FIELD_STAGING_TRANSCRIPTION_MODEL",
    "FIELD_STAGING_SMOKE_TOKEN",
    "FIELD_STAGING_PORTAL_PROJECT",
]


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _redact_host(url: str) -> str:
    host = _host(url)
    return host or "(unparseable)"


def main() -> int:
    failures: list[str] = []
    report: dict = {"contract": "field-intelligence-staging-v1", "checks": {}}

    values = {name: (os.environ.get(name) or "").strip() for name in REQUIRED + OPTIONAL}
    missing = [name for name in REQUIRED if not values[name]]
    if missing:
        failures.append(f"missing required staging configuration: {sorted(missing)}")
    report["checks"]["present"] = {name: bool(values[name]) for name in REQUIRED + OPTIONAL}

    # 1) No staging URL may point at a production hostname.
    for name in ("FIELD_STAGING_API_URL", "FIELD_STAGING_PORTAL_URL",
                 "FIELD_STAGING_DEPLOY_HOOK", "FIELD_STAGING_WORKER_DEPLOY_HOOK",
                 "FIELD_STAGING_OBJECT_ENDPOINT_URL"):
        value = values.get(name) or ""
        if value and _host(value) in PRODUCTION_HOSTNAMES:
            failures.append(f"{name} targets a PRODUCTION hostname ({_redact_host(value)})")
    report["checks"]["api_host"] = _redact_host(values["FIELD_STAGING_API_URL"]) if values["FIELD_STAGING_API_URL"] else None

    # 2) The staging database must not be the production database. The runner
    #    may expose the production DB host fingerprint as
    #    PRODUCTION_DATABASE_HOST_FINGERPRINT (a hostname, never credentials).
    db_host = _host(values["FIELD_STAGING_DATABASE_URL"]) if values["FIELD_STAGING_DATABASE_URL"] else ""
    if db_host in PRODUCTION_HOSTNAMES:
        failures.append("FIELD_STAGING_DATABASE_URL targets a production hostname")
    production_db_fingerprint = (os.environ.get("PRODUCTION_DATABASE_HOST_FINGERPRINT") or "").strip().lower()
    if production_db_fingerprint and db_host == production_db_fingerprint:
        failures.append("FIELD_STAGING_DATABASE_URL equals the production database fingerprint")
    if values["FIELD_STAGING_DATABASE_URL"] and not values["FIELD_STAGING_DATABASE_URL"].startswith(("postgresql://", "postgres://")):
        failures.append("FIELD_STAGING_DATABASE_URL must be PostgreSQL")
    report["checks"]["database_host"] = db_host or None

    # 3) The staging bucket must not be the production bucket.
    production_bucket = (os.environ.get(PRODUCTION_BUCKET_HINT) or "").strip()
    staging_bucket = values["FIELD_STAGING_OBJECT_BUCKET"]
    if staging_bucket and production_bucket and staging_bucket == production_bucket:
        failures.append("FIELD_STAGING_OBJECT_BUCKET equals the production bucket")
    if staging_bucket and "staging" not in staging_bucket.lower():
        failures.append("FIELD_STAGING_OBJECT_BUCKET must be a dedicated staging bucket (name must contain 'staging')")
    report["checks"]["bucket_is_staging_named"] = bool(staging_bucket and "staging" in staging_bucket.lower())

    # 4) Object prefix must be staging-scoped when provided.
    prefix = (os.environ.get("FIELD_STAGING_OBJECT_PREFIX") or "staging/field-intelligence").strip()
    if "staging" not in prefix.lower():
        failures.append("FIELD_STAGING_OBJECT_PREFIX must be staging-scoped")
    report["checks"]["object_prefix"] = prefix

    # 5) Release state: internal only. general is always refused; canary needs
    #    the separate explicit confirmation input.
    release_state = (os.environ.get("FIELD_STAGING_RELEASE_STATE") or "internal").strip().lower()
    canary_confirmed = (os.environ.get("FIELD_STAGING_CONFIRM_CANARY") or "").strip() == "CONFIRM_STAGING_CANARY"
    if release_state == "general":
        failures.append("release state 'general' is refused in staging")
    elif release_state == "canary" and not canary_confirmed:
        failures.append("release state 'canary' requires the explicit CONFIRM_STAGING_CANARY confirmation")
    elif release_state not in {"internal", "canary", "disabled"}:
        failures.append(f"unknown staging release state: {release_state}")
    report["checks"]["release_state"] = release_state

    # 6) Transcription: a fake provider is acceptable in staging only when
    #    explicitly labeled; a real provider needs endpoint + key present.
    provider = values["FIELD_STAGING_TRANSCRIPTION_PROVIDER"].lower()
    if provider in {"openai_whisper", "whisper", "http", "configured", "production"}:
        if not (values["FIELD_STAGING_TRANSCRIPTION_ENDPOINT"] and values["FIELD_STAGING_TRANSCRIPTION_API_KEY"]):
            failures.append("real staging transcription provider requires endpoint and API key")
    report["checks"]["transcription_provider"] = provider or None

    # 7) Never reuse production R2 credentials: the workflow must not export
    #    CLOUDFLARE_R2_* production names into this validation environment.
    for name in ("CLOUDFLARE_R2_ACCESS_KEY_ID", "CLOUDFLARE_R2_SECRET_ACCESS_KEY"):
        if (os.environ.get(name) or "").strip():
            failures.append(f"production credential variable {name} must not be set in the staging contract environment")

    # 8) Portal project must not be the production Pages project.
    portal_project = values.get("FIELD_STAGING_PORTAL_PROJECT") or "agroai-portal-staging"
    if portal_project in PRODUCTION_PORTAL_PROJECTS:
        failures.append("FIELD_STAGING_PORTAL_PROJECT is the production portal project")
    report["checks"]["portal_project"] = portal_project

    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
