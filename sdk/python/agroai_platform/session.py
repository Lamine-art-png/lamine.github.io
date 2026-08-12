"""Human CLI session: RFC 8628 device login, secure storage, control-plane calls.

The human control-plane credential (a short-lived org-scoped JWT obtained via the
browser-assisted device flow) is stored in the OS keychain when available, else
in a 0600-permission file under the user config directory. An API key is never
used as human identity, and no client secret is embedded in the CLI.
"""
from __future__ import annotations

import json
import os
import stat
import time
import webbrowser
from pathlib import Path
from typing import Any

import httpx

SERVICE = "agroai-cli"
_ACCOUNT = "human-session"
DEFAULT_BASE_URL = "https://api.agroai-pilot.com"


def _config_path() -> Path:
    root = Path(os.getenv("AGROAI_CONFIG_HOME", Path.home() / ".config" / "agroai"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "session.json"


def _keyring():
    try:
        import keyring  # type: ignore

        return keyring
    except Exception:
        return None


def save_session(data: dict[str, Any]) -> None:
    payload = json.dumps(data)
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, _ACCOUNT, payload)
            return
        except Exception:
            pass
    path = _config_path()
    path.write_text(payload, encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600, owner-only


def load_session() -> dict[str, Any] | None:
    kr = _keyring()
    if kr is not None:
        try:
            raw = kr.get_password(SERVICE, _ACCOUNT)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    path = _config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def clear_session() -> bool:
    removed = False
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, _ACCOUNT)
            removed = True
        except Exception:
            pass
    path = _config_path()
    if path.exists():
        path.unlink()
        removed = True
    return removed


def login(base_url: str | None = None, *, open_browser: bool = True, timeout: float = 300.0, printer=print) -> dict[str, Any]:
    """Run the device-authorization flow and persist the resulting session."""
    base = (base_url or os.getenv("AGROAI_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    with httpx.Client(timeout=20.0) as client:
        started = client.post(f"{base}/v1/platform/cli/device/authorization", json={"client_label": "agroai-cli"})
        started.raise_for_status()
        body = started.json()
        device_code = body["device_code"]
        user_code = body["user_code"]
        verify = body.get("verification_uri_complete") or body.get("verification_uri")
        interval = max(1, int(body.get("interval", 5)))
        printer(f"To authorize the agroai CLI, visit:\n  {verify}\nand confirm the code: {user_code}")
        if open_browser and verify:
            try:
                webbrowser.open(verify)
            except Exception:
                pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(interval)
            polled = client.post(f"{base}/v1/platform/cli/device/token", json={"device_code": device_code})
            data = polled.json() if polled.headers.get("content-type", "").startswith("application/json") else {}
            status = data.get("status")
            if status == "approved" and data.get("access_token"):
                session = {
                    "access_token": data["access_token"],
                    "base_url": base,
                    "organization_id": data.get("organization_id"),
                    "obtained_at": int(time.time()),
                }
                save_session(session)
                return session
            if status == "slow_down":
                interval += 2
                continue
            if status in {"authorization_pending", None}:
                continue
            raise RuntimeError(f"device authorization failed: {status}")
        raise TimeoutError("device authorization timed out before approval")


def control_plane_request(method: str, path: str, *, json_body: Any = None, timeout: float = 20.0) -> httpx.Response:
    session = load_session()
    if not session or not session.get("access_token"):
        raise RuntimeError("not logged in — run `agroai login` first")
    base = session["base_url"].rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        return client.request(
            method,
            f"{base}{path}",
            headers={"Authorization": f"Bearer {session['access_token']}", "Content-Type": "application/json"},
            json=json_body,
        )
