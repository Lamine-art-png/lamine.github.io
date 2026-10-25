#!/usr/bin/env bash
# Deploy AGRO-AI Academy to Cloudflare: staging or production, never both.
#   bash scripts/deploy.sh staging
#   ACADEMY_DEPLOY_CONFIRM=production bash scripts/deploy.sh production
#
# Required: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, and STREAM_API_TOKEN
# (Stream:Edit; every deploy protects and verifies the lesson videos, see
# scripts/stream.mjs).
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
    ENV_ARGS=(--env staging); BUCKET="${BACKUP_BUCKET:-agroai-academy-staging-backups}"; FILES_BUCKET="agroai-academy-staging-files" ;;
  production)
    DB_NAME="agroai-academy"; HOST="academy.agroai-pilot.com"; SERVICE="agroai-academy"
    ENV_ARGS=(); BUCKET="${BACKUP_BUCKET:-agroai-academy-backups}"; FILES_BUCKET="agroai-academy-files"
    if [ "${ACADEMY_DEPLOY_CONFIRM:-}" != "production" ]; then
      echo "Refusing to deploy production without ACADEMY_DEPLOY_CONFIRM=production." >&2
      exit 2
    fi ;;
  *) echo "unknown target $TARGET" >&2; exit 2 ;;
esac
test -n "${CLOUDFLARE_API_TOKEN:-}" || { echo "CLOUDFLARE_API_TOKEN is required" >&2; exit 1; }
test -n "${CLOUDFLARE_ACCOUNT_ID:-}" || { echo "CLOUDFLARE_ACCOUNT_ID is required" >&2; exit 1; }
# Video protection is verified on every deploy; without the Stream token a
# release could go out unverified, so nothing starts.
test -n "${STREAM_API_TOKEN:-}" || { echo "::error::STREAM_API_TOKEN is required: lesson video protection is verified on every deploy. Add a Cloudflare token limited to Stream:Edit as the GitHub secret ACADEMY_STREAM_API_TOKEN." >&2; exit 1; }

WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; rm -f wrangler.generated.toml; }
trap cleanup EXIT
CONFIG=(--config wrangler.generated.toml "${ENV_ARGS[@]}")
summary() { if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then printf '%s\n' "$*" >> "$GITHUB_STEP_SUMMARY"; fi; }
api() { curl -fsS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json" "${CF_API}$1"; }
# A failed query's JSON error (SQL or schema message, no row data) is shown instead of being swallowed by the parser.
d1() {
  local out
  if ! out="$($WRANGLER d1 execute "$DB_NAME" --remote "${CONFIG[@]}" --json --command "$1")"; then
    echo "::error::D1 query failed: $(printf '%s' "$out" | tr '\n' ' ' | head -c 800)" >&2
    return 1
  fi
  printf '%s' "$out"
}
# Run one query per input line and merge the rows (D1 rejects large compound SELECTs).
d1_each() {
  local i=0 q files=()
  while IFS= read -r q || [ -n "$q" ]; do
    [ -n "$q" ] || continue
    d1 "$q" > "$WORK/q-$i.json" || return 1
    files+=("$WORK/q-$i.json"); i=$((i + 1))
  done
  $H merge-d1 "${files[@]}" </dev/null
}

echo "==> Target ${TARGET}: Worker ${SERVICE}, database ${DB_NAME}, https://${HOST}"
summary "### Academy ${TARGET} deployment" "- Worker \`${SERVICE}\`, D1 \`${DB_NAME}\`, https://${HOST}"

echo "==> Checking DNS ownership of ${HOST}"
ZONE_ID="$(api "/zones?name=agroai-pilot.com" | $H zone-id)"
test -n "$ZONE_ID" || { echo "Zone agroai-pilot.com is not accessible with this token." >&2; exit 1; }
DNS_CODE="$(curl -sS -o "$WORK/dns.json" -w '%{http_code}' -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" "${CF_API}/zones/${ZONE_ID}/dns_records?name=${HOST}")" || DNS_CODE=000
if [ "$DNS_CODE" = "200" ]; then
  RECORDS="$($H result-count < "$WORK/dns.json")"
elif [ "$DNS_CODE" = "403" ]; then
  # Token without DNS read permission: check public DNS instead. (Cloudflare
  # also refuses to attach a Worker custom domain over an existing record.)
  RECORDS="$(node -e '
    const [base, host] = process.argv.slice(1);
    Promise.all(["A", "AAAA", "CNAME"].map((t) => fetch(`${base}?name=${host}&type=${t}`, { headers: { accept: "application/dns-json" } }).then((r) => r.json())))
      .then((rs) => { if (rs.some((r) => r.Status !== 0 && r.Status !== 3)) throw new Error("lookup failed"); console.log(rs.reduce((n, r) => n + (r.Answer || []).length, 0)); })
      .catch(() => console.log("error"));
  ' "${DOH_BASE:-https://cloudflare-dns.com/dns-query}" "$HOST")"
  [ "$RECORDS" != "error" ] || { echo "::error::Could not check DNS for ${HOST}; refusing to continue." >&2; exit 1; }
  echo "    Token cannot read DNS records; public DNS shows ${RECORDS} record(s)."
else
  echo "::error::Could not read DNS records for ${HOST} (HTTP ${DNS_CODE}); refusing to continue." >&2; exit 1
