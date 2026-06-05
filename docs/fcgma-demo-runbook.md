# FCGMA Water Intelligence Copilot — Demo Runbook

**Version:** 0.1.0  
**Updated:** 2026-06-05

---

## What Is Live

- WiseConn controller telemetry when `WISECONN_API_KEY` is configured (provides irrigation schedule events, NOT extraction volumes)
- CIMIS reference ET data when `CIMIS_APP_KEY` is configured

## What Is Authorized

- WiseConn API access via existing AGRO-AI integration (controller telemetry only)
- CIMIS public API (weather context only)
- FCGMA public documents (rule pack reference)

## What Is Public Context

- FCGMA flowmeter requirements: https://fcgma.org/flowmeter-requirements/
- FCGMA agency forms: https://fcgma.org/agency-forms/
- FCGMA interactive map: https://fcgma.org/interactive-map/
- Resolution 2018-01: https://s42135.pcdn.co/wp-content/uploads/2022/07/Resolution-2018-01.pdf
- CIMIS REST API: https://et.water.ca.gov/Rest/Index

## What Is Replayed

- WiseConn sanitized replay: captures from authorized WiseConn access with customer identifiers replaced by anonymized IDs

## What Is Injected

- 16 demonstration scenarios covering all major exception types
- All carry `scenario_injected: true` and a visible label
- Scenarios are isolated from any live data

---

## How to Run Locally

```bash
# Option 1: Use the demo script
chmod +x scripts/run_fcgma_demo.sh
./scripts/run_fcgma_demo.sh

# Option 2: Manual
cd agroai_api
pip install -r requirements.txt
DATABASE_URL=sqlite:///./demo.db uvicorn app.main:app --reload --port 8000

# Then open the demo portal
cd customer-portal
python -m http.server 8080
# Visit: http://localhost:8080/fcgma-demo.html
```

---

## How to Configure CIMIS_APP_KEY

1. Register at https://et.water.ca.gov/Home/Register (free)
2. Obtain your app key
3. Set environment variable: `export CIMIS_APP_KEY=your-key-here`
4. Restart the backend server
5. The weather context panel will show live ETo data for the configured station

**Never commit a real CIMIS_APP_KEY to git.**

---

## How to Capture a Sanitized WiseConn Replay Safely

```bash
# This requires WISECONN_API_KEY to be set
# Run the sanitized capture script (creates anonymized replay files)
# DO NOT commit raw captures

# The capture script strips:
# - Customer names
# - Farm names  
# - Exact addresses
# - Sensitive identifiers (replaced with stable anonymized IDs)

# Generated files go to: agroai_api/app/services/fcgma/replays/
# These paths are in .gitignore — never commit them

python agroai_api/scripts/cli.py wiseconn-demo  # existing WiseConn demo script
```

---

## How to Reset Scenarios

```bash
# Via API
curl -X POST http://localhost:8000/v1/fcgma-demo/scenarios/reset

# Via UI: click "Reset Scenarios" button in the header
```

---

## How to Generate a Report

```bash
# Via API
curl -X POST http://localhost:8000/v1/fcgma-demo/reports/generate \
  -H "Content-Type: application/json" \
  -d '{"report_type": "full", "reporting_period": "2026-Q1"}'

# Returns report_id, then download:
curl http://localhost:8000/v1/fcgma-demo/reports/{report_id}/pdf -o report.pdf
curl http://localhost:8000/v1/fcgma-demo/reports/{report_id}/bundle -o bundle.zip

# Via UI: click "Generate Report" button in header or Reports tab
```

---

## How to Use the Copilot

```bash
# Via API
curl -X POST http://localhost:8000/v1/fcgma-demo/copilot/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What requires my attention today?"}'

# Via UI: use the right-side Ask AGRO-AI panel
# Preset buttons load common questions
# Voice input available in Chrome/Edge (click microphone button)
```

---

## 10-Minute Executive Demo Sequence

1. **(0:00)** Open http://localhost:8080/fcgma-demo.html
   - Point to the truthfulness banner: "This is what honest AI infrastructure looks like."
   - Metric strip: records, exceptions, provisional AF

2. **(1:00)** Intelligence summary card
   - AI has identified specific exception types
   - This is computed from real backend tools, not written by a human

3. **(2:00)** Ask AGRO-AI: "What requires my attention today?"
   - Shows grounded answer with record IDs and citations
   - Explain: deterministic tools run first, LLM only formats (if key configured)

4. **(3:30)** Click "Review Priority Records"
   - Show filter bar: meter reset, CombCode unresolved, pump without meter
   - Click on a record requiring attention — open the drawer

5. **(5:00)** Record drawer deep-dive
   - Evidence class badge: groundwater_meter_reading
   - Open exceptions with severity
   - Click "How was this calculated?" — show calculation steps
   - Source lineage block — sanitized hash, calculation version
   - DEMO badge: explain this is a scenario illustration

6. **(6:30)** Source Health tab
   - Show each provider's status
   - Explain Ranch Systems is explicitly disabled: "We don't have their schema"
   - CIMIS: show unavailable state with clear message

7. **(7:30)** Reports tab
   - Click Generate Report
   - Download PDF — show it looks professional with prominent disclaimer

8. **(8:30)** Ask AGRO-AI: "What data would Fox Canyon need to provide to refine this calculation?"
   - Shows gap analysis: CombCode mapping, backup estimation procedure, Ranch Systems schema

9. **(9:30)** Closing: "What you've seen is the infrastructure for an honest applied-water intelligence system. The demo scenarios illustrate every exception type you'd encounter in production. The gaps are clearly labeled. This is what we'd build together with your data."

---

## What Must NOT Be Claimed During the Fox Canyon Call

- Do NOT claim this system has been authorized by Fox Canyon
- Do NOT claim the applied-water calculations are validated regulatory logic
- Do NOT claim AGRO-AI has a Ranch Systems integration
- Do NOT claim the calculation results are submission-ready
- Do NOT claim CIMIS data replaces flowmeter records
- Do NOT suggest the AI copilot approves records or determines compliance

**Always say:** "This is a demonstration of the workflow and intelligence infrastructure. The actual applied-water model requires your validation."

---

## What to Request from Fox Canyon Afterward

1. CombCode lookup table for the management zone(s) of interest
2. Official applied-water attribution methodology
3. Pre-approved backup estimation procedure and form references
4. Sample AMI CSV export format (or direct feed specification)
5. Confirmation of reporting period and deadline schedule
6. Well-to-parcel mapping for the demonstration area
7. Any FCGMA-specific unit or multiplier requirements

## What to Request from Ranch Systems Afterward

1. Official Ranch Systems AMI export schema
2. Sample anonymized export file
3. API authorization process for third-party integrations
4. Confirmation of data format version

---

## Environment Variables Required

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | No (defaults to SQLite) | Database connection string |
| `WISECONN_API_KEY` | Optional | Enables live WiseConn controller telemetry |
| `CIMIS_APP_KEY` | Optional | Enables live CIMIS weather context |
| `ANTHROPIC_API_KEY` | Optional | Enables LLM copilot formatting (deterministic fallback used if absent) |
| `CIMIS_TARGET` | Optional | CIMIS station (default: Station 152, Camarillo, Ventura County) |
