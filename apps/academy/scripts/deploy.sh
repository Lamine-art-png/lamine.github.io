#!/usr/bin/env bash
# Deploy AGRO-AI Academy to Cloudflare: staging or production, never both.
#   bash scripts/deploy.sh staging
#   ACADEMY_DEPLOY_CONFIRM=production bash scripts/deploy.sh production
#
# Required: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID.
# Optional secrets (read from the environment, never printed):
#   BOOTSTRAP_ADMIN_EMAILS, RESEND_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
#   CERT_SIGNING_SECRET (used only if the Worker has none yet),
#   BACKUP_PASSPHRASE (encrypts backups with GPG AES-256 before upload).
#
# Safety:
# * Staging and production use different Workers, D1 databases, hostnames,
#   backup buckets and secrets. Production needs ACADEMY_DEPLOY_CONFIRM=production.
# * Refuses to deploy if the hostname has a DNS record that is not this Worker.
#   It never edits or deletes DNS records.
# * Before any migration, an existing database is exported, the export is
#   restored into a scratch SQLite database and checked, then stored in a
#   private R2 bucket and read back to confirm the stored copy. Any failure
#   stops the deployment before the schema or code changes.
# * Never replaces an existing CERT_SIGNING_SECRET, and refuses to create one
#   when certificates already exist (a new key would invalidate them).
set -euo pipefail
set +x

TARGET="${1:?usage: deploy.sh staging|production}"
WRANGLER="${ACADEMY_WRANGLER:-npx --yes wrangler@4.107.0}"
CF_API="${CF_API_BASE:-https://api.cloudflare.com/client/v4}"
HERE="$(cd "$(dirname "$0")" && pwd)"
H="node ${HERE}/deploy-helpers.mjs"

case "$TARGET" in
  staging)
    DB_NAME="agroai-academy-staging"; HOST="academy-staging.agroai-pilot.com"; SERVICE="agroai-academy-staging"
    ENV_ARGS=(--env staging); BUCKET="${BACKUP_BUCKET:-agroai-academy-staging-backups}" ;;
  production)
    DB_NAME="agroai-academy"; HOST="academy.agroai-pilot.com"; SERVICE="agroai-academy"
    ENV_ARGS=(); BUCKET="${BACKUP_BUCKET:-agroai-academy-backups}"
    if [ "${ACADEMY_DEPLOY_CONFIRM:-}" != "production" ]; then
      echo "Refusing to deploy production without ACADEMY_DEPLOY_CONFIRM=production." >&2
      exit 2
    fi ;;
  *) echo "unknown target $TARGET" >&2; exit 2 ;;
esac
test -n "${CLOUDFLARE_API_TOKEN:-}" || { echo "CLOUDFLARE_API_TOKEN is required" >&2; exit 1; }
test -n "${CLOUDFLARE_ACCOUNT_ID:-}" || { echo "CLOUDFLARE_ACCOUNT_ID is required" >&2; exit 1; }

WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; rm -f wrangler.generated.toml; }
trap cleanup EXIT
CONFIG=(--config wrangler.generated.toml "${ENV_ARGS[@]}")
summary() { if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then printf '%s\n' "$*" >> "$GITHUB_STEP_SUMMARY"; fi; }
api() { curl -fsS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json" "${CF_API}$1"; }
d1() { $WRANGLER d1 execute "$DB_NAME" --remote "${CONFIG[@]}" --json --command "$1"; }

echo "==> Target ${TARGET}: Worker ${SERVICE}, database ${DB_NAME}, https://${HOST}"
summary "### Academy ${TARGET} deployment" "- Worker \`${SERVICE}\`, D1 \`${DB_NAME}\`, https://${HOST}"

echo "==> Checking DNS ownership of ${HOST}"
ZONE_ID="$(api "/zones?name=agroai-pilot.com" | $H zone-id)"
test -n "$ZONE_ID" || { echo "Zone agroai-pilot.com is not accessible with this token." >&2; exit 1; }
RECORDS="$(api "/zones/${ZONE_ID}/dns_records?name=${HOST}" | $H result-count)"
if [ "$RECORDS" != "0" ]; then
  OWNED="$(api "/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/domains?hostname=${HOST}" | $H domain-owned "$SERVICE")"
  if [ "$OWNED" != "yes" ]; then
    echo "::error::${HOST} already has a DNS record that is not this Worker's custom domain. Refusing to change it; ask the founder to confirm the hostname." >&2
    exit 1
  fi
  echo "    ${HOST} is already attached to ${SERVICE}."
else
  echo "    No existing record; the Worker custom domain will create it."
fi

echo "==> Ensuring D1 database ${DB_NAME}"
DB_ID="$($WRANGLER d1 list --json 2>/dev/null | $H d1-id "$DB_NAME")"
if [ -z "$DB_ID" ]; then
  $WRANGLER d1 create "$DB_NAME" >/dev/null
  DB_ID="$($WRANGLER d1 list --json 2>/dev/null | $H d1-id "$DB_NAME")"
  echo "    Created ${DB_NAME}."
fi
test -n "$DB_ID" || { echo "Could not resolve D1 database id" >&2; exit 1; }
# Only this target's database_id is filled in; the other environment keeps its placeholder.
$H set-db-id "$DB_NAME" "$DB_ID" < wrangler.toml > wrangler.generated.toml

echo "==> Backing up ${DB_NAME} before migrations"
TABLES_JSON="$(d1 "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")" || { echo "::error::Could not read the database schema; refusing to continue." >&2; exit 1; }
if [ "$(printf '%s' "$TABLES_JSON" | $H has-row-name users)" = "yes" ]; then
  COUNTS_SQL="$(printf '%s' "$TABLES_JSON" | $H counts-sql)"
  d1 "$COUNTS_SQL" | $H counts-json > "$WORK/live-counts.json" || { echo "::error::Could not count live rows." >&2; exit 1; }
  echo "    Live rows: $(cat "$WORK/live-counts.json")"
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  KEY="d1/${DB_NAME}/${STAMP}-${GITHUB_SHA:-manual}.sql.gz"

  # Point-in-time restore marker (D1 Time Travel), recorded as a second recovery path.
  if BOOKMARK="$($WRANGLER d1 time-travel info "$DB_NAME" "${CONFIG[@]}" --json 2>/dev/null | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{const j=JSON.parse(s.slice(s.search(/[[{]/)));process.stdout.write(String(j.bookmark||""))}catch{}})')" && [ -n "$BOOKMARK" ]; then
    echo "    Time Travel bookmark: ${BOOKMARK}"
    summary "- Time Travel bookmark before migration: \`${BOOKMARK}\`"
  else
    echo "::warning::Could not read a D1 Time Travel bookmark; relying on the verified export."
  fi

  $WRANGLER d1 export "$DB_NAME" --remote "${CONFIG[@]}" --output "$WORK/backup.sql" >/dev/null || { echo "::error::Database export failed; refusing to migrate." >&2; exit 1; }
  test -s "$WORK/backup.sql" || { echo "::error::Database export is empty; refusing to migrate." >&2; exit 1; }
  echo "==> Verifying the export restores cleanly"
  node "${HERE}/backup-verify.mjs" "$WORK/backup.sql" --expect "$WORK/live-counts.json" > "$WORK/verify.json" || {
    echo "::error::Backup verification failed: $(cat "$WORK/verify.json")" >&2; exit 1; }
  echo "    Restore check passed."

  gzip -9 -n -c "$WORK/backup.sql" > "$WORK/backup.sql.gz"
  if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
    gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 --symmetric --cipher-algo AES256 \
      -o "$WORK/upload" "$WORK/backup.sql.gz" 3<<<"$BACKUP_PASSPHRASE"
    KEY="${KEY}.gpg"; ENCRYPTED="GPG AES-256"
  else
    cp "$WORK/backup.sql.gz" "$WORK/upload"; ENCRYPTED="no (private bucket, encrypted at rest by R2)"
    echo "::warning::BACKUP_PASSPHRASE is not set; the backup is stored unencrypted in the private bucket."
  fi
  SUM="$(sha256sum "$WORK/upload" | cut -d' ' -f1)"

  echo "==> Storing backup in private R2 bucket ${BUCKET}"
  if [ "$($WRANGLER r2 bucket list 2>/dev/null | $H has-bucket "$BUCKET")" != "yes" ]; then
    $WRANGLER r2 bucket create "$BUCKET" >/dev/null || { echo "::error::Could not create backup bucket ${BUCKET}." >&2; exit 1; }
  fi
  $WRANGLER r2 object put "${BUCKET}/${KEY}" --file "$WORK/upload" --content-type application/octet-stream --remote >/dev/null || {
    echo "::error::Backup upload failed; refusing to migrate." >&2; exit 1; }
  $WRANGLER r2 object get "${BUCKET}/${KEY}" --file "$WORK/roundtrip" --remote >/dev/null || {
    echo "::error::Could not read the stored backup back; refusing to migrate." >&2; exit 1; }
  [ "$(sha256sum "$WORK/roundtrip" | cut -d' ' -f1)" = "$SUM" ] || { echo "::error::Stored backup does not match (checksum); refusing to migrate." >&2; exit 1; }
  echo "    Stored ${BUCKET}/${KEY} (sha256 ${SUM}) and read it back intact."
  summary "- Backup: \`r2://${BUCKET}/${KEY}\`" "- SHA-256: \`${SUM}\` · encrypted: ${ENCRYPTED}" "- Restore check: $(node -e 'const v=require(process.argv[1]);console.log(Object.entries(v.tables).filter(([t])=>["users","enrollments","attempts","certificates"].includes(t)).map(([t,n])=>t+"="+n).join(", "))' "$WORK/verify.json")"
else
  echo "    New or empty database: nothing to back up."
  summary "- Backup: not needed (new or empty database)"
fi

echo "==> Applying migrations to ${DB_NAME}"
$WRANGLER d1 migrations apply "$DB_NAME" --remote "${CONFIG[@]}"

echo "==> Deploying Worker ${SERVICE}"
$WRANGLER deploy "${CONFIG[@]}"

echo "==> Configuring secrets"
EXISTING="$($WRANGLER secret list --format json "${CONFIG[@]}")" || { echo "::error::Could not list Worker secrets; refusing to change them." >&2; exit 1; }
if [ "$(printf '%s' "$EXISTING" | $H has-secret CERT_SIGNING_SECRET)" != "yes" ]; then
  CERTS="$(d1 "SELECT COUNT(*) AS n FROM certificates" | $H scalar n)"
  if [ "${CERTS:-0}" != "0" ]; then
    echo "::error::${CERTS} certificate(s) exist but the Worker has no CERT_SIGNING_SECRET. Restore the original key; a new key would invalidate every issued credential." >&2
    exit 1
  fi
  if [ -n "${CERT_SIGNING_SECRET:-}" ]; then
    [ "${#CERT_SIGNING_SECRET}" -ge 32 ] || { echo "::error::CERT_SIGNING_SECRET must be at least 32 characters." >&2; exit 1; }
    printf '%s' "$CERT_SIGNING_SECRET" | $WRANGLER secret put CERT_SIGNING_SECRET "${CONFIG[@]}" >/dev/null
    echo "    Set CERT_SIGNING_SECRET from the provided value."
  else
    printf '%s' "$(openssl rand -hex 32)" | $WRANGLER secret put CERT_SIGNING_SECRET "${CONFIG[@]}" >/dev/null
    echo "    Generated CERT_SIGNING_SECRET (stored only in Cloudflare)."
    echo "::warning::A new certificate signing key was generated inside Cloudflare and cannot be read back. Provide CERT_SIGNING_SECRET from a password manager if you need an escrowed copy."
  fi
else
  echo "    CERT_SIGNING_SECRET already present; left unchanged."
fi
for NAME in BOOTSTRAP_ADMIN_EMAILS RESEND_API_KEY GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET; do
  if [ -n "${!NAME:-}" ]; then
    printf '%s' "${!NAME}" | $WRANGLER secret put "$NAME" "${CONFIG[@]}" >/dev/null
    echo "    Updated ${NAME}."
  fi
done
# Staging only: token for the automated staging test inbox (ignored by the app elsewhere).
if [ "$TARGET" = "staging" ] && [ -n "${STAGING_TEST_INBOX_TOKEN:-}" ]; then
  printf '%s' "$STAGING_TEST_INBOX_TOKEN" | $WRANGLER secret put STAGING_TEST_TOKEN "${CONFIG[@]}" >/dev/null
  echo "    Updated STAGING_TEST_TOKEN."
fi
echo "==> ${TARGET} deployed to https://${HOST}"
summary "- Deployed to https://${HOST}"