fi
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
TABLES_JSON="$(d1 "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name")" || { echo "::error::Could not read the database schema; refusing to continue." >&2; exit 1; }
if [ "$(printf '%s' "$TABLES_JSON" | $H has-row-name users)" = "yes" ]; then
  COUNTS_QUERIES="$(printf '%s' "$TABLES_JSON" | $H counts-queries)"
  CRITICAL_QUERIES="$(printf '%s' "$TABLES_JSON" | $H critical-queries)"
  # Critical records (learners, enrollments, attempts, certificates, reviews) are
  # fingerprinted before and after the export; every record unchanged across the
  # export window must be in the backup exactly (no tolerance).
  printf '%s\n' "$CRITICAL_QUERIES" | d1_each | $H critical-json > "$WORK/critical-before.json" || { echo "::error::Could not fingerprint critical records." >&2; exit 1; }
  printf '%s\n' "$COUNTS_QUERIES" | d1_each | $H counts-json > "$WORK/live-counts.json" || { echo "::error::Could not count live rows." >&2; exit 1; }
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
  printf '%s\n' "$CRITICAL_QUERIES" | d1_each | $H critical-json > "$WORK/critical-after.json" || { echo "::error::Could not fingerprint critical records after the export." >&2; exit 1; }
  echo "==> Verifying the export: completeness, integrity, restore and migration rehearsal"
  node "${HERE}/backup-verify.mjs" "$WORK/backup.sql" --expect "$WORK/live-counts.json" \
    --before "$WORK/critical-before.json" --after "$WORK/critical-after.json" --migrations migrations > "$WORK/verify.json" || {
    echo "::error::Backup verification failed: $(node -e 'const v=require(process.argv[1]);console.log(v.problems.join("; "))' "$WORK/verify.json")" >&2; exit 1; }
  node -e 'const v=require(process.argv[1]);for(const n of v.notes)console.log("    note: "+n);console.log("    Critical records verified exactly: "+Object.entries(v.critical).map(([t,c])=>t+"="+c.stable).join(", "));console.log("    Pending migrations rehearsed on the restored copy: "+(v.rehearsed.join(", ")||"none"))' "$WORK/verify.json"
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

echo "==> Ensuring private file bucket ${FILES_BUCKET}"
if [ "$($WRANGLER r2 bucket list 2>/dev/null | $H has-bucket "$FILES_BUCKET")" != "yes" ]; then
  $WRANGLER r2 bucket create "$FILES_BUCKET" >/dev/null || { echo "::error::Could not create file bucket ${FILES_BUCKET}." >&2; exit 1; }
  echo "    Created ${FILES_BUCKET}."
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
echo "==> Protecting lesson videos in Cloudflare Stream"
# Every deploy re-asserts and re-verifies protection of the lesson videos and
# records the evidence the publication gate reads. It is mandatory: the
# token is checked before anything changes (top of this script) and any
# failure here fails the deployment.
mkdir -p "$WORK/stream"
if [ "$(printf '%s' "$EXISTING" | $H has-secret STREAM_SIGNING_KEY_ID)" != "yes" ]; then
  node "$HERE/stream.mjs" create-key --out "$WORK/stream"
  $WRANGLER secret put STREAM_SIGNING_KEY_ID "${CONFIG[@]}" < "$WORK/stream/key-id" >/dev/null
  $WRANGLER secret put STREAM_SIGNING_JWK "${CONFIG[@]}" < "$WORK/stream/key-jwk" >/dev/null
  rm -f "$WORK/stream/key-id" "$WORK/stream/key-jwk"
  echo "    Created a Stream signing key for ${SERVICE} (Worker secrets only)."
fi
d1 "SELECT video_id, locale, status, CASE WHEN status = 'reviewed' THEN vtt END AS vtt FROM video_captions" | $H rows > "$WORK/stream/captions.json"
STREAM_OK=0
node "$HERE/stream.mjs" protect --out "$WORK/stream" --captions "$WORK/stream/captions.json" || STREAM_OK=$?
# Evidence is recorded even when a check fails, so the gate sees the failure.
for F in evidence mapping captions; do
  if [ -s "$WORK/stream/$F.sql" ]; then
    $WRANGLER d1 execute "$DB_NAME" --remote "${CONFIG[@]}" --file "$WORK/stream/$F.sql" >/dev/null
    echo "    Applied $F ($(grep -c . "$WORK/stream/$F.sql") statement(s))."
  fi
done
CODE="$(cat "$WORK/stream/customer-code" 2>/dev/null || true)"
if [ -n "$CODE" ] && [ "$(printf '%s' "$EXISTING" | $H has-secret STREAM_CUSTOMER_CODE)" != "yes" ]; then
  printf '%s' "$CODE" | $WRANGLER secret put STREAM_CUSTOMER_CODE "${CONFIG[@]}" >/dev/null
  echo "    Set STREAM_CUSTOMER_CODE."
fi
if [ "$STREAM_OK" != "0" ]; then
  echo "::error::One or more lesson videos are not verifiably protected in Cloudflare Stream (see the job summary)." >&2
  exit 1
fi

echo "==> ${TARGET} deployed to https://${HOST}"
summary "- Deployed to https://${HOST}"
