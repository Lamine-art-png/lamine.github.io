#!/usr/bin/env python3
"""Fail CI when repository content contains a recognizable production secret."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAX_FILE_BYTES = 5 * 1024 * 1024

# High-confidence credential formats only. Keep this list conservative enough to
# run across the entire repository without flagging ordinary identifiers.
PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "aws_secret_access_key_literal": re.compile(
        rb"\bAWS_SECRET_ACCESS_KEY\b\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40}\b"
    ),
    "stripe_live_key": re.compile(rb"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
    "github_token": re.compile(
        rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b"
    ),
    "slack_token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "webhook_secret": re.compile(rb"\bwhsec_[A-Za-z0-9]{24,}\b"),
    "platform_api_key": re.compile(rb"\bagro_(?:test|live)_[A-Za-z0-9_-]{24,}\b"),
    "postman_api_key": re.compile(rb"\bPMAK-[A-Za-z0-9-]{20,}\b"),
    "openai_api_key": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    "google_api_key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    "google_oauth_client_secret": re.compile(rb"\bGOCSPX-[0-9A-Za-z_-]{20,}\b"),
    "sendgrid_api_key": re.compile(rb"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{20,}\b"),
    "resend_api_key": re.compile(rb"\bre_[A-Za-z0-9]{24,}\b"),
    # OpenWeather keys are opaque 32-hex strings, so require the credential
    # variable name as context to avoid false positives on hashes.
    "openweather_api_key_literal": re.compile(
        rb"\bOPENWEATHER_API_KEY\b\s*[:=]\s*[\"']?[a-fA-F0-9]{32}\b"
    ),
    "cloudflare_api_token_literal": re.compile(
        rb"\bCLOUDFLARE_API_TOKEN\b\s*[:=]\s*[\"']?[A-Za-z0-9_-]{30,}\b"
    ),
}


def repository_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def main() -> int:
    paths = repository_paths()
    findings: list[str] = []
    for path in paths:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(data):
                findings.append(f"{path.relative_to(ROOT)}: {name}")
    if findings:
        raise SystemExit(
            "Potential committed secrets detected. Treat every match as compromised, "
            "remove it from the commit, and rotate the credential before proceeding:\n"
            + "\n".join(sorted(findings))
        )
    print(f"Secret scan passed across {len(paths)} repository paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
