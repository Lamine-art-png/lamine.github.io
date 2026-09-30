#!/usr/bin/env python3
"""Inventory customer-facing English messages returned by the API.

Signup, sign-in, verification, recovery, preference and billing responses carry
human-readable English `detail`/`message` text that the portal renders. Listing
them in shared/ui-api-messages.en.json (content-addressed literal.* keys) puts
them in the canonical UI source, so every locale catalog translates them and
the portal's literal runtime localizes them wherever they are displayed.

  python3 scripts/i18n-extract-api-messages.py          # regenerate
  python3 scripts/i18n-extract-api-messages.py --check  # CI: fail on drift
"""
from __future__ import annotations

import ast
import hashlib
import re
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shared" / "ui-api-messages.en.json"
MODULES = [
    "agroai_api/app/api/v1/auth.py",
    "agroai_api/app/api/v1/billing.py",
    "agroai_api/app/api/v1/recovery_v2.py",
    "agroai_api/app/api/v1/preferences.py",
    "agroai_api/app/services/password_policy.py",
    "agroai_api/app/services/credential_recovery.py",
    "agroai_api/app/services/team_invitations.py",
    "agroai_api/app/api/v1/team_invitation_accept.py",
]
MESSAGE_KEYWORDS = {"detail", "message"}


def literal_key(text: str) -> str:
    return "literal." + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


INTERNAL = ("Stripe signature", "Stripe payload", "Stripe event", "webhook")


def customer_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if any(marker in text for marker in INTERNAL):
        return False
    # Only {identifier} placeholders are allowed (templates the portal fills).
    return len(text) >= 8 and " " in text and text[0].isupper() and not re.search(r"\{(?![A-Za-z_][A-Za-z0-9_]*\})", text) and "_" not in text.split()[0]


def extract(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        # detail="..." / message="..." keyword arguments
        if isinstance(node, ast.keyword) and node.arg in MESSAGE_KEYWORDS and isinstance(node.value, ast.Constant):
            if customer_text(node.value.value):
                found.add(node.value.value.strip())
        # {"message": "..."} / {"detail": "..."} payloads
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in MESSAGE_KEYWORDS and isinstance(value, ast.Constant):
                    if customer_text(value.value):
                        found.add(value.value.strip())
        # _error(status, code, "message") helper calls in the invitation service
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_error" and len(node.args) >= 3:
            message = node.args[2]
            if isinstance(message, ast.Constant) and customer_text(message.value):
                found.add(message.value.strip())
        # module constants such as GENERIC_MESSAGE = "..."
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(name.endswith(("_MESSAGE", "_ERROR")) for name in names) and customer_text(node.value.value):
                found.add(node.value.value.strip())
        # password policy returns its message strings directly (f-strings are
        # rendered with the module's integer constants)
        if path.name == "password_policy.py" and isinstance(node, ast.Return):
            if isinstance(node.value, ast.Constant) and customer_text(node.value.value):
                found.add(node.value.value.strip())
            elif isinstance(node.value, ast.JoinedStr):
                constants = {
                    t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                    for t in n.targets if isinstance(t, ast.Name)
                }
                parts = []
                for piece in node.value.values:
                    if isinstance(piece, ast.Constant):
                        parts.append(str(piece.value))
                    elif isinstance(piece, ast.FormattedValue) and isinstance(piece.value, ast.Name) and piece.value.id in constants:
                        parts.append(str(constants[piece.value.id]))
                    else:
                        parts = []
                        break
                if parts and customer_text("".join(parts)):
                    found.add("".join(parts).strip())
    return found


def main() -> None:
    messages: set[str] = set()
    for module in MODULES:
        messages |= extract(ROOT / module)
    catalog = {literal_key(text): text for text in sorted(messages)}
    content = json.dumps(dict(sorted(catalog.items())), ensure_ascii=False, indent=2) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != content:
            raise SystemExit("shared/ui-api-messages.en.json is stale: run python3 scripts/i18n-extract-api-messages.py")
        print(json.dumps({"status": "ok", "apiMessages": len(catalog)}))
        return
    OUT.write_text(content, encoding="utf-8")
    print(json.dumps({"apiMessages": len(catalog)}))


if __name__ == "__main__":
    main()
