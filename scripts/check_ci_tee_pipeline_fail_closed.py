#!/usr/bin/env python3
"""Verify that CI test failures cannot be hidden by tee.

No external YAML/Python dependencies: GitHub Actions syntax itself is
validated by actionlint in the same workflow. Here we intentionally execute
the exact inline test commands with stub executables that fail, proving the
substantive command exit status reaches GitHub while the diagnostic log
continues to be written.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    ".github/workflows/ci.yml": {
        "commercial_control_plane": 3,
        "portal_release_contract": 5,
    },
    ".github/workflows/i18n-inventory-ci.yml": {
        "exact-head-i18n-inventory": 1,
    },
}
FAIL_EXIT = 37
MARKER = "agroai_ci_injected_test_failure"


def jobs(text: str) -> dict[str, str]:
    """Only split on two-space top-level job keys, never on nested steps."""
    matches = list(re.finditer(r"(?m)^  ([A-Za-z0-9_-]+):\s*$", text))
    return {
        match.group(1): text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        for i, match in enumerate(matches)
    }


def piped_commands(body: str) -> list[tuple[str, str]]:
    """Extract simple inline run commands. The risk in these jobs was inline."""
    found = []
    for line in body.splitlines():
        match = re.match(r"^        run: (.+\|\s*tee\s+([^\s]+))\s*$", line)
        if match:
            found.append((match.group(1), match.group(2)))
    return found


def verify_job(path: str, name: str, expected_count: int) -> int:
    workflow = (ROOT / path).read_text(encoding="utf-8")
    body = jobs(workflow).get(name)
    assert body is not None, f"Required job removed: {path}:{name}"
    defaults = re.search(r"(?m)^    defaults:\n      run:\n(?:(?:        [^\n]*)\n)*", body)
    assert defaults and re.search(r"(?m)^        shell: bash\s*$", defaults.group()), (
        f"{path}:{name} must run Bash with pipefail, not GitHub's default bash -e"
    )
    commands = piped_commands(body)
    assert len(commands) == expected_count, (
        f"{path}:{name}: expected {expected_count} tee-piped CI checks; found {len(commands)}"
    )
    with tempfile.TemporaryDirectory(prefix="agroai-tee-contract-") as tmp:
        tmpdir = Path(tmp)
        stub_dir = tmpdir / "bin"
        stub_dir.mkdir()
        for command_name in ("python", "python3", "node"):
            stub = stub_dir / command_name
            stub.write_text(f'#!/bin/sh\nprintf "{MARKER}\\n"\nexit {FAIL_EXIT}\n')
            stub.chmod(0o755)
        env = {**os.environ, "PATH": str(stub_dir) + os.pathsep + os.environ.get("PATH", "")}
        for i, (command, report_name) in enumerate(commands):
            step_dir = tmpdir / f"step{i}"
            step_dir.mkdir()
            script = step_dir / "run.sh"
            script.write_text(command + "\n")
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                cwd=step_dir, env=env, capture_output=True, text=True, timeout=15,
            )
            assert result.returncode == FAIL_EXIT, (
                f"{path}:{name}: masked a failed checker: {command!r}; "
                f"exit={result.returncode} stdout={result.stdout} stderr={result.stderr}"
            )
            report = step_dir / report_name
            assert report.is_file() and MARKER in report.read_text(), (
                f"{path}:{name}: diagnostic report was lost for {command!r}"
            )
    return len(commands)


def main() -> None:
    checked = sum(
        verify_job(path, name, expected)
        for path, group in TARGETS.items()
        for name, expected in group.items()
    )
    # A negative control catches an accidentally weakened test.
    with tempfile.TemporaryDirectory(prefix="agroai-tee-negative-") as tmp:
        report = Path(tmp) / "report.log"
        old = subprocess.run(
            ["bash", "-e", "-c", f"bash -c 'echo {MARKER}; exit {FAIL_EXIT}' | tee {report}"],
            capture_output=True, text=True,
        )
        assert old.returncode == 0 and MARKER in report.read_text(), (
            "Negative control stopped reproducing the original masked-failure bug"
        )
    assert checked == 9, f"Expected to test 9 vulnerable checks, got {checked}"
    print(f"PASS: {checked} exact CI tee commands propagate failed checker exit while retaining logs")


if __name__ == "__main__":
    main()
