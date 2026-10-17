#!/usr/bin/env bash
# Deploy AGRO-AI Academy to Cloudflare (staging or production).
#   CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID must be set.
# Optional secrets (read from the environment, never printed):
#   BOOTSTRAP_ADMIN_EMAILS, RESEND_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
# Safety: refuses to deploy if the target hostname already has a DNS record
# that does not belong to this Worker. It never edits or deletes DNS records.
set -euo pipefail
set +x

TARGET="${1:?usage: deploy.sh staging|production}"
WRANGLER="npx --yes wrangler@4.107.0"
case "$TARGET" in
  staging)    DB_NAME="agroai-academy-staging"; HOST="academy-staging.agroai-pilot.com"; SERVICE="agroai-academy-staging"; ENV_ARGS=(--env staging) ;;
  production) DB_NAME="agroai-academy";         HOST="academy.agroai-pilot.com";         SERVICE="agroai-academy";         ENV_ARGS=() ;;
  *) echo "unknown target $TARGET" >&2; exit 2 ;;
esac
test -n "${CLOUDFLARE_API_TOKEN:-}" || { echo "CLOUDFLARE_API_TOKEN is required" >&2; exit 1; }
test -n "${CLOUDFLARE_ACCOUNT_ID:-}" || { echo "CLOUDFLARE_ACCOUNT_ID is required" >&2; exit 1; }

api() { curl -fsS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json" "https://api.cloudflare.com/client/v4$1"; }

echo "==> Checking DNS ownership of ${HOST}"
ZONE_ID="$(api "/zones?name=agroai-pilot.com" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const r=JSON.parse(s);process.stdout.write(r.result?.[0]?.id||"")})')"
test -n "$ZONE_ID" || { echo "Zone agroai-pilot.com is not accessible with this token." >&2; exit 1; }
RECORDS="$(api "/zones/${ZONE_ID}/dns_records?name=${HOST}" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const r=JSON.parse(s);process.stdout.write(String(r.result?.length||0))})')"
if [ "$RECORDS" != "0" ]; then
  OWNED="$(api "/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/domains?hostname=${HOST}" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const r=JSON.parse(s);process.stdout.write((r.result||[]).some(x=>x.service===process.argv[1])?"yes":"no")})' "$SERVICE")"
  if [ "$OWNED" != "yes" ]; then
    echo "::error::${HOST} already has a DNS record that is not this Worker's custom domain. Refusing to change it; ask the founder to confirm the hostname." >&2
    exit 1
  fi
  echo "    ${HOST} is already attached to ${SERVICE}."
else
  echo "    No existing record; the Worker custom domain will create it."
fi

echo "==> Ensuring D1 database ${DB_NAME}"
DB_ID="$($WRANGLER d1 list --json 2>/dev/null | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const l=JSON.parse(s.slice(s.indexOf("[")));const m=l.find(x=>x.name===process.argv[1]);process.stdout.write(m?.uuid||"")})' "$DB_NAME")"
if [ -z "$DB_ID" ]; then
  $WRANGLER d1 create "$DB_NAME" >/dev/null
  DB_ID="$($WRANGLER d1 list --json 2>/dev/null | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const l=JSON.parse(s.slice(s.indexOf("[")));const m=l.find(x=>x.name===process.argv[1]);process.stdout.write(m?.uuid||"")})' "$DB_NAME")"
fi
test -n "$DB_ID" || { echo "Could not resolve D1 database id" >&2; exit 1; }
sed "s/00000000-0000-0000-0000-000000000000/${DB_ID}/g" wrangler.toml > wrangler.generated.toml

echo "==> Backing up and migrating ${DB_NAME}"
if [ "$TARGET" = "production" ]; then
  $WRANGLER d1 export "$DB_NAME" --remote --output "/tmp/${DB_NAME}-$(date +%Y%m%d%H%M%S).sql" --config wrangler.generated.toml >/dev/null 2>&1 || echo "    (no existing data to back up)"
fi
$WRANGLER d1 migrations apply "$DB_NAME" --remote --config wrangler.generated.toml "${ENV_ARGS[@]}"

echo "==> Deploying Worker ${SERVICE}"
$WRANGLER deploy --config wrangler.generated.toml "${ENV_ARGS[@]}"

echo "==> Configuring secrets"
EXISTING="$($WRANGLER secret list --config wrangler.generated.toml "${ENV_ARGS[@]}" 2>/dev/null || echo "[]")"
if ! printf '%s' "$EXISTING" | grep -q '"CERT_SIGNING_SECRET"'; then
  openssl rand -hex 32 | $WRANGLER secret put CERT_SIGNING_SECRET --config wrangler.generated.toml "${ENV_ARGS[@]}" >/dev/null
  echo "    Generated CERT_SIGNING_SECRET (stored only in Cloudflare)."
fi
for NAME in BOOTSTRAP_ADMIN_EMAILS RESEND_API_KEY GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET; do
  if [ -n "${!NAME:-}" ]; then
    printf '%s' "${!NAME}" | $WRANGLER secret put "$NAME" --config wrangler.generated.toml "${ENV_ARGS[@]}" >/dev/null
    echo "    Updated ${NAME}."
  fi
done
rm -f wrangler.generated.toml
echo "==> ${TARGET} deployed to https://${HOST}"
