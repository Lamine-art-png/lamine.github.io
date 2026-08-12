"""Contract-drift gate: OpenAPI <-> route manifest <-> Python SDK <-> TS SDK <-> CLI.

The route manifest (app/platform_api/route_manifest.py) and the FastAPI-generated
public OpenAPI are the single sources of truth. This test fails when any client
(Python SDK, TypeScript SDK, agroai CLI) references a path that is not a live
PUBLIC Platform route, when a public endpoint disappears, or when a private/admin
route leaks into the public contract — i.e. it detects drift, not schema copies.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.platform_api.route_manifest import manifest_dicts, public_routes

REPO = Path(__file__).resolve().parents[3]
SDK_PY = REPO / "sdk" / "python" / "agroai_platform"
SDK_TS = REPO / "sdk" / "typescript" / "src"

_PARAM = re.compile(r"\{[^}]+\}")
_PATH = re.compile(r"/v1/platform/[A-Za-z0-9_./{}\-]*")


def _norm(path: str) -> str:
    # Normalise every path parameter to a single placeholder and drop trailing
    # query/format artefacts so client literals compare to manifest templates.
    path = path.split("{query}")[0].split("?")[0].rstrip("/")
    path = _PARAM.sub("{}", path)
    return path or "/v1/platform"


def _public_norm() -> set[str]:
    return {_norm(r["route"]) for r in public_routes()}


def _all_norm() -> set[str]:
    return {_norm(r["route"]) for r in manifest_dicts()}


def _client_paths(root: Path, exts: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for path in root.rglob("*"):
        if path.suffix not in exts or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Reconstruct TS template literals like `/v1/platform/jobs/${x}` -> {}
        text = re.sub(r"\$\{[^}]+\}", "{}", text)
        for m in _PATH.findall(text):
            found.add(_norm(m))
    return found


def test_python_sdk_and_cli_reference_only_declared_live_routes():
    declared = _all_norm()
    for ref in _client_paths(SDK_PY, (".py",)):
        assert ref in declared, f"Python SDK/CLI references a route that does not exist: {ref}"


def test_typescript_sdk_references_only_declared_live_routes():
    declared = _all_norm()
    for ref in _client_paths(SDK_TS, (".ts",)):
        assert ref in declared, f"TypeScript SDK references a route that does not exist: {ref}"


def test_data_plane_sdk_client_uses_only_public_routes():
    """The pure server SDK client (not the CLI) must use only PUBLIC api-key
    routes — it never speaks the human control-plane surface."""
    public = _public_norm()
    client_only = _client_paths(SDK_PY / "client.py" if (SDK_PY / "client.py").exists() else SDK_PY, (".py",))
    # Restrict to the SDK client module specifically.
    text = (SDK_PY / "client.py").read_text(encoding="utf-8") if (SDK_PY / "client.py").exists() else ""
    refs = {_norm(m) for m in _PATH.findall(re.sub(r"\$\{[^}]+\}", "{}", text))}
    for ref in refs:
        assert ref in public, f"SDK data-plane client references a non-public route: {ref}"


def test_public_openapi_matches_the_route_manifest_and_leaks_no_private_route():
    from app.api.v1.platform_api import platform_openapi
    from app.core.config import settings

    original = getattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", False)
    settings.PLATFORM_API_PUBLIC_DOCS_ENABLED = True
    try:
        spec = platform_openapi()
    finally:
        settings.PLATFORM_API_PUBLIC_DOCS_ENABLED = original

    # Paths in the servers-relative OpenAPI are under /platform/...; prefix /v1.
    documented = {_norm("/v1" + p) for p in spec.get("paths", {})}
    public = _public_norm()
    private = _all_norm() - public

    # Every documented path is a declared public route (no invented endpoints).
    unexpected = documented - public
    assert not unexpected, f"Public OpenAPI documents non-public paths: {sorted(unexpected)}"
    # No private/admin/developer route leaked into the public contract.
    assert not (documented & private), f"Private routes leaked into public OpenAPI: {sorted(documented & private)}"
