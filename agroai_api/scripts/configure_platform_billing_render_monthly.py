"""Apply the monthly Platform API Stripe catalog to one Render service.

Only Platform API billing variables are mutable. The Stripe webhook secret is updated
when Stripe returns a newly-created endpoint secret. When an existing endpoint is
reused, the secret is intentionally absent and the activation workflow proves that the
runtime already has a valid signing secret by expecting signature denial instead of a
configuration error.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_ROOT = "https://api.render.com/v1"
CONTRACT = "agroai-platform-api-stripe-monthly-provisioning-v1"
CONFIRMATIONS = {
    "test": "CONFIGURE AGROAI PLATFORM TEST MONTHLY BILLING",
    "live": "CONFIGURE AGROAI PLATFORM LIVE MONTHLY BILLING",
}

PUBLIC_KEYS = {
    "PLATFORM_API_STRIPE_MODE",
    "PLATFORM_API_STRIPE_METER_EVENT_NAME",
    "PLATFORM_API_STRIPE_METER_ID",
    "PLATFORM_API_STRIPE_CUSTOMER_PORTAL_CONFIGURATION",
    "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID",
    "PLATFORM_API_STRIPE_DEVELOPER_OVERAGE_PRICE_ID",
    "PLATFORM_API_STRIPE_SCALE_MONTHLY_PRICE_ID",
    "PLATFORM_API_STRIPE_SCALE_OVERAGE_PRICE_ID",
    "PLATFORM_API_BILLING_ENABLED",
    "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
    "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
    "PLATFORM_API_PRICING_ENABLED",
    "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",
}
REQUIRED_PUBLIC_KEYS = PUBLIC_KEYS - {
    "PLATFORM_API_STRIPE_CUSTOMER_PORTAL_CONFIGURATION",
}
SECRET_KEYS = {
    "PLATFORM_API_STRIPE_SECRET_KEY",
    "PLATFORM_API_STRIPE_WEBHOOK_SECRET",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise RuntimeError("Provisioning report must be a JSON object")
    return payload


def _load_env(path: Path) -> dict[str, str]:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise RuntimeError("Secrets file permissions are too broad; require mode 0600")
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise RuntimeError("Secrets file contains an invalid line")
        values[key.strip()] = value.strip()
    return values


def _request(
    method: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"{API_ROOT}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "AGRO-AI-Platform-Monthly-Billing-Activator/1.0",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        response_text = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(
            f"Render API returned HTTP {exc.code} for {method} {path}: "
            f"{response_text}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Render API request failed for {method} {path}") from exc


def _set_env(service_id: str, token: str, key: str, value: str) -> None:
    if key not in PUBLIC_KEYS | SECRET_KEYS:
        raise RuntimeError(f"Refusing non-billing environment mutation: {key}")
    _request(
        "PUT",
        f"/services/{quote(service_id, safe='')}/env-vars/{quote(key, safe='')}",
        token,
        {"value": value},
    )


def _deploy(service_id: str, token: str, commit_id: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"deployMode": "deploy_only"}
    if commit_id:
        payload["commitId"] = commit_id
    return _request(
        "POST",
        f"/services/{quote(service_id, safe='')}/deploys",
        token,
        payload,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure monthly Platform API Stripe billing on Render."
    )
    parser.add_argument("--mode", choices=("test", "live"), required=True)
    parser.add_argument("--provisioning-report", required=True)
    parser.add_argument("--secrets-file", required=True)
    parser.add_argument("--service-id", default=os.getenv("RENDER_SERVICE_ID", ""))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--commit-id", default="")
    parser.add_argument("--confirmation", default="")
    parser.add_argument(
        "--report-output",
        default="platform-api-render-monthly-configuration.json",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    provisioning = _load_json(Path(args.provisioning_report))
    if provisioning.get("contract") != CONTRACT:
        raise RuntimeError("Unrecognized monthly Stripe provisioning report")
    if provisioning.get("mode") != args.mode:
        raise RuntimeError("Stripe provisioning mode does not match Render target")
    if not provisioning.get("applied"):
        raise RuntimeError("Refusing to configure Render from a planning-only report")
    if provisioning.get("billing_intervals_enabled") != ["monthly"]:
        raise RuntimeError("Provisioning report attempted to enable an unapproved interval")
    if provisioning.get("annual_checkout_enabled") is not False:
        raise RuntimeError("Annual Checkout must remain disabled in this catalog")

    raw_public = provisioning.get("render_env")
    if not isinstance(raw_public, dict):
        raise RuntimeError("Provisioning report is missing render_env")
    public_values = {
        str(key): str(value)
        for key, value in raw_public.items()
        if key in PUBLIC_KEYS and str(value).strip()
    }
    missing_public = sorted(REQUIRED_PUBLIC_KEYS - set(public_values))
    if missing_public:
        raise RuntimeError(f"Provisioning report is incomplete: {missing_public}")
    if public_values.get("PLATFORM_API_PRICING_ENABLED") != "false":
        raise RuntimeError("Provisional annual pricing must remain non-public")

    secret_values = {
        key: value
        for key, value in _load_env(Path(args.secrets_file)).items()
        if key in SECRET_KEYS
    }
    if not secret_values.get("PLATFORM_API_STRIPE_SECRET_KEY"):
        raise RuntimeError("Stripe secret key is missing")

    token = (os.environ.get("RENDER_API_KEY") or "").strip()
    service_id = args.service_id.strip()
    if args.apply:
        if args.confirmation != CONFIRMATIONS[args.mode]:
            raise RuntimeError(
                f"Exact confirmation required: {CONFIRMATIONS[args.mode]}"
            )
        if not token:
            raise RuntimeError("RENDER_API_KEY is required with --apply")
        if not service_id.startswith("srv-"):
            raise RuntimeError("A valid Render service ID is required with --apply")

    values = {**public_values, **secret_values}
    mutations = sorted(values)
    deploy_id: str | None = None
    if args.apply:
        for key in mutations:
            _set_env(service_id, token, key, values[key])
            time.sleep(0.1)
        if args.deploy:
            deployment = _deploy(
                service_id,
                token,
                args.commit_id.strip() or None,
            )
            deploy_id = str(
                deployment.get("id")
                or (deployment.get("deploy") or {}).get("id")
                or ""
            ) or None

    report = {
        "contract": "agroai-platform-api-render-monthly-billing-v1",
        "mode": args.mode,
        "applied": bool(args.apply),
        "service_id": service_id or None,
        "environment_variables_updated": mutations,
        "secrets_updated": sorted(secret_values),
        "webhook_secret_updated": "PLATFORM_API_STRIPE_WEBHOOK_SECRET" in secret_values,
        "deploy_requested": bool(args.apply and args.deploy),
        "deploy_id": deploy_id,
        "commit_id": args.commit_id.strip() or None,
        "annual_checkout_enabled": False,
    }
    output = Path(args.report_output)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
