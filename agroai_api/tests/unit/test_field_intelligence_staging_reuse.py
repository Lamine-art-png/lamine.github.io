"""Reusing an existing staging database left at an earlier launch revision.

The existing staging database was migrated to 027_field_intelligence_launch
in July; the repository head has moved on. Preflight must accept any revision
on the linear path from the rollback floor to the head (so the database can
be upgraded in place) and refuse anything unknown.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = API_ROOT / "scripts" / "field_intelligence_migration.py"


def _run(*args: str, url: str) -> tuple[int, dict | str]:
    env = {**os.environ, "DATABASE_URL": url}
    proc = subprocess.run(list(args), capture_output=True, text=True, timeout=600, cwd=API_ROOT, env=env)
    stdout = proc.stdout.strip()
    try:
        return proc.returncode, json.loads(stdout[stdout.index("{"):])
    except ValueError:
        return proc.returncode, stdout + proc.stderr


def _migration(command: str, url: str) -> tuple[int, dict | str]:
    return _run(sys.executable, str(SCRIPT), command, "--database-url", url, url=url)


def test_database_at_an_earlier_launch_revision_is_a_supported_baseline(tmp_path):
    url = f"sqlite:///{tmp_path}/staging.db"
    code, output = _run(sys.executable, "-m", "alembic", "upgrade", "027_field_intelligence_launch", url=url)
    assert code == 0, output

    code, payload = _migration("preflight", url)
    assert code == 0 and payload["ok"], payload
    assert payload["current_revision"] == "027_field_intelligence_launch"
    assert payload["upgrade_needed"] is True

    code, payload = _migration("upgrade", url)
    assert code == 0 and payload["ok"], payload
    code, payload = _migration("verify", url)
    assert code == 0 and payload["ok"], payload


def test_unknown_revision_is_refused(tmp_path):
    url = f"sqlite:///{tmp_path}/unknown.db"
    code, output = _run(sys.executable, "-m", "alembic", "upgrade", "026_platform_api_operations", url=url)
    assert code == 0, output
    with sqlite3.connect(tmp_path / "unknown.db") as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'zzz_not_a_revision'")
    code, payload = _migration("preflight", url)
    assert code != 0
    assert "not on the supported upgrade path" in json.dumps(payload)
