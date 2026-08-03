#!/usr/bin/env python3
"""Apply the reviewed 2026 Platform API enterprise-hardening patch.

This script is intentionally deterministic. It refuses to continue if the
expected source text has drifted, preventing a partially applied security
change. It never reads or writes credential values.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime information-disclosure and customer-response hardening.
# ---------------------------------------------------------------------------
replace_once(
    "agroai_api/app/main.py",
    '    expose_headers=["x-agroai-runtime", "x-agroai-error"],',
    '    expose_headers=[\n'
    '        "x-agroai-runtime",\n'
    '        "X-Request-Id",\n'
    '        "RateLimit-Limit",\n'
    '        "RateLimit-Remaining",\n'
    '        "RateLimit-Reset",\n'
    '        "Retry-After",\n'
    '    ],',
)
replace_once(
    "agroai_api/app/main.py",
    '    if request.url.path.startswith("/v1/auth/") or request.url.path.startswith("/v1/account/"):\n'
    '        response.headers.setdefault("Cache-Control", "no-store, max-age=0")\n'
    '        response.headers.setdefault("Pragma", "no-cache")',
    '    sensitive_prefixes = ("/v1/auth/", "/v1/account/", "/v1/platform/", "/v1/admin/")\n'
    '    sensitive_exact_paths = {\n'
    '        "/v1/readiness",\n'
    '        "/v1/runtime/ai-status",\n'
    '        "/v1/auth/email-delivery/status",\n'
    '    }\n'
    '    if request.url.path.startswith(sensitive_prefixes) or request.url.path in sensitive_exact_paths:\n'
    '        response.headers.setdefault("Cache-Control", "no-store, max-age=0")\n'
    '        response.headers.setdefault("Pragma", "no-cache")',
)
replace_once(
    "agroai_api/app/main.py",
    '    except Exception as exc:  # pragma: no cover\n'
    '        logger.exception("Unhandled API error path=%s", request.url.path)\n'
    '        payload = {\n'
    '            "status": "error",\n'
    '            "error": "backend_runtime_error",\n'
    '            "path": request.url.path,\n'
    '            "reason": exc.__class__.__name__,\n'
    '            "checked_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",\n'
    '        }\n'
    '        response = JSONResponse(payload, status_code=500)\n'
    '        response.headers["x-agroai-error"] = exc.__class__.__name__\n'
    '        return _add_runtime_cors_headers(response, origin)',
    '    except Exception:  # pragma: no cover\n'
    '        logger.exception("Unhandled API error path=%s", request.url.path)\n'
    '        request_id = str(getattr(request.state, "request_id", "") or "")\n'
    '        payload = {\n'
    '            "status": "error",\n'
    '            "error": "backend_runtime_error",\n'
    '            "request_id": request_id,\n'
    '            "checked_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",\n'
    '        }\n'
    '        response = JSONResponse(payload, status_code=500)\n'
    '        response.headers["Cache-Control"] = "no-store, max-age=0"\n'
    '        response.headers["Pragma"] = "no-cache"\n'
    '        return _add_runtime_cors_headers(response, origin)',
)
replace_once(
    "agroai_api/app/main.py",
    '        "schema": schema_status,\n'
    '        "production": report.to_dict(),',
    '        "schema": {"ready": bool(schema_status["ready"])},\n'
    '        "production": {\n'
    '            "ready": bool(report.ready),\n'
    '            "target_scale": report.target_scale,\n'
    '            "blocker_count": len(report.blockers),\n'
    '            "warning_count": len(report.warnings),\n'
    '        },',
)
replace_once(
    "agroai_api/app/main.py",
    '    return {\n'
    '        "status": "ok",\n'
    '        "runtime": VERSION,\n'
    '        "configured": status_payload.get("configured"),\n'
    '        "provider": status_payload.get("provider"),\n'
    '        "mode": status_payload.get("mode"),\n'
    '        "base_url_present": status_payload.get("base_url_present"),\n'
    '        "selected_model": status_payload.get("model"),\n'
    '        "missing_env": status_payload.get("missing_env", []),\n'
    '        "fallback_active": status_payload.get("fallback_active"),\n'
    '        "profiles": status_payload.get("profiles", {}),\n'
    '        "checked_at": datetime.datetime.utcnow().isoformat() + "Z",\n'
    '    }',
    '    configured = bool(status_payload.get("configured"))\n'
    '    return {\n'
    '        "status": "ok" if configured else "degraded",\n'
    '        "runtime": VERSION,\n'
    '        "configured": configured,\n'
    '        "checked_at": datetime.datetime.utcnow().isoformat() + "Z",\n'
    '    }',
)
replace_once(
    "agroai_api/app/main.py",
    '    return {\n'
    '        "configured": current.get("configured"),\n'
    '        "provider": current.get("provider"),\n'
    '        "missing_env": current.get("missing_env", []),\n'
    '        "from_email_configured": current.get("from_email_configured"),\n'
    '        "from_email_domain": current.get("from_email_domain"),\n'
    '        "resend_configured": current.get("resend_configured"),\n'
    '        "sendgrid_configured": current.get("sendgrid_configured"),\n'
    '        "smtp_configured": current.get("smtp_configured"),\n'
    '        "resend_app_url_configured": current.get("resend_app_url_configured"),\n'
    '        "verification_base_url": current.get("verification_base_url"),\n'
    '    }',
    '    configured = bool(current.get("configured"))\n'
    '    return {\n'
    '        "status": "ok" if configured else "degraded",\n'
    '        "configured": configured,\n'
    '    }',
)

# ---------------------------------------------------------------------------
# SDK release metadata. Registry publication remains a separate credentialed
# release action; these manifests are no longer intentionally private.
# ---------------------------------------------------------------------------
write(
    "sdk/python/pyproject.toml",
    '''[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "agroai-platform"
version = "0.3.0"
description = "Typed server-side client for the AGRO-AI Platform API"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "Proprietary"}
authors = [{name = "AGRO-AI Inc."}]
keywords = ["agriculture", "api", "agtech", "enterprise"]
classifiers = [
  "Development Status :: 4 - Beta",
  "Intended Audience :: Developers",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Typing :: Typed",
]
dependencies = ["requests>=2.31,<3", "httpx>=0.26,<1"]

[project.urls]
Documentation = "https://agroai-pilot.com/platform-api/docs/"
Homepage = "https://agroai-pilot.com/platform-api"
Issues = "https://agroai-pilot.com/platform-api/support"

[tool.setuptools.packages.find]
where = ["."]
include = ["agroai_platform*"]
''',
)
write(
    "sdk/typescript/package.json",
    json.dumps(
        {
            "name": "@agro-ai/platform",
            "version": "0.3.0",
            "type": "module",
            "description": "Typed server-side client for the AGRO-AI Platform API",
            "license": "UNLICENSED",
            "engines": {"node": ">=20"},
            "exports": {".": "./dist/index.js", "./browser": "./dist/browser.js"},
            "types": "./dist/index.d.ts",
            "files": ["dist", "README.md", "CHANGELOG.md"],
            "publishConfig": {"access": "public", "provenance": True},
            "scripts": {
                "build": "tsc -p tsconfig.json",
                "test": "npm run build && node --test tests/*.test.mjs",
                "pack:verify": "npm pack --dry-run",
            },
            "devDependencies": {"typescript": "5.8.3"},
        },
        indent=2,
    ),
)

# Keep public copy truthful while making the source SDK/release path usable.
replace_once(
    "developers/index.html",
    '<section id="introduction"><div class="eyebrow">Private developer preview</div>',
    '<section id="introduction"><div class="eyebrow">Enterprise developer platform</div>',
)
replace_once(
    "developers/index.html",
    '<section id="sdks"><h2>SDKs</h2><p>The unpublished Python and TypeScript packages provide typed errors, request IDs, rate-limit state, safe retries, pagination, uploads, polling, usage access, environment selection, and server-side webhook verification. Browser runtimes must never receive an API key.</p></section>',
    '<section id="sdks"><h2>SDKs</h2><p>The versioned Python and TypeScript server SDKs provide typed errors, request IDs, rate-limit state, safe retries, pagination, uploads, polling, usage access, environment selection, and server-side webhook verification. Signed build artifacts are produced by the release workflow before registry publication. Browser runtimes must never receive an API key.</p></section>',
)

# Mark stale 2025 documents as historical so they cannot be used as present-day
# enterprise evidence.
for historical in (
    "agroai_api/docs/ENTERPRISE_READINESS_ROADMAP.md",
    "agroai_api/ENTERPRISE_DELIVERY_SUMMARY.md",
):
    target = ROOT / historical
    text = target.read_text(encoding="utf-8")
    banner = (
        "> [!WARNING]\n"
        "> **Historical document.** This 2025 plan is not a current production, "
        "security, scale, certification, or customer-readiness claim. Use "
        "`docs/platform-api-enterprise-readiness-2026.md` as the authoritative "
        "Platform API readiness record.\n\n"
    )
    if not text.startswith("> [!WARNING]"):
        target.write_text(banner + text, encoding="utf-8")

write(
    "agroai_api/tests/unit/test_runtime_security_hardening.py",
    '''from __future__ import annotations


def test_public_runtime_diagnostics_are_minimal_and_non_cacheable(client):
    ai = client.get("/v1/runtime/ai-status")
    assert ai.status_code == 200
    assert set(ai.json()) <= {"status", "runtime", "configured", "checked_at"}
    assert ai.headers["cache-control"].startswith("no-store")

    email = client.get("/v1/auth/email-delivery/status")
    assert email.status_code == 200
    assert set(email.json()) == {"status", "configured"}
    assert email.headers["cache-control"].startswith("no-store")


def test_readiness_preserves_health_contract_without_configuration_inventory(client):
    response = client.get("/v1/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload["schema"]) == {"ready"}
    assert set(payload["production"]) == {
        "ready",
        "target_scale",
        "blocker_count",
        "warning_count",
    }
    rendered = response.text.lower()
    assert "missing_env" not in rendered
    assert "secret" not in rendered
    assert response.headers["cache-control"].startswith("no-store")


def test_platform_responses_are_non_cacheable_and_expose_operational_headers(client):
    response = client.get(
        "/v1/platform/health",
        headers={"origin": "https://app.agroai-pilot.com"},
    )
    assert response.headers["cache-control"].startswith("no-store")
    exposed = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-request-id" in exposed
    assert "ratelimit-limit" in exposed
    assert "retry-after" in exposed
    assert "x-agroai-error" not in exposed
''',
)

write(
    "agroai_api/scripts/platform_api_load_probe.py",
    '''#!/usr/bin/env python3
"""Bounded, read-only Platform API latency and availability probe.

