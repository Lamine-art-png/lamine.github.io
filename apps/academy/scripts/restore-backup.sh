#!/usr/bin/env bash
# Restore a verified Academy backup into a NEW D1 database. Never writes to the
# live database: switching the Worker to the restored copy is a separate,
# deliberate change of database_id in wrangler.toml followed by a deploy.
#   bash scripts/restore-backup.sh <bucket>/<key> <new-database-name> [expected-sha256]
# Encrypted (.gpg) backups need BACKUP_PASSPHRASE.
set -euo pipefail
set +x
SRC="${1:?usage: restore-backup.sh <bucket>/<key> <new-database-name> [expected-sha256]}"
NEW_DB="${2:?new database name required}"
EXPECT_SUM="${3:-}"
WRANGLER="${ACADEMY_WRANGLER:-npx --yes wrangler@4.107.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
case "$NEW_DB" in
  agroai-academy|agroai-academy-staging) echo "Refusing to restore over a live database (${NEW_DB}). Choose a new name." >&2; exit 2 ;;
esac
if $WRANGLER d1 list --json 2>/dev/null | node "${HERE}/deploy-helpers.mjs" d1-id "$NEW_DB" | grep -q .; then
  echo "Database ${NEW_DB} already exists; restore only into a new database." >&2; exit 2
fi
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

echo "==> Downloading ${SRC}"
$WRANGLER r2 object get "$SRC" --file "$WORK/object" --remote >/dev/null
SUM="$(sha256sum "$WORK/object" | cut -d' ' -f1)"
echo "    sha256 ${SUM}"
if [ -n "$EXPECT_SUM" ] && [ "$SUM" != "$EXPECT_SUM" ]; then echo "Checksum mismatch; expected ${EXPECT_SUM}." >&2; exit 1; fi
if [[ "$SRC" == *.gpg ]]; then
  test -n "${BACKUP_PASSPHRASE:-}" || { echo "BACKUP_PASSPHRASE is required for encrypted backups." >&2; exit 1; }
  gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 -o "$WORK/backup.sql.gz" -d "$WORK/object" 3<<<"$BACKUP_PASSPHRASE"
else
  mv "$WORK/object" "$WORK/backup.sql.gz"
fi
gunzip -c "$WORK/backup.sql.gz" > "$WORK/backup.sql"

echo "==> Verifying the backup restores cleanly"
H="node ${HERE}/deploy-helpers.mjs"
node "${HERE}/backup-verify.mjs" "$WORK/backup.sql" --fingerprints "$WORK/dump-critical.json" > "$WORK/verify.json" || {
  echo "Backup verification failed: $(node -e 'console.log(require(process.argv[1]).problems.join("; "))' "$WORK/verify.json")" >&2; exit 1; }
node -e 'const v=require(process.argv[1]);process.stdout.write(JSON.stringify(Object.fromEntries(Object.entries(v.tables).filter(([t])=>t!=="d1_migrations"))))' "$WORK/verify.json" > "$WORK/dump-counts.json"

echo "==> Importing into new database ${NEW_DB}"
$WRANGLER d1 create "$NEW_DB" >/dev/null
$WRANGLER d1 execute "$NEW_DB" --remote --file "$WORK/backup.sql" --yes >/dev/null

echo "==> Checking the restored database matches the backup exactly"
q() { $WRANGLER d1 execute "$NEW_DB" --remote --json --command "$1"; }
# One query per line, rows merged (D1 rejects large compound SELECTs).
q_each() {
  local i=0 line files=()
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    q "$line" > "$WORK/q-$i.json"; files+=("$WORK/q-$i.json"); i=$((i + 1))
  done
  $H merge-d1 "${files[@]}" </dev/null
}
TABLES="$(q "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name <> 'd1_migrations' ORDER BY name")"
printf '%s' "$TABLES" | $H counts-queries | q_each | $H counts-json > "$WORK/restored-counts.json"
$H same-json "$WORK/dump-counts.json" < "$WORK/restored-counts.json" >/dev/null || {
  echo "Restored row counts differ from the backup; do not use ${NEW_DB}: $(node -e 'const [a,b]=process.argv.slice(1).map(f=>require(f));console.log(Object.keys({...a,...b}).filter(k=>a[k]!==b[k]).map(k=>`${k} backup=${b[k]} restored=${a[k]}`).join(", "))' "$WORK/restored-counts.json" "$WORK/dump-counts.json")" >&2; exit 1; }
printf '%s' "$TABLES" | $H critical-queries | q_each | $H critical-json | $H same-json "$WORK/dump-critical.json" >/dev/null || {
  echo "Restored learner, exam or certificate records differ from the backup; do not use ${NEW_DB}." >&2; exit 1; }
echo "    Every table's row count and every critical record match the backup."
echo "==> Restored into ${NEW_DB}. The live database was not modified."
echo "    To switch the Worker, set its database_id in wrangler.toml and deploy after review."
