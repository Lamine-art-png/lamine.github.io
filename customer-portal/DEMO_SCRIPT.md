# AGRO-AI Water Command Center Walkthrough Script

Use this script for customer, integration partner, investor, OEM, and strategic partner walkthroughs of `https://app.agroai-pilot.com`.

## Five Minute Flow

1. **Open the portal** at `https://app.agroai-pilot.com`.
   - Position AGRO-AI as the Water Command Center: scattered signals become reconciled recommendations, execution tasks, verification evidence, and reporting.
2. **Open the evaluation workspace** with **Open Water Command Center**.
   - Explain that sample data is isolated from production telemetry.
3. **Introduce the main story**.
   - Use the hero line: **Scattered irrigation data becomes a verified water decision.**
4. **Show Source intake**.
   - Walk through Connected field, Upload records, and Sample data package.
   - Use **View accepted fields** and **View analysis schema** to show that the backend has a defined contract.
5. **Run intelligence analysis**.
   - Click **Run intelligence analysis**.
   - Show the Intelligence Stream moving through Sources, Normalize, Reconcile, Decide, and Verify.
6. **Show the backend trace**.
   - Point out that the visible steps come from Workbench Engine `analysis_trace`, not static cards.
7. **Review Recommendation**.
   - Show action, start time, duration, depth, confidence, key drivers, limitations, and verification requirement.
8. **Review Reconciliation and Verification**.
   - Walk through planned-vs-applied variance, controller validity, flow-meter agreement, weather demand, soil deficit, field notes, and Earth observation sample layer support.
9. **Move the Verification Chain**.
   - Click **Schedule recommendation**, **Mark as applied**, **Add observation**, and **Verify outcome**.
10. **Open Report preview**.
   - Show evidence completeness, applied variance, compliance posture, and executive summary.
   - Use **Export CSV** or **Print report**.
11. **Show Integrations**.
   - Open **Request backend setup** for WiseConn or Talgil.
   - Copy or download the setup brief and point to the audit event.

## 30 Second Version

1. Open Water Command Center.
2. Show the three input modes.
3. Run intelligence analysis.
4. Show the animated Intelligence Stream and backend trace.
5. Review the recommendation and Source Reconciliation.
6. Show the Verification Chain.
7. Preview the report.
8. Open Integrations and prepare a backend setup request.

## Talk Track

AGRO-AI reads controller history, weather, soil context, field observations, uploaded records, flow evidence, crop context, water cost context, and earth-observation sample layers, then turns them into a verified water decision that a farm team can schedule, verify, and report.

## Current Limitation Language

Provider credentials must be stored server-side through a credential vault and tenant provisioning flow. The static portal does not store provider secrets in browser storage, and the earth-observation layer shown here is a sample layer rather than a live partner integration.
