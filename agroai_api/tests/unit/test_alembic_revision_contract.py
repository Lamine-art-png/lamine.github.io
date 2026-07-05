from __future__ import annotations

import ast
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
MAX_REVISION_LENGTH = 32


def _literal_assignment(module: ast.Module, name: str) -> str | None:
    for node in module.body:
        value = None
        if isinstance(node, ast.Assign):
            matches = any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
            if matches:
                value = node.value
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def test_alembic_revision_ids_fit_existing_version_table_and_are_unique():
    revisions: dict[str, Path] = {}
    violations: list[str] = []

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _literal_assignment(module, "revision")
        if revision is None:
            violations.append(f"{path.name}: missing literal revision id")
            continue
        if len(revision) > MAX_REVISION_LENGTH:
            violations.append(
                f"{path.name}: revision {revision!r} is {len(revision)} chars; "
                f"max is {MAX_REVISION_LENGTH}"
            )
        previous = revisions.get(revision)
        if previous is not None:
            violations.append(
                f"{path.name}: duplicate revision {revision!r}; already in {previous.name}"
            )
        revisions[revision] = path

    assert not violations, "\n".join(violations)
