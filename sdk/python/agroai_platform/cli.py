"""AGRO-AI Platform API command-line interface.

Human control-plane operations use the first-party browser/device session created
by ``agroai login``. Data-plane operations use a scoped ``agro_test_`` or
``agro_live_`` API key. The two credential classes are never interchanged.
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

SAFE_BOOTSTRAP_SCOPES = [
    "projects:read",
    "fields:read",
    "fields:write",
    "reports:read",
    "reports:write",
    "jobs:read",
    "usage:read",
]


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("agroai-platform")
    except Exception:  # pragma: no cover
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
        return "\n".join(f"{key}: {_scalar(value)}" for key, value in data.items())
    if isinstance(data, list):
        return "\n".join(str(_scalar(item)) for item in data)
    return str(data)


def _scalar(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return _json.dumps(value, default=str)
    return str(value)


def _exit_code_for(exc: AgroAIPlatformError) -> int:
    status = exc.status_code or 0
    if status in (401, 403): return EXIT_AUTH
    if status == 429: return EXIT_RATE_LIMITED
    if status == 404: return EXIT_NOT_FOUND
    return EXIT_ERROR


def _fail(message: str, *, code: int, as_json: bool, request_id: str | None = None, err=None) -> int:
    err = err or sys.stderr
    if as_json:
        payload: dict[str, Any] = {"error": {"message": message}}
        if request_id: payload["request_id"] = request_id
        _json.dump(payload, err, indent=2, sort_keys=True)
        err.write("\n")
    else:
        err.write(f"error: {message}\n")
        if request_id: err.write(f"request_id: {request_id}\n")
    return code


def _build_client(args) -> AgroAIPlatformClient:
    return AgroAIPlatformClient(
        api_key=args.api_key or os.getenv("AGROAI_API_KEY", "") or None,
        base_url=args.base_url or None,
        timeout=args.timeout,
    )


def _cmd_doctor(args, out, err) -> int:
    key = args.api_key or os.getenv("AGROAI_API_KEY", "")
    base_url = args.base_url or os.getenv("AGROAI_BASE_URL", "https://api.agroai-pilot.com")
    environment = "test" if key.startswith("agro_test_") else "live" if key.startswith("agro_live_") else "unknown"
    checks: list[dict[str, Any]] = [
        {"check": "AGROAI_API_KEY", "ok": bool(key), "detail": (key[:14] + "…") if key else "(unset)"},
        {"check": "key_environment", "ok": environment in {"test", "live"}, "detail": environment},
        {"check": "base_url", "ok": bool(base_url), "detail": base_url},
    ]
    reachable = False
    if key:
        try:
            resp = _build_client(args).request("GET", "/v1/platform/me")
            reachable = True
            checks.append({"check": "api_reachable", "ok": True, "detail": "/v1/platform/me responded"})
            checks.append({"check": "principal", "ok": True, "detail": _scalar(resp.data)})
        except AgroAIPlatformError as exc:
            checks.append({"check": "api_reachable", "ok": False, "detail": f"{exc.status_code}: {exc}"})
        except Exception as exc:
            checks.append({"check": "api_reachable", "ok": False, "detail": str(exc)})
    else:
        checks.append({"check": "api_reachable", "ok": False, "detail": "skipped (no API key)"})
    if args.json:
        _emit({"checks": checks, "healthy": bool(key) and reachable}, as_json=True, out=out)
    else:
        for check in checks:
            out.write(f"[{'PASS' if check['ok'] else 'FAIL'}] {check['check']}: {check['detail']}\n")
    return EXIT_OK if key and reachable else EXIT_CONFIG


def _cmd_me(args, out, err) -> int:
    _emit(_build_client(args).request("GET", "/v1/platform/me").data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_fields_list(args, out, err) -> int:
    client = _build_client(args)
    if args.all:
        items = list(client.iter_fields(page_size=min(max(args.limit, 1), 100)))
        _emit({"items": items, "count": len(items)}, as_json=args.json, out=out)
    else:
        _emit(client.list_fields(cursor=args.cursor, limit=args.limit).data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_fields_get(args, out, err) -> int:
    _emit(_build_client(args).request("GET", f"/v1/platform/fields/{args.field_id}").data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_fields_create(args, out, err) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.crop: payload["crop"] = args.crop
    if args.area_hectares is not None: payload["area_hectares"] = args.area_hectares
    try:
        data = _build_client(args).create_field(payload)
    except AgroAIPlatformError as exc:
        return _fail(str(exc), code=_exit_code_for(exc), as_json=args.json, request_id=exc.request_id, err=err)
    _emit(data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_usage(args, out, err) -> int:
    _emit(_build_client(args).request("GET", "/v1/platform/usage").data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_providers_list(args, out, err) -> int:
    _emit(_build_client(args).request("GET", "/v1/platform/providers").data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_providers_status(args, out, err) -> int:
    _emit(_build_client(args).request("GET", f"/v1/platform/providers/{args.provider}").data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_jobs_get(args, out, err) -> int:
    _emit(_build_client(args).request("GET", f"/v1/platform/jobs/{args.job_id}").data, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_login(args, out, err) -> int:
    from . import session as _session
    try:
        result = _session.login(args.base_url, printer=lambda message: print(message, file=err))
    except Exception as exc:
        return _fail(f"login failed: {exc}", code=EXIT_ERROR, as_json=args.json, err=err)
    _emit({"status": "logged_in", "organization_id": result.get("organization_id")}, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_logout(args, out, err) -> int:
    from . import session as _session
    _emit({"status": "logged_out", "server_revocation": _session.logout()}, as_json=args.json, out=out)
    return EXIT_OK


def _control_plane_json(
    args,
    method: str,
    path: str,
    *,
    json_body=None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from . import session as _session
    request_kwargs: dict[str, Any] = {"json_body": json_body, "timeout": args.timeout}
    if params is not None:
        request_kwargs["params"] = params
    response = _session.control_plane_request(method, path, **request_kwargs)
    payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"message": response.text}
    if response.status_code >= 400:
        message = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and isinstance(payload.get("detail"), dict):
            message = payload["detail"].get("message") or payload["detail"].get("code") or message
        raise RuntimeError(str(message or f"control-plane request failed with status {response.status_code}"))
    return payload if isinstance(payload, dict) else {"data": payload}


def _cp(
    args,
    method: str,
    path: str,
    *,
    json_body=None,
    params: dict[str, Any] | None = None,
    out=None,
    err=None,
) -> int:
    try:
        payload = _control_plane_json(args, method, path, json_body=json_body, params=params)
    except RuntimeError as exc:
        return _fail(str(exc), code=EXIT_ERROR, as_json=args.json, err=err)
    _emit(payload, as_json=args.json, out=out)
    return EXIT_OK


def _cmd_projects_list(args, out, err) -> int:
    return _cp(args, "GET", "/v1/platform/developer/projects", out=out, err=err)


def _cmd_projects_create(args, out, err) -> int:
    return _cp(args, "POST", "/v1/platform/developer/projects", json_body={"name": args.name, "environment": args.environment}, out=out, err=err)


def _cmd_service_accounts_list(args, out, err) -> int:
    return _fail(
        "service-account listing is not exposed by the current Platform API control plane",
        code=EXIT_USAGE,
        as_json=args.json,
        err=err,
    )


def _cmd_service_accounts_create(args, out, err) -> int:
    return _cp(
        args,
        "POST",
        f"/v1/platform/developer/projects/{args.project_id}/service-accounts",
        json_body={"name": args.name, "description": args.description, "scopes": args.scope or []},
        out=out,
        err=err,
    )


def _cmd_keys_list(args, out, err) -> int:
    return _cp(args, "GET", "/v1/platform/developer/keys", out=out, err=err)


def _cmd_keys_create(args, out, err) -> int:
    return _cp(args, "POST", f"/v1/platform/developer/service-accounts/{args.service_account_id}/keys", json_body={"name": args.name, "scopes": args.scope or []}, out=out, err=err)


def _cmd_keys_revoke(args, out, err) -> int:
    return _cp(args, "POST", f"/v1/platform/developer/keys/{args.key_id}/revoke", json_body={}, out=out, err=err)


def _cmd_keys_rotate(args, out, err) -> int:
    return _cp(args, "POST", f"/v1/platform/developer/keys/{args.key_id}/rotate", json_body={"overlap_minutes": args.overlap_minutes}, out=out, err=err)


def _cmd_webhooks_list(args, out, err) -> int:
    return _cp(args, "GET", "/v1/platform/developer/webhooks", out=out, err=err)


def _cmd_bootstrap(args, out, err) -> int:
    """Create the minimal safe TEST project -> service account -> key chain.

    Plaintext key output is deliberate and one-time, mirroring the backend
    creation response. The command never persists that key to disk.
    """
    scopes = args.scope or list(SAFE_BOOTSTRAP_SCOPES)
    try:
        project_payload = _control_plane_json(args, "POST", "/v1/platform/developer/projects", json_body={"name": args.name, "environment": "test"})
        project = project_payload.get("project") or {}
        project_id = project.get("id")
        if not project_id: raise RuntimeError("project creation did not return an id")
        service_payload = _control_plane_json(
            args,
            "POST",
            f"/v1/platform/developer/projects/{project_id}/service-accounts",
            json_body={"name": args.service_account_name, "description": "Created by agroai bootstrap", "scopes": scopes},
        )
        service_account = service_payload.get("service_account") or {}
        service_account_id = service_account.get("id")
        if not service_account_id: raise RuntimeError("service-account creation did not return an id")
        key_payload = _control_plane_json(
            args,
            "POST",
            f"/v1/platform/developer/service-accounts/{service_account_id}/keys",
            json_body={"name": args.key_name, "scopes": scopes},
        )
        plaintext = key_payload.get("plaintext_key")
        key = key_payload.get("key") or {}
        if not plaintext or not str(plaintext).startswith("agro_test_"):
            raise RuntimeError("TEST key creation did not return the expected one-time agro_test_ credential")
    except RuntimeError as exc:
        return _fail(str(exc), code=EXIT_ERROR, as_json=args.json, err=err)

    result = {
        "status": "ready",
        "environment": "test",
        "project_id": project_id,
        "service_account_id": service_account_id,
        "key_id": key.get("id"),
        "scopes": scopes,
        "api_key": plaintext,
        "plaintext_display": "one_time_only",
        "next": "export AGROAI_API_KEY='<api_key>' && agroai doctor",
    }
    _emit(result, as_json=args.json, out=out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agroai", description="AGRO-AI Platform API CLI")
    parser.add_argument("--version", action="version", version=f"agroai {_version()}")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--api-key", default=None, help="Override AGROAI_API_KEY.")
    parser.add_argument("--base-url", default=None, help="Override AGROAI_BASE_URL.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Request timeout seconds.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Diagnose data-plane configuration and connectivity.").set_defaults(func=_cmd_doctor)
    sub.add_parser("me", help="Show the authenticated API-key principal.").set_defaults(func=_cmd_me)
    sub.add_parser("usage", help="Show usage summary.").set_defaults(func=_cmd_usage)
    sub.add_parser("login", help="Sign in via browser device authorization.").set_defaults(func=_cmd_login)
    sub.add_parser("logout", help="Revoke and clear the stored human CLI session.").set_defaults(func=_cmd_logout)

    p_boot = sub.add_parser("bootstrap", help="Create a complete safe TEST project, service account, and one-time API key.")
    p_boot.add_argument("--name", default="AGRO-AI CLI quickstart", help="TEST project name.")
    p_boot.add_argument("--service-account-name", default="local-dev")
    p_boot.add_argument("--key-name", default="local-dev")
    p_boot.add_argument("--scope", action="append", help="Repeatable TEST-safe scope. Defaults to the quickstart scope set.")
    p_boot.set_defaults(func=_cmd_bootstrap)

    p_proj = sub.add_parser("projects", help="Platform API projects (human control plane).")
    projsub = p_proj.add_subparsers(dest="projects_command", required=True)
    projsub.add_parser("list", help="List projects.").set_defaults(func=_cmd_projects_list)
    p_pc = projsub.add_parser("create", help="Create a project.")
    p_pc.add_argument("--name", required=True)
    p_pc.add_argument("--environment", choices=["test", "live"], default="test")
    p_pc.set_defaults(func=_cmd_projects_create)

    p_sa = sub.add_parser("service-accounts", help="Project service accounts (human control plane).")
    sasub = p_sa.add_subparsers(dest="service_accounts_command", required=True)
    p_sal = sasub.add_parser("list", help="Report whether service-account listing is available.")
    p_sal.add_argument("--project-id", default=None)
    p_sal.set_defaults(func=_cmd_service_accounts_list)
    p_sac = sasub.add_parser("create", help="Create a service account.")
    p_sac.add_argument("--project-id", required=True)
    p_sac.add_argument("--name", required=True)
    p_sac.add_argument("--description", default=None)
    p_sac.add_argument("--scope", action="append", required=True, help="Repeatable scope.")
    p_sac.set_defaults(func=_cmd_service_accounts_create)

    p_keys = sub.add_parser("keys", help="Platform API keys (human control plane).")
    keysub = p_keys.add_subparsers(dest="keys_command", required=True)
    keysub.add_parser("list", help="List API keys.").set_defaults(func=_cmd_keys_list)
    p_kc = keysub.add_parser("create", help="Create a key under a service account.")
    p_kc.add_argument("--service-account-id", required=True)
    p_kc.add_argument("--name", required=True)
    p_kc.add_argument("--scope", action="append", help="Repeatable scope; subset of the service account.")
    p_kc.set_defaults(func=_cmd_keys_create)
    p_kr = keysub.add_parser("revoke", help="Revoke a key.")
    p_kr.add_argument("key_id")
    p_kr.set_defaults(func=_cmd_keys_revoke)
    p_krt = keysub.add_parser("rotate", help="Rotate a key.")
    p_krt.add_argument("key_id")
    p_krt.add_argument("--overlap-minutes", type=int, default=0)
    p_krt.set_defaults(func=_cmd_keys_rotate)

    p_wh = sub.add_parser("webhooks", help="Webhook endpoints (human control plane).")
    whsub = p_wh.add_subparsers(dest="webhooks_command", required=True)
    whsub.add_parser("list", help="List webhook endpoints.").set_defaults(func=_cmd_webhooks_list)

    p_fields = sub.add_parser("fields", help="Field resources (API-key data plane).")
    fsub = p_fields.add_subparsers(dest="fields_command", required=True)
    p_fl = fsub.add_parser("list", help="List fields.")
    p_fl.add_argument("--limit", type=int, default=50)
    p_fl.add_argument("--cursor", default=None)
    p_fl.add_argument("--all", action="store_true")
    p_fl.set_defaults(func=_cmd_fields_list)
    p_fg = fsub.add_parser("get", help="Get a field by id.")
    p_fg.add_argument("field_id")
    p_fg.set_defaults(func=_cmd_fields_get)
    p_fc = fsub.add_parser("create", help="Create a field.")
    p_fc.add_argument("--name", required=True)
    p_fc.add_argument("--crop", default=None)
    p_fc.add_argument("--area-hectares", type=float, default=None)
    p_fc.set_defaults(func=_cmd_fields_create)

    p_prov = sub.add_parser("providers", help="Provider readiness.")
    psub = p_prov.add_subparsers(dest="providers_command", required=True)
    psub.add_parser("list", help="List providers.").set_defaults(func=_cmd_providers_list)
    p_ps = psub.add_parser("status", help="Show provider readiness.")
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
        return _fail(str(exc), code=EXIT_CONFIG, as_json=args.json, err=err)
    except KeyboardInterrupt:  # pragma: no cover
        return EXIT_ERROR
    except Exception as exc:
        return _fail(str(exc), code=EXIT_ERROR, as_json=args.json, err=err)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())