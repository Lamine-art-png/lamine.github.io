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


def test_account_verification_platform_api_and_appeal_revisions_form_one_linear_tail():
    expected_tail = {
        "019_account_verification": "018_outreach_engagement",
        "020_platform_api_private_beta": "019_account_verification",
        "021_platform_api_hardening": "020_platform_api_private_beta",
        "022_account_access_appeals": "021_platform_api_hardening",
        "023_field_intelligence": "022_account_access_appeals",
        # Two independent tails branch off 023 and are reconciled by the
        # 027 merge revision (asserted separately below).
        "024_field_intelligence_launch": "023_field_intelligence",
        "024_platform_api_programs": "023_field_intelligence",
        "025_platform_api_commerce": "024_platform_api_programs",
        "026_platform_api_operations": "025_platform_api_commerce",
    }
    actual_tail = {}

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _literal_assignment(module, "revision")
        if revision in expected_tail:
            actual_tail[revision] = _literal_assignment(module, "down_revision")

    assert actual_tail == expected_tail
    all_down_revisions = set(actual_tail.values())
    assert "019_platform_api_private_beta" not in all_down_revisions
    assert "020_platform_api_hardening" not in actual_tail


def _all_revisions_and_down_revisions():
    """Return (revisions, edges) where edges maps child -> set(parents).

    Handles both string and tuple ``down_revision`` declarations so merge
    revisions with multiple parents are represented correctly.
    """
    revisions: set[str] = set()
    edges: dict[str, set[str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _literal_assignment(module, "revision")
        if revision is None:
            continue
        revisions.add(revision)
        parents: set[str] = set()
        for node in module.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "down_revision" for t in node.targets
            ):
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parents.add(value.value)
                elif isinstance(value, (ast.Tuple, ast.List)):
                    for elt in value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            parents.add(elt.value)
        edges[revision] = parents
    return revisions, edges


def test_migration_graph_has_exactly_one_head():
    """No revision may be left as an unreferenced head except the single tip."""
    revisions, edges = _all_revisions_and_down_revisions()
    referenced_parents: set[str] = set()
    for parents in edges.values():
        referenced_parents |= parents
    heads = {rev for rev in revisions if rev not in referenced_parents}
    assert heads == {"027_merge_fi_and_platform_api"}, (
        f"expected exactly one Alembic head, found: {sorted(heads)}"
    )


def test_merge_revision_reconciles_both_feature_tails():
    _, edges = _all_revisions_and_down_revisions()
    assert edges.get("027_merge_fi_and_platform_api") == {
        "024_field_intelligence_launch",
        "026_platform_api_operations",
    }
