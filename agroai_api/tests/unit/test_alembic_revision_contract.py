import ast
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
MAX_REVISION_LENGTH = 32


def _literal_assignment(module, name):
    for node in module.body:
        value = None
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                value = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def test_alembic_revision_ids_fit_existing_version_table_and_are_unique():
    revisions = {}
    violations = []
    paths = [path for path in VERSIONS_DIR.glob("*.py") if not path.name.startswith("__")]

    for path in sorted(paths):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _literal_assignment(module, "revision")
        if revision is None:
            violations.append(f"{path.name}: missing literal revision id")
            continue
        if len(revision) > MAX_REVISION_LENGTH:
            violations.append(
                f"{path.name}: revision {revision!r} is {len(revision)} chars; max is {MAX_REVISION_LENGTH}"
            )
        previous = revisions.get(revision)
        if previous is not None:
            violations.append(f"{path.name}: duplicate revision {revision!r}; already in {previous.name}")
        revisions[revision] = path

    assert not violations, "\n".join(violations)
