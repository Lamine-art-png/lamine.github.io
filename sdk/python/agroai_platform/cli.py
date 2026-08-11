"""AGRO-AI Platform API command-line interface.

A first-class CLI built directly on the official Python SDK client
(``agroai_platform.client``) — not a wrapper around ``curl``. Data-plane
operations authenticate with an ``agro_test_`` / ``agro_live_`` key supplied
via ``AGROAI_API_KEY`` (or ``--api-key``).

Human control-plane actions (creating projects and keys) intentionally require
a human session, not a machine API key. Those subcommands report how to obtain
access rather than misusing a data-plane key — a browser/device authentication
flow is a tracked follow-up (see docs/platform-api-cli.md).

Exit codes:
    0  success
    1  generic error
    2  usage error (argparse)
    3  authentication/authorization error (401/403)
    4  rate limited (429)
    5  not found (404)
    6  configuration or connectivity error
"""
from __future__ import annotations

import argparse
import json as _json
import os
import sys
from typing import Any

from .client import AgroAIPlatformClient, AgroAIPlatformError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_RATE_LIMITED = 4
EXIT_NOT_FOUND = 5
EXIT_CONFIG = 6


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("agroai-platform")
    except Exception:  # pragma: no cover - fallback when not installed
        return "0.2.0"


def _emit(data: Any, *, as_json: bool, out=None) -> None:
    out = out or sys.stdout
    if as_json:
        _json.dump(data, out, indent=2, sort_keys=True, default=str)
        out.write("\n")
    else:
        out.write(_human(data) + "\n")


def _human(data: Any) -> str:
    if isinstance(data, dict):
        return "\n".join(f"{k}: {_scalar(v)}" for k, v in data.items())
    if isinstance(data, list):
        return "\n".join(str(_scalar(item)) for item in data)
    return str(data)


