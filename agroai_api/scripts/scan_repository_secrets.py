#!/usr/bin/env python3
"""Fail CI when repository content contains a recognizable production secret."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAX_FILE_BYTES = 5 * 1024 * 1024
PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "stripe_live_key": re.compile(rb"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
    "github_token": re.compile(rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),
    "slack_token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "webhook_secret": re.compile(rb"\bwhsec_[A-Za-z0-9]{24,}\b"),
    "platform_api_key": re.compile(rb"\bagro_(?:test|live)_[A-Za-z0-9_-]{24,}\b"),
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
    findings: list[str] = []
    for path in repository_paths():
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(data):
                findings.append(f"{path.relative_to(ROOT)}: {name}")
    if findings:
        raise SystemExit("Potential committed secrets detected:\n" + "\n".join(sorted(findings)))
    print(f"Secret scan passed across {len(repository_paths())} repository paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
