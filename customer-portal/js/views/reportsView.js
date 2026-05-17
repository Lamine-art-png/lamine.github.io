import { demoReports } from "../demoData.js";
import { reportCard } from "../components/ui.js";

const liveReports = [
  { name: "Irrigation Intelligence Report", purpose: "Daily decision narrative with recommendations, risks, and next actions.", status: "Report generation is coming online for this deployment.", coverage: "Live workspace", lastGenerated: "", action: "View readiness" },
  { name: "Planned vs Applied Report", purpose: "Compares planned schedules with controller-applied evidence and exceptions.", status: "Report generation is coming online for this deployment.", coverage: "Operating chain", lastGenerated: "", action: "View readiness" },
  { name: "Water Efficiency Summary", purpose: "Summarizes water use, trends, and operational efficiency by environment.", status: "Report generation is coming online for this deployment.", coverage: "WiseConn + Talgil ready", lastGenerated: "", action: "View readiness" },
  { name: "Verification Compliance Report", purpose: "Shows which recommendations were scheduled, applied, observed, and verified.", status: "Report generation is coming online for this deployment.", coverage: "Verification chain", lastGenerated: "", action: "View readiness" },
  { name: "Integration Health Report", purpose: "Reviews runtime status, sync coverage, limitations, and telemetry freshness.", status: "Connected source live", coverage: "WiseConn + Talgil", lastGenerated: "", action: "Check integrations" },
  { name: "Executive ROI Summary", purpose: "Frames water, energy, cost, and operational value for executive stakeholders.", status: "Report generation is coming online for this deployment.", coverage: "Executive layer", lastGenerated: "", action: "View readiness" },
];

export function renderReports(state) {
  const reports = state.session.mode === "demo" ? demoReports : liveReports;
  return `<div class="screen-stack"><section class="panel-card"><div class="section-heading"><p class="eyebrow">Report Center</p><h2>Executive-ready reporting</h2><p>Each report explains its purpose, coverage, readiness status, and the next action with customer-ready language.</p></div><div class="report-grid">${reports
    .map(reportCard)
    .join("")}</div></section></div>`;
}
