from __future__ import annotations

import re
import subprocess
from pathlib import Path


def read(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str | Path, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def tracked_files() -> list[Path]:
    return [Path(p) for p in subprocess.check_output(["git", "ls-files"], text=True).splitlines()]


def replace_in_tracked(old: str, new: str) -> None:
    for path in tracked_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")


# The launch migration is rebased after the Platform API product tail.
replace_in_tracked("024_field_intelligence_launch", "027_field_intelligence_launch")

migration = Path("agroai_api/alembic/versions/027_field_intelligence_launch.py")
text = migration.read_text(encoding="utf-8")
text = text.replace(
    "Revision ID: 027_field_intelligence_launch\nRevises: 023_field_intelligence",
    "Revision ID: 027_field_intelligence_launch\nRevises: 026_platform_api_operations",
)
text = text.replace(
    'down_revision = "023_field_intelligence"',
    'down_revision = "026_platform_api_operations"',
)
migration.write_text(text, encoding="utf-8")

# Current-main schema contract plus Field Intelligence launch tables.
path = "agroai_api/app/db/schema_contract.py"
text = read(path).replace(
    'HEAD_ALEMBIC_REVISION = "026_platform_api_operations"',
    'HEAD_ALEMBIC_REVISION = "027_field_intelligence_launch"',
)
if '"field_runtime_flags"' not in text:
    marker = '    "platform_abuse_events": {"id", "organization_id", "signal_type", "status"},\n}'
    replacement = (
        '    "platform_abuse_events": {"id", "organization_id", "signal_type", "status"},\n'
        '    "field_runtime_flags": {"key", "value_json", "updated_at"},\n'
        '    "field_worker_heartbeats": {"worker_id", "git_sha", "last_heartbeat_at"},\n}'
    )
    if marker not in text:
        raise SystemExit("schema contract insertion marker missing")
    text = text.replace(marker, replacement)
write(path, text)

# Linear Alembic ancestry contract.
path = "agroai_api/tests/unit/test_alembic_revision_contract.py"
text = read(path)
marker = '        "026_platform_api_operations": "025_platform_api_commerce",'
addition = marker + '\n        "027_field_intelligence_launch": "026_platform_api_operations",'
if '"027_field_intelligence_launch": "026_platform_api_operations"' not in text:
    if marker not in text:
        raise SystemExit("alembic ancestry marker missing")
    text = text.replace(marker, addition)
write(path, text)

path = "agroai_api/tests/unit/test_schema_adoption_contract.py"
text = read(path)
text = text.replace(
    "def test_head_contract_covers_security_queue_provenance_access_appeals_and_platform_api():",
    "def test_head_contract_covers_security_queue_provenance_access_appeals_platform_api_and_field_launch():",
)
text = text.replace(
    'assert HEAD_ALEMBIC_REVISION == "026_platform_api_operations"',
    'assert HEAD_ALEMBIC_REVISION == "027_field_intelligence_launch"',
)
if 'HEAD_SCHEMA_REQUIREMENTS["field_runtime_flags"]' not in text:
    text += (
        '\n    assert {"key", "value_json", "updated_at"}.issubset('
        'HEAD_SCHEMA_REQUIREMENTS["field_runtime_flags"])\n'
        '    assert {"worker_id", "git_sha", "last_heartbeat_at"}.issubset('
        'HEAD_SCHEMA_REQUIREMENTS["field_worker_heartbeats"])\n'
    )
write(path, text)

for path in (".github/workflows/ci.yml", ".github/workflows/hardening-backend-reusable.yml"):
    text = read(path).replace(
        "026_platform_api_operations (head)", "027_field_intelligence_launch (head)"
    )
    write(path, text)

# Field Intelligence migration tooling now removes only launch-control tables.
path = "agroai_api/scripts/field_intelligence_migration.py"
text = read(path)
text = text.replace(
    "downgrade        — advisory-locked rollback to 022_account_access_appeals",
    "downgrade        — advisory-locked rollback to 026_platform_api_operations",
)
text = text.replace(
    "The rollback floor is ``022_account_access_appeals``: rolling back removes\nField Intelligence schema only",
    "The rollback floor is ``026_platform_api_operations``: rolling back removes\nonly the Field Intelligence launch-control schema",
)
text = text.replace(
    'ROLLBACK_FLOOR = "022_account_access_appeals"',
    'ROLLBACK_FLOOR = "026_platform_api_operations"',
)
start = text.index("FIELD_TABLES = {")
end = text.index("PRESERVED_TABLES = {", start)
sets = '''FIELD_FOUNDATION_TABLES = {
    "field_capture_sessions",
    "field_observations",
    "field_observation_assets",
    "field_observation_processing_runs",
    "field_observation_audit_events",
    "field_storage_reservations",
}
FIELD_LAUNCH_TABLES = {
    "field_runtime_flags",
    "field_worker_heartbeats",
}
FIELD_TABLES = FIELD_FOUNDATION_TABLES | FIELD_LAUNCH_TABLES

'''
text = text[:start] + sets + text[end:]
preserved_marker = '    "workspaces",\n}'
preserved_addition = '''    "workspaces",
    "field_capture_sessions",
    "field_observations",
    "field_observation_assets",
    "field_observation_processing_runs",
    "field_observation_audit_events",
    "field_storage_reservations",
    "platform_api_applications",
    "platform_program_enrollments",
    "platform_live_access_requests",
    "platform_partner_dossiers",
    "platform_terms_documents",
    "platform_terms_acceptances",
    "platform_api_plans",
    "platform_api_operation_costs",
    "platform_api_subscriptions",
    "platform_credit_reservations",
    "platform_status_components",
    "platform_abuse_events",
}'''
if preserved_marker not in text:
    raise SystemExit("migration preserved-table marker missing")
text = text.replace(preserved_marker, preserved_addition, 1)
old = '''    leftover = FIELD_TABLES & tables
    if leftover:
        _fail(report, f"rollback left Field Intelligence tables behind: {sorted(leftover)}")
    missing = PRESERVED_TABLES - tables
'''
new = '''    leftover = FIELD_LAUNCH_TABLES & tables
    if leftover:
        _fail(report, f"rollback left Field Intelligence launch tables behind: {sorted(leftover)}")
    missing_foundation = FIELD_FOUNDATION_TABLES - tables
    if missing_foundation:
        _fail(report, f"rollback removed Field Intelligence foundation tables: {sorted(missing_foundation)}")
    missing = PRESERVED_TABLES - tables
'''
if old not in text:
    raise SystemExit("verify-rollback block marker missing")
text = text.replace(old, new)
write(path, text)

# PostgreSQL roundtrip: current main 026 -> launch 027 -> 026 -> 027.
path = ".github/workflows/field-intelligence-ci.yml"
text = read(path)
pattern = re.compile(
    r"      - name: Upgrade current-main baseline.*?"
    r"(?=      - name: Re-upgrade to repository head)",
    re.S,
)
block = '''      - name: Upgrade current-main baseline (026_platform_api_operations)
        run: alembic upgrade 026_platform_api_operations
      - name: Upgrade current-main database to repository head (026 -> 027)
        run: alembic upgrade head
      - name: Downgrade only the Field Intelligence launch revision
        run: alembic downgrade 026_platform_api_operations
      - name: Prove launch tables are gone and foundation/current-main schemas survive
        run: |
          python - <<'PY'
          import os, sqlalchemy as sa
          engine = sa.create_engine(os.environ["DATABASE_URL"])
          inspector = sa.inspect(engine)
          tables = set(inspector.get_table_names())
          removed = {"field_runtime_flags", "field_worker_heartbeats"}
          leftover = removed & tables
          assert not leftover, f"downgrade left launch tables behind: {sorted(leftover)}"
          preserved = {
              "field_capture_sessions", "field_observations", "field_observation_assets",
              "field_observation_processing_runs", "field_observation_audit_events",
              "field_storage_reservations", "organization_verification_profiles",
              "security_audit_events", "account_access_appeals", "api_projects",
              "platform_api_keys", "platform_webhook_outbox", "platform_webhook_audit_events",
              "platform_api_applications", "platform_program_enrollments",
              "platform_live_access_requests", "platform_partner_dossiers",
              "platform_api_plans", "platform_api_operation_costs",
              "platform_api_subscriptions", "platform_credit_reservations",
              "platform_status_components", "platform_abuse_events",
          }
          missing = preserved - tables
          assert not missing, f"downgrade removed protected tables: {sorted(missing)}"
          print("launch tables removed:", sorted(removed))
          print("protected schemas preserved:", sorted(preserved))
          PY
'''
text, count = pattern.subn(block, text, count=1)
if count != 1:
    raise SystemExit("Field Intelligence CI migration block not found")
write(path, text)

# Preserve both authoritative topology sections.
path = "docs/DEPLOYMENT_TRUTH_MAP.md"
text = read(path).rstrip()
if "## K. Field Intelligence staging (isolated)" not in text:
    text += '''

## K. Field Intelligence staging (isolated)

Field Intelligence staging is an entirely separate topology deployed only by
`.github/workflows/field-intelligence-staging.yml` through the protected
`field-intelligence-staging` environment. It must never target
`app.agroai-pilot.com`, `api.agroai-pilot.com`, `api-preview.agroai-pilot.com`,
the production Render service, production database, production R2 bucket, or
production Pages project. The launch migration is
`027_field_intelligence_launch` after `026_platform_api_operations`; staging
rollback proof is `027 → 026 → 027`, preserving the Field Intelligence
foundation and every Platform API program, commerce, and operations table.
The release state remains `internal` until a separately approved canary action.
See `docs/field-intelligence-staging-runbook.md`.
'''
write(path, text)

path = "docs/platform-api-operations-runbook.md"
text = read(path)
text, count = re.subn(
    r"- The required linear Alembic tail is .*?; `alembic heads` must return only `.*?`\.",
    "- The required linear Alembic tail is `019_account_verification` → "
    "`020_platform_api_private_beta` → `021_platform_api_hardening` → "
    "`022_account_access_appeals` → `023_field_intelligence` → "
    "`024_platform_api_programs` → `025_platform_api_commerce` → "
    "`026_platform_api_operations` → `027_field_intelligence_launch`; "
    "`alembic heads` must return only `027_field_intelligence_launch`.",
    text,
    count=1,
)
if count != 1:
    raise SystemExit("Platform API migration-tail line not found")
write(path, text)

for old, new in {
    "024→022→024": "027→026→027",
    "024 -> 022 -> 024": "027 -> 026 -> 027",
    "024 → 022 → 024": "027 → 026 → 027",
    "024→022": "027→026",
    "022→024": "026→027",
    "022 -> 024": "026 -> 027",
}.items():
    replace_in_tracked(old, new)
