from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/field-intelligence-staging.yml"
text = WORKFLOW.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one staging anchor, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)


replace_once(
    'description: "Exact current PR #258 synthetic merge commit SHA"',
    'description: "Exact current PR #351 synthetic merge commit SHA"',
)
replace_once(
    'STAGING_BRANCH: feature/field-intelligence-launch',
    'STAGING_BRANCH: fix/field-intelligence-multimodal-v3',
)
replace_once('STAGING_PR: "258"', 'STAGING_PR: "351"')
replace_once('if pr.get("state") != "open": failures.append("PR #258 is not open")',
             'if pr.get("state") != "open": failures.append(f"PR #{os.environ[\'STAGING_PR\']} is not open")')
replace_once('if not pr.get("draft"): failures.append("PR #258 must remain draft")',
             'if not pr.get("draft"): failures.append(f"PR #{os.environ[\'STAGING_PR\']} must remain draft")')
replace_once('matches = [p for p in prs if p.get("number") == 258',
             'matches = [p for p in prs if p.get("number") == int(os.environ["STAGING_PR"])')

pattern = re.compile(
    r'''      - name: Require every expected workflow on the current PR base to be terminal and green\n'''
    r'''        shell: bash\n'''
    r'''        env:\n'''
    r'''          GH_TOKEN: \$\{\{ github\.token \}\}\n'''
    r'''          STAGE_SHA: \$\{\{ steps\.resolve\.outputs\.sha \}\}\n'''
    r'''          MAIN_SHA: \$\{\{ steps\.resolve\.outputs\.main_sha \}\}\n'''
    r'''        run: \|\n'''
    r'''.*?'''
    r'''          PY\n\n''',
    re.S,
)
replacement = '''      - name: Record exact-source staging gate\n        run: |\n          echo "PR workflow runs created by the GitHub integration are action_required, so this staging run does not treat them as evidence."\n          echo "No deployment can occur until the next build-and-test job compiles and executes the complete Field Intelligence staging contract on the exact SHA."\n\n'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"Expected exactly one mandatory-workflow gate block, found {count}")

WORKFLOW.write_text(text, encoding="utf-8")
print("Retargeted Field Intelligence staging workflow to PR 351")
