# AGRO-AI Enterprise Portal Demo Script

Use this script for customer, integration partner, and investor walkthroughs of `https://app.agroai-pilot.com`.

## Five minute demo flow

### 1. Open the portal

Open `https://app.agroai-pilot.com` and pause on the entry screen.

Positioning line:

> This is the AGRO-AI Water Command Center: recommendation, execution, and verification for connected irrigation environments.

Point out the two paths:

- **Customer Access** is the enterprise login surface. Production authentication requires backend identity endpoints before real customer credentials are accepted.
- **Interactive Demo** is a one-click simulated workspace for demos.

### 2. Launch the demo workspace

Click **Launch AGRO-AI Demo Workspace**.

Explain:

> The demo workspace is isolated and clearly labeled as demo data. It does not mix simulated data with live production telemetry.

### 3. Show Command Center

Start on **Command Center**.

Call out the Demo Brief:

1. Connected controller environments
2. Farm and zone context
3. Today's water recommendation
4. Execution task
5. Verification chain
6. Reporting layer

Positioning line:

> AGRO-AI is not just a recommendation card. It is an operating layer that tracks the full decision chain.

### 4. Show Farm Explorer

Open **Farm Explorer**.

Show the demo organization, farms, zones, controller provider, crop, soil, data quality, latest recommendation, and verification status.

Positioning line:

> This is where a customer sees which controller environment, crop context, and zone context are feeding the intelligence layer.

### 5. Show recommendation detail

Open **Intelligence**.

Show:

- Decision
- Recommended depth
- Recommended duration
- Timing
- Confidence
- Data quality
- Key drivers
- Live inputs used
- Manual overrides used
- Verification required

Only open **Technical Trace** if the audience is technical.

Positioning line:

> The recommendation is supported by source context, drivers, and a verification plan, not just a black-box answer.

### 6. Show operating chain

Return to **Command Center** or open **Verification**.

Walk through:

1. Recommended
2. Scheduled
3. Applied
4. Observed
5. Verified

Positioning line:

> This is the proof layer. AGRO-AI tracks what was recommended, what was scheduled, what the controller applied, what the field observed, and whether the outcome was verified.

### 7. Show integrations

Open **Integrations**.

Show WiseConn and Talgil cards with status, health, farms/targets, zones/sensors, what AGRO-AI reads, what AGRO-AI generates, and limitations.

Explain:

> Secure credential storage requires backend credential endpoints. The static portal does not store real provider credentials in browser storage.

### 8. Show reports

Open **Reports**.

Show:

- Irrigation Intelligence Report
- Planned vs Applied Report
- Water Efficiency Summary
- Verification Compliance Report
- Integration Health Report
- Executive ROI Summary

Positioning line:

> The report center is the executive layer: daily decisions, planned-vs-applied proof, water efficiency, compliance, integration health, and ROI framing.

### 9. Explain backend/API layer

Explain the real production layer:

- API base: `https://api.agroai-pilot.com`
- WiseConn runtime is live.
- Talgil runtime is live.
- Intelligence Engine is live.
- Live context endpoints are live.
- Live WiseConn recommendation is supported for zone `162803`.

Clarify that demo mode is simulated and labeled, while live mode uses available runtime endpoints.

### 10. Close with customer value

Close with:

> AGRO-AI connects irrigation environments, turns context into actionable decisions, tracks execution, verifies outcomes, and creates an executive evidence layer for water operations.

## 30 second version

1. Open `https://app.agroai-pilot.com`.
2. Click **Launch AGRO-AI Demo Workspace**.
3. Show the **Command Center** and say: “This is recommendation, execution, and verification in one operating view.”
4. Point to the recommendation proof card: decision, depth, duration, timing, confidence, inputs, and verification required.
5. Point to the operating chain: Recommended → Scheduled → Applied → Observed → Verified.
6. Open **Integrations** and say: “WiseConn and Talgil environments feed the intelligence layer; secure credential storage is backend-controlled.”
7. Open **Reports** and say: “This becomes the executive evidence layer for water decisions, verification compliance, integration health, and ROI.”