Credentials are read only from AGROAI_PLATFORM_LOAD_TEST_KEY. Response bodies
are never stored. Production safeguards prevent accidental high-volume runs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from urllib.parse import urlparse

import httpx

ALLOWED_PATHS = {"/v1/health", "/v1/readiness", "/v1/platform/health", "/v1/platform/me"}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


async def run(args: argparse.Namespace) -> dict[str, object]:
    parsed = urlparse(args.base_url)
    if parsed.scheme != "https":
        raise SystemExit("base URL must use HTTPS")
    if args.path not in ALLOWED_PATHS:
        raise SystemExit(f"path is not in the read-only allowlist: {args.path}")
    is_production = parsed.hostname in {"api.agroai-pilot.com", "platform.agroai-pilot.com"}
    if is_production and (args.requests > 200 or args.concurrency > 10) and not args.confirm_production:
        raise SystemExit("production runs above 200 requests or concurrency 10 require --confirm-production")
    if args.requests < 1 or args.requests > 10000:
        raise SystemExit("requests must be between 1 and 10000")
    if args.concurrency < 1 or args.concurrency > 200:
        raise SystemExit("concurrency must be between 1 and 200")

    headers = {"User-Agent": "agroai-enterprise-load-probe/1.0"}
    key = os.getenv("AGROAI_PLATFORM_LOAD_TEST_KEY", "").strip()
    if args.path == "/v1/platform/me":
        if not key:
            raise SystemExit("AGROAI_PLATFORM_LOAD_TEST_KEY is required for /v1/platform/me")
        headers["Authorization"] = f"Bearer {key}"

    queue: asyncio.Queue[int] = asyncio.Queue()
    for item in range(args.requests):
        queue.put_nowait(item)
    latencies: list[float] = []
    status_counts: dict[str, int] = {}

    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        timeout=httpx.Timeout(args.timeout),
        follow_redirects=False,
        headers=headers,
        limits=httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency),
    ) as client:
        async def worker() -> None:
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                started = time.perf_counter()
                try:
                    response = await client.get(args.path)
                    code = str(response.status_code)
                except httpx.HTTPError:
                    code = "transport_error"
                elapsed = (time.perf_counter() - started) * 1000
                latencies.append(elapsed)
                status_counts[code] = status_counts.get(code, 0) + 1
                queue.task_done()

        started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        duration = max(time.perf_counter() - started, 0.000001)

    success = sum(count for code, count in status_counts.items() if code.startswith("2"))
    errors = args.requests - success
    result = {
        "base_url_host": parsed.hostname,
        "path": args.path,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "duration_seconds": round(duration, 3),
        "throughput_rps": round(args.requests / duration, 3),
        "success_rate": round(success / args.requests, 6),
        "error_rate": round(errors / args.requests, 6),
        "latency_ms": {
            "min": round(min(latencies), 3),
            "mean": round(statistics.fmean(latencies), 3),
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies), 3),
        },
        "status_counts": status_counts,
        "thresholds": {"max_error_rate": args.max_error_rate, "max_p95_ms": args.max_p95_ms},
    }
    result["passed"] = result["error_rate"] <= args.max_error_rate and result["latency_ms"]["p95"] <= args.max_p95_ms
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://api-preview.agroai-pilot.com")
    parser.add_argument("--path", default="/v1/health")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=500.0)
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

