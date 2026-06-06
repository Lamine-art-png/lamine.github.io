#!/usr/bin/env python3
"""
AGRO-AI FCGMA Runtime Verification Script
Verifies all API routes, response schemas, and the operational loop.
Exits non-zero on any failure.

Usage:
    python3 scripts/verify_fcgma_runtime.py [--base http://127.0.0.1:8000]
"""

import sys
import json
import argparse
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000/v1/fcgma-demo"
PASS = 0
FAIL = 0

def ok(msg): global PASS; PASS += 1; print(f"  ✓  {msg}")
def fail(msg): global FAIL; FAIL += 1; print(f"  ✗  {msg}", file=sys.stderr)


def get(path) -> dict:
    url = BASE + path
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def post(path, body=None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def patch(path, body) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"}, method="PATCH")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def check(label, value, expected=None, contains=None):
    if expected is not None and value != expected:
        fail(f"{label}: expected {expected!r}, got {value!r}")
    elif contains is not None and contains not in str(value):
        fail(f"{label}: expected to contain {contains!r}, got {value!r}")
    else:
        ok(label)


def head_ok(path):
    try:
        url = BASE + path
        req = urllib.request.Request(url, method="HEAD")
        urllib.request.urlopen(req, timeout=10)
        ok(f"HEAD {path}")
    except urllib.error.HTTPError as e:
        fail(f"HEAD {path}: HTTP {e.code}")


print("\n━━━  AGRO-AI FCGMA Runtime Verification  ━━━\n")

# ── Status ─────────────────────────────────────────────────────
print("[ Status ]")
try:
    s = get("/status")
    check("environment is illustrative_workspace", s.get("environment"), "illustrative_workspace")
    check("product name updated", s.get("product"), contains="Applied Water Intelligence")
    check("ledger_stats present", "ledger_stats" in s, True)
    check("total_records > 0", s.get("ledger_stats", {}).get("total_records", 0) > 0, True)
except Exception as e:
    fail(f"Status endpoint: {e}")

# ── Dashboard ──────────────────────────────────────────────────
print("\n[ Dashboard ]")
try:
    d = get("/dashboard")
    check("stats key present", "stats" in d, True)
    check("total_records > 0", d["stats"].get("total_records", 0) > 0, True)
    check("provisional_af present", d["stats"].get("provisional_af") is not None, True)
    check("open_exceptions present", d["stats"].get("open_exceptions") is not None, True)
except Exception as e:
    fail(f"Dashboard endpoint: {e}")

# ── Review Queue ───────────────────────────────────────────────
print("\n[ Review Queue ]")
record_id = None
try:
    q = get("/review-queue")
    check("records list present", "records" in q, True)
    check("records count > 0", len(q.get("records", [])) > 0, True)
    record_id = q["records"][0]["id"]
    check("record_id present", record_id is not None, True)
except Exception as e:
    fail(f"Review queue: {e}")

# ── Record Detail ──────────────────────────────────────────────
print("\n[ Record Detail ]")
if record_id:
    try:
        ledger = get(f"/records/{record_id}/ledger")
        check("record.id present", ledger.get("record", {}).get("id") == record_id, True)
        check("calculation_explanation present", "calculation_explanation" in ledger, True)
        check("disclaimer present", "disclaimer" in ledger, True)
    except Exception as e:
        fail(f"Record ledger: {e}")

    try:
        audit = get(f"/records/{record_id}/audit")
        check("audit_events present", "audit_events" in audit, True)
        check("exceptions present", "exceptions" in audit, True)
    except Exception as e:
        fail(f"Record audit: {e}")

# ── Source Health ──────────────────────────────────────────────
print("\n[ Source Health ]")
try:
    h = get("/source-health")
    check("provider_health.providers present", len(h.get("provider_health", {}).get("providers", [])) > 0, True)
    check("rule_pack present", "rule_pack" in h, True)
    ranch = next((p for p in h["provider_health"]["providers"] if "ranch" in p.get("provider_id", "").lower()), None)
    if ranch:
        check("ranch_systems disabled", ranch.get("status"), "disabled")
except Exception as e:
    fail(f"Source health: {e}")

# ── Rules ──────────────────────────────────────────────────────
print("\n[ Rules ]")
try:
    r = get("/rules")
    check("rules list present", len(r.get("rules", [])) > 0, True)
    check("metadata present", "metadata" in r, True)
except Exception as e:
    fail(f"Rules: {e}")

# ── Terris Reporting Cycle ─────────────────────────────────────
print("\n[ Terris: Reporting Cycle ]")
try:
    c = get("/terris/reporting-cycle")
    check("readiness_percentage present", c.get("readiness_percentage") is not None, True)
    check("cycle_status present", c.get("cycle_status") is not None, True)
    check("blocking_exceptions present", c.get("blocking_exceptions") is not None, True)
    check("total_records > 0", c.get("total_records", 0) > 0, True)
except Exception as e:
    fail(f"Terris reporting cycle: {e}")

# ── Terris Priority Actions ────────────────────────────────────
print("\n[ Terris: Priority Actions ]")
try:
    a = get("/terris/priority-actions")
    check("actions list present", len(a.get("actions", [])) > 0, True)
    check("total_actions > 0", a.get("total_actions", 0) > 0, True)
    first = a["actions"][0]
    check("action has record_id", "record_id" in first, True)
    check("action has severity", "severity" in first, True)
    check("action has recommended_action", "recommended_action" in first, True)
except Exception as e:
    fail(f"Terris priority actions: {e}")

# ── Terris Blocking Records ────────────────────────────────────
print("\n[ Terris: Blocking Records ]")
try:
    b = get("/terris/blocking-records")
    check("records list present", "records" in b, True)
    check("blocking_count > 0", b.get("blocking_count", 0) > 0, True)
    if b["records"]:
        check("blocking record has record_id", "record_id" in b["records"][0], True)
        check("blocking record has blocking_reasons", "blocking_reasons" in b["records"][0], True)
except Exception as e:
    fail(f"Terris blocking records: {e}")

# ── Terris Preset Questions ────────────────────────────────────
print("\n[ Terris: Preset Questions ]")
try:
    p = get("/terris/preset-questions")
    check("agent is Terris", p.get("agent"), "Terris")
    check("questions list not empty", len(p.get("questions", [])) > 0, True)
    labels = [q.get("label", "") for q in p.get("questions", [])]
    check("no Ask AGRO-AI in labels", not any("Ask AGRO-AI" in l for l in labels), True)
except Exception as e:
    fail(f"Terris presets: {e}")

# ── Terris Query (key questions) ───────────────────────────────
print("\n[ Terris: Query ]")
QUESTIONS = [
    "What requires my attention today?",
    "Is the current reporting cycle ready?",
    "Which records are blocking cycle close?",
    "Which assumptions still require Fox Canyon validation?",
]
for q in QUESTIONS:
    try:
        r = post("/terris/query", {"query": q})
        check(f"query '{q[:40]}...' → agent=Terris", r.get("agent"), "Terris")
        check(f"  has direct_answer", bool(r.get("direct_answer")), True)
        check(f"  has investigation_stages", len(r.get("investigation_stages", [])) > 0, True)
        check(f"  has disclaimer", bool(r.get("disclaimer")), True)
    except Exception as e:
        fail(f"Terris query '{q[:40]}': {e}")

# ── Terris Query: generate brief ──────────────────────────────
try:
    r = post("/terris/query", {"query": "Generate a reporting-readiness brief."})
    check("generate brief → has direct_answer", bool(r.get("direct_answer")), True)
    check("generate brief → has recommended_action", bool(r.get("recommended_action")), True)
except Exception as e:
    fail(f"Terris generate brief: {e}")

# ── Reviewer workflow ──────────────────────────────────────────
print("\n[ Reviewer Workflow ]")
if record_id:
    try:
        updated = patch(f"/records/{record_id}/review", {
            "status": "requires_attention",
            "notes": "Verification script reviewer note",
            "actor": "verify_script",
        })
        check("review PATCH returns record", "id" in updated or "detail" not in updated, True)
    except Exception as e:
        fail(f"Review PATCH: {e}")

    try:
        recomputed = post(f"/records/{record_id}/recompute")
        check("recompute returns record", "id" in recomputed, True)
    except Exception as e:
        fail(f"Recompute: {e}")

# ── Exceptions resolve ─────────────────────────────────────────
print("\n[ Exception Resolution ]")
try:
    exc = get("/exceptions")
    open_excs = [e for e in exc.get("exceptions", []) if e.get("status") == "open"]
    if open_excs:
        exc_id = open_excs[0]["id"]
        resolved = post(f"/exceptions/{exc_id}/resolve", {
            "resolution": "Verification script test resolution — illustrative",
            "actor": "verify_script",
        })
        check("exception resolve returns status", resolved.get("status"), "resolved")
    else:
        ok("No open exceptions to test (or all resolved in prior steps)")
except Exception as e:
    fail(f"Exception resolution: {e}")

# ── Report Generation ──────────────────────────────────────────
print("\n[ Reports ]")
report_id = None
try:
    rpt = post("/reports/generate", {"report_type": "full"})
    report_id = rpt.get("report_id")
    check("report_id present", report_id is not None, True)
    check("record_count > 0", rpt.get("record_count", 0) > 0, True)
    check("exception_count present", rpt.get("exception_count") is not None, True)
    check("disclaimer present", bool(rpt.get("disclaimer")), True)
    check("disclaimer uses ILLUSTRATIVE", "ILLUSTRATIVE" in rpt.get("disclaimer", "").upper(), True)
except Exception as e:
    fail(f"Report generation: {e}")

if report_id:
    try:
        meta = get(f"/reports/{report_id}")
        check("report meta: report_id matches", meta.get("report_id"), report_id, )
    except Exception as e:
        fail(f"Report meta: {e}")

    try:
        url = BASE + f"/reports/{report_id}/pdf"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            pdf_bytes = r.read()
        check("PDF download returns bytes", len(pdf_bytes) > 100, True)
        check("PDF starts with PDF magic bytes", pdf_bytes[:4], b"%PDF")
    except Exception as e:
        fail(f"PDF download: {e}")

    try:
        url = BASE + f"/reports/{report_id}/bundle"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            zip_bytes = r.read()
        check("ZIP bundle download returns bytes", len(zip_bytes) > 100, True)
        check("ZIP starts with PK magic bytes", zip_bytes[:2], b"PK")
    except Exception as e:
        fail(f"ZIP bundle download: {e}")

# ── Reports List ───────────────────────────────────────────────
try:
    reports = get("/reports")
    check("reports list present", "reports" in reports, True)
    check("total > 0 after generate", reports.get("total", 0) > 0, True)
except Exception as e:
    fail(f"Reports list: {e}")

# ── Final summary ──────────────────────────────────────────────
print(f"\n━━━  Results: {PASS} passed  ·  {FAIL} failed  ━━━\n")
sys.exit(0 if FAIL == 0 else 1)
