import { demoReports } from "../demoData.js";
import { reportCard } from "../components/ui.js";

const liveReports = [
  { name: "Daily Irrigation Intelligence Report", description: "Executive summary of daily decisions and next actions.", status: "Report generation is coming online for this deployment.", coverage: "Live workspace", lastGenerated: "", action: "View readiness" },
  { name: "Water Use Summary", description: "Controller and block-level water use summary.", status: "Report generation is coming online for this deployment.", coverage: "WiseConn + Talgil ready", lastGenerated: "", action: "View readiness" },
  { name: "Verification Compliance Report", description: "Evidence that recommendations were scheduled, applied, observed, and verified.", status: "Report generation is coming online for this deployment.", coverage: "Operating chain", lastGenerated: "", action: "View readiness" },
  { name: "Recommendation Confidence Report", description: "Confidence, data-quality, and missing-input trends.", status: "Report generation is coming online for this deployment.", coverage: "Intelligence Engine", lastGenerated: "", action: "View readiness" },
  { name: "Integration Health Report", description: "Provider runtime status and sync coverage.", status: "Runtime status live", coverage: "WiseConn + Talgil", lastGenerated: "", action: "Check integrations" },
];

export function renderReports(state) {
  const reports = state.session.mode === "demo" ? demoReports : liveReports;
  return `<div class="screen-stack"><section class="panel-card"><div class="section-heading"><p class="eyebrow">Report Center</p><h2>Executive-ready reporting</h2><p>Report cards are deployment-safe and avoid debug wording when generation is not yet enabled.</p></div><div class="report-grid">${reports
    .map(reportCard)
    .join("")}</div></section></div>`;
}