write(
    ".github/dependabot.yml",
    '''version: 2
updates:
  - package-ecosystem: pip
    directory: /agroai_api
    schedule: {interval: weekly}
    open-pull-requests-limit: 10
    labels: [dependencies, security]
  - package-ecosystem: pip
    directory: /sdk/python
    schedule: {interval: weekly}
    open-pull-requests-limit: 5
    labels: [dependencies, sdk]
  - package-ecosystem: npm
    directory: /figma-enterprise-v4
    schedule: {interval: weekly}
    open-pull-requests-limit: 10
    labels: [dependencies, portal]
  - package-ecosystem: npm
    directory: /cloudflare/edge-gateway
    schedule: {interval: weekly}
    open-pull-requests-limit: 10
    labels: [dependencies, edge]
  - package-ecosystem: npm
    directory: /sdk/typescript
    schedule: {interval: weekly}
    open-pull-requests-limit: 5
    labels: [dependencies, sdk]
  - package-ecosystem: github-actions
    directory: /
    schedule: {interval: weekly}
    open-pull-requests-limit: 10
    labels: [dependencies, ci]
''',
)

write(
    "SECURITY.md",
    '''# AGRO-AI security reporting

Report suspected vulnerabilities privately to **contact@agroai-pilot.com** with
`[SECURITY]` in the subject. Include the affected host or endpoint, impact,
reproduction steps, and a safe contact method. Do not include real customer
data, production credentials, destructive payloads, or public disclosure before
coordination.

AGRO-AI targets acknowledgement within one business day for credible reports.
A response target is not a contractual SLA. We may request identity and scope
validation before sharing remediation details.

## Safe-harbor boundaries

Good-faith, non-destructive research against accounts and data you own is
welcome. Do not access another organization, degrade availability, perform
social engineering, send spam, test physical equipment controls, or retain data
that is not yours. Stop immediately if customer data becomes visible.

## Supported production surface

Security support applies to the current production Platform API, Developer
Console, authenticated Enterprise Portal, and official AGRO-AI SDK release
artifacts. Historical branches, local demos, and third-party provider systems are
outside the supported surface.
''',
)