def _scalar(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return _json.dumps(value, default=str)
    return str(value)


def _exit_code_for(exc: AgroAIPlatformError) -> int:
    status = exc.status_code or 0
    if status in (401, 403):
        return EXIT_AUTH
    if status == 429:
        return EXIT_RATE_LIMITED
    if status == 404:
        return EXIT_NOT_FOUND
    return EXIT_ERROR


def _fail(message: str, *, code: int, as_json: bool, request_id: str | None = None, err=None) -> int:
    err = err or sys.stderr
    if as_json:
        payload = {"error": {"message": message}}
        if request_id:
            payload["request_id"] = request_id
        _json.dump(payload, err, indent=2, sort_keys=True)
        err.write("\n")
    else:
        err.write(f"error: {message}\n")
        if request_id:
            err.write(f"request_id: {request_id}\n")
    return code


def _build_client(args) -> AgroAIPlatformClient:
    return AgroAIPlatformClient(
        api_key=args.api_key or os.getenv("AGROAI_API_KEY", "") or None,
        base_url=args.base_url or None,
        timeout=args.timeout,
    )


# --------------------------------------------------------------------------- #
# command handlers
# --------------------------------------------------------------------------- #
def _cmd_doctor(args, out, err) -> int:
    """Environment + connectivity diagnostics. Never prints the key itself."""
    as_json = args.json
    key = args.api_key or os.getenv("AGROAI_API_KEY", "")
    base_url = args.base_url or os.getenv("AGROAI_BASE_URL", "https://api.agroai-pilot.com")
    checks: list[dict[str, Any]] = []

    key_present = bool(key)
    environment = "unknown"
    if key.startswith("agro_test_"):
        environment = "test"
    elif key.startswith("agro_live_"):
        environment = "live"
    # Only ever expose a short, non-reversible prefix — never the full key.
    key_display = (key[:14] + "…") if key_present else "(unset)"

    checks.append({"check": "AGROAI_API_KEY", "ok": key_present, "detail": key_display})
    checks.append({"check": "key_environment", "ok": environment in ("test", "live"), "detail": environment})
    checks.append({"check": "base_url", "ok": bool(base_url), "detail": base_url})

    reachable = False
    request_id = None
    if key_present:
        try:
            client = _build_client(args)
            resp = client.request("GET", "/v1/platform/me")
            reachable = True
            request_id = resp.request_id
            me = resp.data if hasattr(resp, "data") else resp
            checks.append({"check": "api_reachable", "ok": True, "detail": "/v1/platform/me responded"})
            checks.append({"check": "principal", "ok": True, "detail": _scalar(me)})
        except AgroAIPlatformError as exc:
            checks.append({"check": "api_reachable", "ok": False, "detail": f"{exc.status_code}: {exc}"})
            request_id = exc.request_id
        except Exception as exc:  # connectivity/config
            checks.append({"check": "api_reachable", "ok": False, "detail": str(exc)})
    else:
        checks.append({"check": "api_reachable", "ok": False, "detail": "skipped (no API key)"})

    if as_json:
        _emit({"checks": checks, "healthy": key_present and reachable}, as_json=True, out=out)
    else:
        for c in checks:
            mark = "PASS" if c["ok"] else "FAIL"
            out.write(f"[{mark}] {c['check']}: {c['detail']}\n")

    if not key_present:
        return EXIT_CONFIG
    return EXIT_OK if reachable else EXIT_CONFIG


def _cmd_me(args, out, err) -> int:
    client = _build_client(args)
    resp = client.request("GET", "/v1/platform/me")
    _emit(resp.data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_fields_list(args, out, err) -> int:
    client = _build_client(args)
    if args.all:
        items = list(client.iter_fields(page_size=min(max(args.limit, 1), 100)))
        _emit({"items": items, "count": len(items)}, as_json=args.json, out=out)
        return EXIT_OK
    resp = client.list_fields(cursor=args.cursor, limit=args.limit)
    _emit(resp.data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_fields_get(args, out, err) -> int:
    client = _build_client(args)
    resp = client.request("GET", f"/v1/platform/fields/{args.field_id}")
    _emit(resp.data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_usage(args, out, err) -> int:
    client = _build_client(args)
    resp = client.request("GET", "/v1/platform/usage")
    _emit(resp.data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_providers_list(args, out, err) -> int:
    client = _build_client(args)
    resp = client.request("GET", "/v1/platform/providers")
    _emit(resp.data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_providers_status(args, out, err) -> int:
    client = _build_client(args)
    resp = client.request("GET", f"/v1/platform/providers/{args.provider}")
    _emit(resp.data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_jobs_get(args, out, err) -> int:
    client = _build_client(args)
    resp = client.request("GET", f"/v1/platform/jobs/{args.job_id}")
    _emit(resp.data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_login(args, out, err) -> int:
    # Honest: do not fabricate a human session using a machine API key.
    return _fail(
        "Human control-plane sign-in (browser/device flow) is not yet available in the CLI. "
        "Create projects and keys in the Developer Console, then export AGROAI_API_KEY for data operations.",
        code=EXIT_ERROR,
        as_json=args.json,
        err=err,
    )


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agroai", description="AGRO-AI Platform API CLI")
    parser.add_argument("--version", action="version", version=f"agroai {_version()}")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--api-key", default=None, help="Override AGROAI_API_KEY.")
    parser.add_argument("--base-url", default=None, help="Override AGROAI_BASE_URL.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Request timeout seconds.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Diagnose configuration and connectivity.").set_defaults(func=_cmd_doctor)
    sub.add_parser("me", help="Show the authenticated principal.").set_defaults(func=_cmd_me)
    sub.add_parser("usage", help="Show usage summary.").set_defaults(func=_cmd_usage)
    sub.add_parser("login", help="(Not yet available) human control-plane sign-in.").set_defaults(func=_cmd_login)
    sub.add_parser("logout", help="(Not yet available) clear stored human session.").set_defaults(func=_cmd_login)

    p_fields = sub.add_parser("fields", help="Field resources.")
    fsub = p_fields.add_subparsers(dest="fields_command", required=True)
    p_fl = fsub.add_parser("list", help="List fields.")
    p_fl.add_argument("--limit", type=int, default=50)
    p_fl.add_argument("--cursor", default=None)
    p_fl.add_argument("--all", action="store_true", help="Follow cursor pagination to completion.")
    p_fl.set_defaults(func=_cmd_fields_list)
    p_fg = fsub.add_parser("get", help="Get a field by id.")
    p_fg.add_argument("field_id")
    p_fg.set_defaults(func=_cmd_fields_get)

    p_prov = sub.add_parser("providers", help="Provider readiness.")
    psub = p_prov.add_subparsers(dest="providers_command", required=True)
    psub.add_parser("list", help="List providers.").set_defaults(func=_cmd_providers_list)
    p_ps = psub.add_parser("status", help="Show a provider's readiness.")
    p_ps.add_argument("provider")
    p_ps.set_defaults(func=_cmd_providers_status)

    p_jobs = sub.add_parser("jobs", help="Asynchronous jobs.")
    jsub = p_jobs.add_subparsers(dest="jobs_command", required=True)
    p_jg = jsub.add_parser("get", help="Get a job by id.")
    p_jg.add_argument("job_id")
    p_jg.set_defaults(func=_cmd_jobs_get)

    return parser


def main(argv: list[str] | None = None, *, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args, out, err)
    except AgroAIPlatformError as exc:
        return _fail(str(exc), code=_exit_code_for(exc), as_json=args.json, request_id=exc.request_id, err=err)
    except ValueError as exc:
        # Raised e.g. when AGROAI_API_KEY is missing.
        return _fail(str(exc), code=EXIT_CONFIG, as_json=args.json, err=err)
    except KeyboardInterrupt:  # pragma: no cover
        return EXIT_ERROR
    except Exception as exc:  # connectivity and unexpected
        return _fail(str(exc), code=EXIT_ERROR, as_json=args.json, err=err)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
