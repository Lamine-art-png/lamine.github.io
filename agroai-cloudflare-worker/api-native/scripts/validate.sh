#!/usr/bin/env bash
#
# Talgil Integration Validation Script
#
# Usage:
#   export BASE_URL="https://agroai-api-staging.your-worker.workers.dev"
#   export ADMIN_TOKEN="your_admin_token"
#   export TENANT_ID="demo_clean_01"
#   bash scripts/validate.sh
#
# This script runs the complete validation sequence and captures
# evidence for every step.

set -euo pipefail

: "${BASE_URL:?Set BASE_URL}"
: "${ADMIN_TOKEN:?Set ADMIN_TOKEN}"
: "${TENANT_ID:?Set TENANT_ID}"

PROOF_DIR="./talgil-proof-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$PROOF_DIR"

HEADERS="-H 'Authorization: Bearer $ADMIN_TOKEN' -H 'x-admin-token: $ADMIN_TOKEN'"

echo "=== Talgil Integration Validation ==="
echo "Base URL:  $BASE_URL"
echo "Tenant:    $TENANT_ID"
echo "Proof dir: $PROOF_DIR"
echo ""

# ── Step 1: Connect ──────────────────────────────────────
echo "[1/8] Connecting tenant $TENANT_ID..."
curl -s \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  -X POST \
  "$BASE_URL/v1/integrations/talgil/connect?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/01_connect.json"
echo ""

# ── Step 2: Status after connect ─────────────────────────
echo "[2/8] Checking status after connect..."
curl -s \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  "$BASE_URL/v1/integrations/talgil/status?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/02_status_after_connect.json"
echo ""

# ── Step 3: Operational sync ─────────────────────────────
echo "[3/8] Running operational sync..."
curl -s \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  -X POST \
  "$BASE_URL/v1/integrations/talgil/sync?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/03_sync.json"
echo ""

# ── Step 4: Historical backfill ──────────────────────────
echo "[4/8] Running historical backfill (simulator range, this may take several minutes)..."
curl -s --max-time 600 \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  -X POST \
  "$BASE_URL/v1/integrations/talgil/backfill?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/04_backfill.json"
echo ""

# ── Step 5: Status after backfill ────────────────────────
echo "[5/8] Checking status after backfill..."
curl -s \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  "$BASE_URL/v1/integrations/talgil/status?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/05_status_after_backfill.json"
echo ""

# ── Step 6: Test event log permissions ───────────────────
echo "[6/8] Testing event log endpoint permissions..."
curl -s \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  -X POST \
  "$BASE_URL/v1/integrations/talgil/test/eventlog?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/06_test_eventlog.json"
echo ""

# ── Step 7: Test water consumption permissions ───────────
echo "[7/8] Testing water consumption endpoint permissions..."
curl -s \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  -X POST \
  "$BASE_URL/v1/integrations/talgil/test/wc?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/07_test_wc.json"
echo ""

# ── Step 8: Sensors latest with metadata ─────────────────
echo "[8/8] Fetching latest sensors with catalog metadata..."
curl -s \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  "$BASE_URL/v1/integrations/talgil/sensors/latest?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/08_sensors_latest.json"
echo ""

# ── Audit log ────────────────────────────────────────────
echo "[Bonus] Fetching audit log..."
curl -s \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "x-admin-token: $ADMIN_TOKEN" \
  "$BASE_URL/v1/integrations/talgil/audit?tenantId=$TENANT_ID" \
  | python3 -m json.tool | tee "$PROOF_DIR/09_audit_log.json"
echo ""

echo "=== Validation complete ==="
echo "All evidence saved to: $PROOF_DIR/"
echo ""
echo "Review checklist:"
echo "  [ ] 01_connect.json: controller_id = 6115, sensor_catalog_count > 0"
echo "  [ ] 02_status: status = connected, sensorCatalogRows > 0"
echo "  [ ] 03_sync.json: catalog_upserted > 0, snapshot_stored > 0"
echo "  [ ] 04_backfill.json: total_rows_stored > 0, no errors in chunks"
echo "  [ ] 05_status: sensorRows significantly > 0"
echo "  [ ] 06_test_eventlog.json: check http_status (200 or 403)"
echo "  [ ] 07_test_wc.json: check http_status (200 or 403)"
echo "  [ ] 08_sensors_latest.json: sensor_name populated (not null)"