write(
    "docs/platform-api-slo-policy.md",
    '''# Platform API service-level objective policy

Status: **engineering objectives, not a customer SLA**.

The launch objective is 99.9% monthly availability for the customer request
path, less than 0.5% server-error rate, and p95 latency below 500 ms for bounded
metadata reads under the declared launch topology. Asynchronous operations have
separate objectives: accepted jobs begin processing within two minutes under
normal load, webhook deliveries reach a terminal state within fifteen minutes,
and billing meter backlog age remains below fifteen minutes.

No objective becomes a contractual claim until at least 30 consecutive days of
production telemetry, alert coverage, incident review, and an approved customer
agreement exist. Scheduled maintenance, customer-caused errors, provider
outages, and force-majeure exclusions must be defined in the signed SLA rather
than invented in product copy.

## Required measurements

Every report records release SHA, environment, instance and replica topology,
database and Redis topology, request mix, duration, throughput, p50/p95/p99,
status-code distribution, CPU, memory, database connections and pool waits,
Redis latency/backlog, queue age, worker throughput, and saturation point.

## Error-budget response

At 50% monthly budget consumption, freeze non-essential reliability-risking
changes. At 75%, require founder and engineering approval for releases. At 100%,
prioritize recovery and reliability work until the rolling window returns within
budget. Security fixes may bypass a freeze with documented risk acceptance.
''',
)

