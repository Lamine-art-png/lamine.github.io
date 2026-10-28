#!/usr/bin/env bash
# Post-deploy smoke test for a live Academy URL. Read-only: creates no data.
#   bash scripts/smoke.sh https://academy-staging.agroai-pilot.com
set -euo pipefail
BASE="${1:?usage: smoke.sh <base-url>}"
fail() { echo "::error::$*" >&2; exit 1; }

echo "==> Waiting for ${BASE}/healthz"
for i in $(seq 1 36); do
  code="$(curl -sS -o health.json -w '%{http_code}' --max-time 15 "${BASE}/healthz" || true)"
  [ "$code" = "200" ] && break
  sleep 5
done
[ "${code:-}" = "200" ] || fail "health check returned ${code:-none}"
node -e '
const h = require("./health.json");
const problems = [];
if (h.ok !== true) problems.push("ok=false");
if (h.database !== "ok") problems.push("database not ok");
if (h.certificate_signing !== "configured") problems.push("certificate signing not configured");
if (!(h.languages >= 60)) problems.push("language inventory missing");
console.log(JSON.stringify(h));
if (problems.length) { console.error(problems.join(", ")); process.exit(1); }'

check() {
  local path="$1" expect="$2" needle="${3:-}"
  local code
  code="$(curl -sS -D headers.txt -o body.html -w '%{http_code}' --max-time 20 "${BASE}${path}")"
  [ "$code" = "$expect" ] || fail "${path} returned ${code}, expected ${expect}"
  if [ -n "$needle" ]; then grep -Fq "$needle" body.html || fail "${path} is missing: ${needle}"; fi
  echo "    ${path} → ${code}"
}
check / 200 "AGRO-AI Academy"
check /courses 200 "Course catalog"
check /courses/introduction-to-ai-in-agriculture 200 "Introduction to Artificial Intelligence in Agriculture"
check /verify 200 "Verify a certificate"
check /verify/AGA-0000-0000-0000 404 "Credential not found"
check /register 200 "Create your account"
check /sitemap.xml 200 "<urlset"
check "/?lang=ar" 200 'dir="rtl"'
check "/?lang=fa" 200 '<html lang="fa" dir="rtl"'
check /static/css/academy.css?v=smoke 200
check /static/brand/academy-lockup-h.webp 200
check /static/brand/og-academy.png 200
check /apple-touch-icon.png 200
check /dashboard 303
grep -qi '^content-security-policy:' headers.txt || true
curl -sS -D h.txt -o /dev/null "${BASE}/" && grep -qi '^content-security-policy:' h.txt || fail "CSP header missing"
grep -qi '^strict-transport-security:' h.txt || fail "HSTS header missing"
echo "==> Smoke test passed for ${BASE}"
