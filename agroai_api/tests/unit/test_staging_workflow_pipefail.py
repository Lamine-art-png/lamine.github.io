"""The staging workflow must fail when a checker piped into ``tee`` fails.

GitHub runs an unspecified shell as ``bash -e {0}`` (no pipefail), so
``checker | tee report`` exits 0 even when the checker exits 1. With
``shell: bash`` it runs ``bash --noprofile --norc -eo pipefail {0}``. These
tests execute the exact step scripts with a failing ``python`` stub rather
than only checking YAML syntax.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "field-intelligence-staging.yml"
GITHUB_BASH = ["bash", "--noprofile", "--norc", "-eo", "pipefail"]   # shell: bash
GITHUB_DEFAULT = ["bash", "-e"]                                      # shell unspecified
QUALIFY_STEPS = (
    "Validate immutable staging resource identities",
    "Preflight the staging database upgrade path (read-only)",
)


def _steps(text: str) -> list[dict]:
    """Minimal step extraction (name, shell, run) without a YAML dependency."""
    lines = text.splitlines()
    steps: list[dict] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)- name: (.+)$", line)
        if not match:
            continue
        indent = len(match.group(1))
        step = {"name": match.group(2).strip(), "shell": None, "run": None}
        cursor = index + 1
        while cursor < len(lines):
            current = lines[cursor]
            if current.strip() and (len(current) - len(current.lstrip())) <= indent:
                break
            key = re.match(r"^\s+(shell|run):\s*(.*)$", current)
            if key and key.group(1) == "shell":
                step["shell"] = key.group(2).strip()
            elif key and key.group(1) == "run":
                value = key.group(2).strip()
                if value in {"|", "|-", ">", ">-"}:
                    body, cursor = [], cursor + 1
                    while cursor < len(lines) and (not lines[cursor].strip()
                                                   or len(lines[cursor]) - len(lines[cursor].lstrip()) > indent + 2):
                        body.append(lines[cursor])
                        cursor += 1
                    width = min((len(row) - len(row.lstrip()) for row in body if row.strip()), default=0)
                    step["run"] = "\n".join(row[width:] for row in body).rstrip() + "\n"
                    continue
                step["run"] = value + "\n"
            cursor += 1
        steps.append(step)
    return steps


def _workflow_default_shell(text: str) -> str | None:
    match = re.search(r"^defaults:\n\s+run:\n\s+shell:\s*(\S+)", text, re.MULTILINE)
    return match.group(1) if match else None


def test_every_tee_pipeline_runs_with_pipefail():
    text = WORKFLOW.read_text()
    default = _workflow_default_shell(text)
    piped = [step for step in _steps(text) if step["run"] and re.search(r"\|\s*tee\b", step["run"])]
    assert piped, "expected tee pipelines in the staging workflow"
    for step in piped:
        assert (step["shell"] or default) == "bash", step["name"]


@pytest.mark.parametrize("step_name", QUALIFY_STEPS)
@pytest.mark.parametrize("shell", [GITHUB_BASH, GITHUB_DEFAULT], ids=["shell_bash", "unspecified_shell"])
def test_a_failing_checker_fails_the_step_and_still_writes_its_report(tmp_path, step_name, shell):
    step = next(step for step in _steps(WORKFLOW.read_text()) if step["name"] == step_name)
    script = tmp_path / "step.sh"
    script.write_text(step["run"])
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name in ("python", "python3"):
        stub = stubs / name
        stub.write_text('#!/bin/sh\necho \'{"status": "refused", "reason": "staging matches production"}\'\nexit 1\n')
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    workdir = tmp_path / "agroai_api"   # the steps run in agroai_api and write ../<report>.json
    workdir.mkdir()
    env = {**os.environ, "PATH": f"{stubs}:{os.environ.get('PATH', '')}",
           "FIELD_STAGING_DATABASE_URL": "postgresql://synthetic.invalid/staging"}
    result = subprocess.run([*shell, str(script)], cwd=workdir, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, (step_name, result.stdout, result.stderr)
    reports = list(tmp_path.glob("staging-*.json"))
    assert reports and "refused" in reports[0].read_text()


def test_the_old_single_line_pipeline_was_fail_open(tmp_path):
    """Documents the bug: without pipefail the step exited 0 although the checker failed."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    stub = stubs / "python"
    stub.write_text("#!/bin/sh\necho '{}'\nexit 1\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    script = tmp_path / "old.sh"
    script.write_text("python scripts/field_intelligence_staging_contract.py | tee report.json\n")
    env = {**os.environ, "PATH": f"{stubs}:{os.environ.get('PATH', '')}"}
    assert subprocess.run([*GITHUB_DEFAULT, str(script)], cwd=tmp_path, env=env).returncode == 0
    assert subprocess.run([*GITHUB_BASH, str(script)], cwd=tmp_path, env=env).returncode != 0