write(
    "docs/platform-api-disaster-recovery.md",
    '''# Platform API disaster recovery standard

Status: **required operating standard; targets remain unproven until exercised**.

## Recovery targets

The initial target is RPO <= 15 minutes and RTO <= 4 hours for the Platform API
system of record. Stripe remains the payment system of record; Redis is
reconstructible coordination state and must never be the only copy of customer
or billing truth. Object-storage recovery depends on bucket versioning,
retention, and provider durability settings.

## Required controls

- PostgreSQL automated backups and point-in-time recovery with a documented
  retention window.
- A quarterly restore into an isolated environment, including Alembic version
  proof, tenant-isolation checks, and sampled row/count reconciliation.
- Object-store versioning/lifecycle review and checksum-based recovery proof.
- Stripe subscription, invoice, webhook-event, and usage-meter reconciliation.
- Exact-SHA application and edge rollback with immutable evidence.
- A dependency map and named recovery owner for database, API, edge, queue,
  object storage, authentication, billing, and provider integrations.

## Exercise evidence

A drill is complete only when it records start/end time, selected restore point,
data-loss window, achieved RPO/RTO, schema SHA, application SHA, reconciliation
results, failures, remediation owner, and deadline. Documentation alone is not a
successful restore test.
''',
)

write(
    "docs/platform-api-incident-response.md",
    '''# Platform API incident-response standard

## Severity

- **SEV-1:** confirmed cross-tenant exposure, active credential compromise,
  unauthorized physical-action risk, or broad production outage.
- **SEV-2:** material degradation, billing corruption risk, lost asynchronous
  custody, or a security event with bounded impact.
- **SEV-3:** limited customer impact with a workaround.

## Response contract

For SEV-1, disable the affected capability first, preserve evidence, revoke or
rotate impacted credentials, and name an incident commander. Use the status
system for truthful customer updates. Do not speculate about cause or impact.
Maintain an event timeline using UTC, release SHAs, request IDs, organization
IDs, audit-event IDs, Stripe event IDs, queue/outbox identifiers, and operator
actions without copying secrets or customer payloads.

## Required closure

A resolved incident requires impact and affected-customer determination,
containment, recovery verification, root cause, contributing conditions,
corrective actions with owners and dates, customer communication decision, and a
blameless postmortem. SEV-1 and SEV-2 corrective actions remain tracked until
verified, not merely merged.
''',
)

