"""Fail-closed staging configuration contract for Field Intelligence.

The contract proves that every staging resource is distinct from production
*before* a deploy hook is called. It prints redacted identities only and never
prints credentials, tokens, transcripts, object keys, or full database URLs.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import unquote, urlparse

PRODUCTION_HOSTNAMES = {
    "app.agroai-pilot.com",
    "api.agroai-pilot.com",
    "api-preview.agroai-pilot.com",
    "agroai-api-preview.onrender.com",
    "agroai-pilot.com",
    "www.agroai-pilot.com",
}
REAL_TRANSCRIPTION_PROVIDERS = {
    "openai_whisper",
    "whisper",
    "http",
    "configured",
    "production",
}

REQUIRED = [
    "FIELD_STAGING_API_URL",
    "FIELD_STAGING_PORTAL_URL",
    "FIELD_STAGING_DATABASE_URL",
    "FIELD_STAGING_DEPLOY_PROVIDER",
    "FIELD_STAGING_API_SERVICE_ID",
    "FIELD_STAGING_DEPLOY_HOOK",
    "FIELD_STAGING_WORKER_MODE",
    "FIELD_STAGING_OBJECT_STORAGE_BACKEND",
    "FIELD_STAGING_OBJECT_BUCKET",
    "FIELD_STAGING_OBJECT_ACCOUNT_ID",
    "FIELD_STAGING_OBJECT_ENDPOINT_URL",
    "FIELD_STAGING_R2_ACCESS_KEY_ID",
    "FIELD_STAGING_R2_SECRET_ACCESS_KEY",
    "FIELD_STAGING_TRANSCRIPTION_PROVIDER",
    "FIELD_STAGING_TRANSCRIPTION_ENDPOINT",
    "FIELD_STAGING_TRANSCRIPTION_API_KEY",
    "FIELD_STAGING_TRANSCRIPTION_MODEL",
    "FIELD_STAGING_INTERNAL_ORGANIZATION_IDS",
    "FIELD_STAGING_PORTAL_PROJECT",
    "PRODUCTION_DATABASE_RESOURCE_FINGERPRINT",
    "PRODUCTION_OBJECT_BUCKET_FINGERPRINT",
    "PRODUCTION_API_SERVICE_ID",
    "PRODUCTION_WORKER_SERVICE_ID",
    "PRODUCTION_PORTAL_PROJECT",
]
OPTIONAL = [
    "FIELD_STAGING_WORKER_SERVICE_ID",
    "FIELD_STAGING_WORKER_DEPLOY_HOOK",
    "FIELD_STAGING_OBJECT_REGION",
    "FIELD_STAGING_OBJECT_PREFIX",
    "FIELD_STAGING_SMOKE_TOKEN",
    "FIELD_STAGING_RESTRICTED_SMOKE_TOKEN",
    "FIELD_STAGING_RELEASE_STATE",
    "FIELD_STAGING_CONFIRM_CANARY",
]


def _value(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _redacted_url_identity(url: str) -> str:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if not host:
        return "(unparseable)"
    return f"{parsed.scheme or 'unknown'}://{host}"


def _database_fingerprint(url: str) -> str:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    port = parsed.port or 5432
    database = unquote((parsed.path or "").lstrip("/")).lower()
    if not host or not database:
        return ""
    return f"{host}:{port}/{database}"


def _object_fingerprint(account_id: str, bucket: str) -> str:
    account = re.sub(r"[^a-z0-9_-]", "", (account_id or "").lower())
    name = (bucket or "").strip().lower()
    return f"{account}:{name}" if account and name else ""


def _render_service_id(hook: str) -> str:
    parsed = urlparse(hook or "")
    if (parsed.hostname or "").lower() != "api.render.com":
        return ""
    match = re.search(r"/deploy/(srv-[A-Za-z0-9-]+)(?:/|$)", parsed.path)
    return match.group(1) if match else ""


def _check_deploy_hook(
    *,
    label: str,
    provider: str,
    hook: str,
    staging_service_id: str,
    production_service_id: str,
    failures: list[str],
) -> dict:
    identity = {"provider": provider, "host": _host(hook), "service_id": staging_service_id or None}
    if staging_service_id and staging_service_id == production_service_id:
        failures.append(f"{label} staging service id equals the production service id")
    if provider != "render":
        failures.append(f"unsupported staging deploy provider: {provider or '(missing)'}")
        return identity
    resolved = _render_service_id(hook)
    if not resolved:
        failures.append(f"{label} deploy hook is not a recognized Render deploy hook")
    elif resolved != staging_service_id:
        failures.append(f"{label} deploy hook service id does not equal the declared staging service id")
    if production_service_id and resolved == production_service_id:
        failures.append(f"{label} deploy hook resolves to the production service")
    identity["resolved_service_id"] = resolved or None
    return identity


def main() -> int:
    failures: list[str] = []
    values = {name: _value(name) for name in REQUIRED + OPTIONAL}
    missing = [name for name in REQUIRED if not values[name]]
    if missing:
        failures.append(f"missing required staging configuration: {sorted(missing)}")

    report: dict = {
        "contract": "field-intelligence-staging-v2",
        "checks": {
            "present": {name: bool(values[name]) for name in REQUIRED + OPTIONAL},
        },
    }

    # No staging URL or hook may point at a production application hostname.
    for name in (
        "FIELD_STAGING_API_URL",
        "FIELD_STAGING_PORTAL_URL",
        "FIELD_STAGING_DEPLOY_HOOK",
        "FIELD_STAGING_WORKER_DEPLOY_HOOK",
        "FIELD_STAGING_OBJECT_ENDPOINT_URL",
        "FIELD_STAGING_TRANSCRIPTION_ENDPOINT",
    ):
        value = values.get(name) or ""
        if value and _host(value) in PRODUCTION_HOSTNAMES:
            failures.append(f"{name} targets a PRODUCTION hostname ({_host(value)})")
    report["checks"]["api"] = _redacted_url_identity(values["FIELD_STAGING_API_URL"])
    report["checks"]["portal"] = _redacted_url_identity(values["FIELD_STAGING_PORTAL_URL"])

    # Normalized database identity is mandatory and must differ from production.
    database_url = values["FIELD_STAGING_DATABASE_URL"]
    if database_url and not database_url.startswith(("postgresql://", "postgres://")):
        failures.append("FIELD_STAGING_DATABASE_URL must be PostgreSQL")
    database_fp = _database_fingerprint(database_url)
    production_database_fp = values["PRODUCTION_DATABASE_RESOURCE_FINGERPRINT"].lower()
    if database_url and not database_fp:
        failures.append("FIELD_STAGING_DATABASE_URL does not contain a usable host and database name")
    if database_fp and database_fp == production_database_fp:
        failures.append("staging database resource fingerprint equals production")
    report["checks"]["database_fingerprint"] = database_fp or None

    # Object-store identity is account + bucket, not a naming hint alone.
    backend = values["FIELD_STAGING_OBJECT_STORAGE_BACKEND"].lower()
    if backend not in {"r2", "s3", "s3_compatible"}:
        failures.append("staging object storage must use R2/S3-compatible durable storage")
    bucket = values["FIELD_STAGING_OBJECT_BUCKET"]
    object_fp = _object_fingerprint(values["FIELD_STAGING_OBJECT_ACCOUNT_ID"], bucket)
    production_object_fp = values["PRODUCTION_OBJECT_BUCKET_FINGERPRINT"].lower()
    if object_fp and object_fp == production_object_fp:
        failures.append("staging object bucket fingerprint equals production")
    if bucket and "staging" not in bucket.lower():
        failures.append("FIELD_STAGING_OBJECT_BUCKET must contain 'staging'")
    prefix = values["FIELD_STAGING_OBJECT_PREFIX"] or "staging/field-intelligence"
    if "staging" not in prefix.lower():
        failures.append("FIELD_STAGING_OBJECT_PREFIX must be staging-scoped")
    report["checks"]["object_fingerprint"] = object_fp or None
    report["checks"]["object_prefix"] = prefix

    # Deploy-hook identity is proven before any network POST.
    provider = values["FIELD_STAGING_DEPLOY_PROVIDER"].lower()
    report["checks"]["api_deploy"] = _check_deploy_hook(
        label="API",
        provider=provider,
        hook=values["FIELD_STAGING_DEPLOY_HOOK"],
        staging_service_id=values["FIELD_STAGING_API_SERVICE_ID"],
        production_service_id=values["PRODUCTION_API_SERVICE_ID"],
        failures=failures,
    )
    worker_mode = values["FIELD_STAGING_WORKER_MODE"].lower()
    if worker_mode not in {"dedicated", "in_process"}:
        failures.append("FIELD_STAGING_WORKER_MODE must be dedicated or in_process")
    if worker_mode == "dedicated":
        if not values["FIELD_STAGING_WORKER_SERVICE_ID"] or not values["FIELD_STAGING_WORKER_DEPLOY_HOOK"]:
            failures.append("dedicated staging worker requires service id and deploy hook")
        report["checks"]["worker_deploy"] = _check_deploy_hook(
            label="worker",
            provider=provider,
            hook=values["FIELD_STAGING_WORKER_DEPLOY_HOOK"],
            staging_service_id=values["FIELD_STAGING_WORKER_SERVICE_ID"],
            production_service_id=values["PRODUCTION_WORKER_SERVICE_ID"],
            failures=failures,
        )
    else:
        if values["FIELD_STAGING_WORKER_DEPLOY_HOOK"]:
            failures.append("in_process worker mode must not configure a worker deploy hook")
        report["checks"]["worker_deploy"] = {"mode": "in_process", "service_id": values["FIELD_STAGING_API_SERVICE_ID"] or None}

    # Portal project identity is mandatory and independent from production.
    portal_project = values["FIELD_STAGING_PORTAL_PROJECT"]
    if portal_project == values["PRODUCTION_PORTAL_PROJECT"]:
        failures.append("staging portal project equals production")
    if portal_project and "staging" not in portal_project.lower():
        failures.append("staging portal project name must contain 'staging'")
    report["checks"]["portal_project"] = portal_project or None

    # Staging must exercise a real transcription provider.
    transcription_provider = values["FIELD_STAGING_TRANSCRIPTION_PROVIDER"].lower()
    if transcription_provider not in REAL_TRANSCRIPTION_PROVIDERS:
        failures.append("staging transcription provider must be a real configured provider")
    if not values["FIELD_STAGING_TRANSCRIPTION_ENDPOINT"] or not values["FIELD_STAGING_TRANSCRIPTION_API_KEY"]:
        failures.append("real staging transcription requires endpoint and API key")
    if not values["FIELD_STAGING_TRANSCRIPTION_MODEL"]:
        failures.append("real staging transcription requires a model")
    report["checks"]["transcription_provider"] = transcription_provider or None

    release_state = (values["FIELD_STAGING_RELEASE_STATE"] or "internal").lower()
    canary_confirmed = values["FIELD_STAGING_CONFIRM_CANARY"] == "CONFIRM_STAGING_CANARY"
    if release_state == "general":
        failures.append("release state 'general' is refused in staging")
    elif release_state == "canary" and not canary_confirmed:
        failures.append("release state 'canary' requires CONFIRM_STAGING_CANARY")
    elif release_state not in {"internal", "canary"}:
        failures.append("staging release state must be internal or explicitly confirmed canary")
    report["checks"]["release_state"] = release_state
    report["checks"]["internal_cohort_configured"] = bool(values["FIELD_STAGING_INTERNAL_ORGANIZATION_IDS"])

    # Production credential variable names are forbidden in the staging job.
    for name in (
        "CLOUDFLARE_R2_ACCESS_KEY_ID",
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        "CLOUDFLARE_API_TOKEN",
        "DATABASE_URL",
    ):
        if _value(name):
            failures.append(f"production/runtime credential variable {name} must not be pre-set in staging validation")

    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