write(
    "docs/platform-api-security-baseline.md",
    '''# Platform API security baseline

The Platform API uses organization/project/service-account scoped keys,
server-side HMAC hashing with a dedicated pepper, one-time plaintext display,
least-privilege scopes, optional CIDR restrictions, rotation overlap, immediate
revocation, and fail-closed lineage checks. Customer API keys are separate from
Portal sessions and internal Queue credentials.

Production requires a distributed fail-closed Redis limiter, authenticated
Cloudflare-to-origin client context, PostgreSQL, durable object storage and
queue custody, explicit versioned AES-GCM keyrings, curated public OpenAPI,
bounded idempotency, signed webhooks, safe request metadata, and exact-release
verification. Physical control execution remains disabled unless separately
implemented and approved.

## Still required for broad enterprise claims

Independent penetration testing, SOC 2/ISO audit work, SSO/MFA/SCIM, approved
legal/DPA text, data-export/deletion workflows, regional residency controls,
customer-specific retention, verified backup restores, and sustained production
SLO evidence are external or multi-quarter controls. They must never be implied
by a passing unit test or deployment gate.
''',
)

write(
    "docs/platform-api-enterprise-readiness-2026.md",
    '''# AGRO-AI Platform API enterprise readiness — 2026

Status: **production-capable controlled launch; broad-enterprise parity not yet certified**.

This is the authoritative readiness record. “OpenAI-level” or “Anthropic-level”
is not a self-awarded certification. The comparison is useful only as an
engineering benchmark for security, reliability, privacy, developer experience,
and operational maturity.

## Verified technical controls

| Domain | Current evidence |
| --- | --- |
| Tenant boundary | Organization, project, service-account, workspace, provider, and resource lineage checks; cross-tenant denial tests. |
| Machine identity | Test/live key separation, HMAC+pepper storage, scoped permissions, expiration, CIDR restrictions, rotation overlap, revocation. |
| Request safety | Server request IDs, bounded customer correlation IDs, cursor pagination, idempotency and concurrency tests, safe error envelopes. |
| Traffic control | Redis-backed multi-dimensional limiter designed to fail closed in production. |
| Secret custody | Versioned AES-256-GCM connector and webhook keyrings; one-time plaintext display; retrieval audit. |
| Webhooks | Signed delivery, timestamp/event identifiers, SSRF controls, bounded response capture, retries, terminal failure, replay controls. |
| Data custody | PostgreSQL system of record, durable queue/outbox patterns, checksum-bound object storage, no raw storage paths in customer responses. |
| Billing | Live Stripe Checkout, Customer Portal, signed/deduplicated webhooks, usage reservation/export/reconciliation, interval-safe prices. |
| Contract quality | Curated Platform-only OpenAPI with CI drift/leak checks; Python and TypeScript SDK source and tests. |
| Operations | Readiness endpoints, status/incident foundation, support cases, audit events, abuse controls, exact-SHA deployment verification. |

## Launch blockers before “all enterprise customers”

| Requirement | State | Completion evidence |
| --- | --- | --- |
| Measured performance | Open | Controlled load/saturation reports on the declared paid production topology. |
| Availability history | Open | At least 30 days of SLO telemetry and reviewed incidents. |
| Disaster recovery | Open | Successful isolated PostgreSQL/object-store restore drill with achieved RPO/RTO. |
| Independent security review | Open | Remediated third-party penetration test and recurring vulnerability program. |
| Compliance | Open | Applicable SOC 2/ISO audit evidence; no certification claim before issuance. |
| Enterprise identity | Open | SAML/OIDC SSO, enforced MFA policy, and SCIM/domain lifecycle where contracted. |
| Privacy operations | Open | Approved DPA/privacy terms, customer export/deletion, configurable retention, residency/ZDR where sold. |
| SDK distribution | In progress | Signed release artifacts now supported; registry publication and support policy required. |
| Legal launch | Open | Counsel-approved API Terms, AUP, Privacy, DPA, SLA, and enterprise order form. |
| Customer operations | Open | Named on-call/customer-success coverage and at least one repeated real enterprise integration. |

## Customer eligibility now

Approved organizations can build controlled server-side integrations using the
reviewed Platform API surface. Physical irrigation writes and providers marked
`awaiting_partner_contract` remain unavailable. Customers requiring SSO, SCIM,
formal SLA, custom residency/ZDR, a completed security questionnaire backed by
certification, or multi-region contractual recovery must use an explicitly
reviewed enterprise agreement and cannot be represented as self-service-ready
until those controls exist.
''',
)

print("enterprise hardening patch applied")
