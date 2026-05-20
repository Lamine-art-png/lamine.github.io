import { demoReports } from "../demoData.js";
import { reportCard, table } from "../components/ui.js";

const liveReports = [
  { name: "Irrigation Intelligence Report", purpose: "Daily decision narrative with recommendations, risks, and next actions.", status: "Report generation is coming online for this deployment.", coverage: "Live workspace", lastGenerated: "", action: "View readiness" },
  { name: "Planned vs Applied Report", purpose: "Compares planned schedules with controller-applied evidence and exceptions.", status: "Report generation is coming online for this deployment.", coverage: "Operating chain", lastGenerated: "", action: "View readiness" },
  { name: "Water Efficiency Summary", purpose: "Summarizes water use, trends, and operational efficiency by environment.", status: "Report generation is coming online for this deployment.", coverage: "WiseConn + Talgil ready", lastGenerated: "", action: "View readiness" },
  { name: "Verification Compliance Report", purpose: "Shows which recommendations were scheduled, applied, observed, and verified.", status: "Report generation is coming online for this deployment.", coverage: "Verification chain", lastGenerated: "", action: "View readiness" },
  { name: "Integration Health Report", purpose: "Reviews runtime status, sync coverage, limitations, and telemetry freshness.", status: "Connected source live", coverage: "WiseConn + Talgil", lastGenerated: "", action: "Check integrations" },
  { name: "Executive ROI Summary", purpose: "Frames water, energy, cost, and operational value for executive stakeholders.", status: "Report generation is coming online for this deployment.", coverage: "Executive layer", lastGenerated: "", action: "View readiness" },
];

function reportPreview(snapshot) {
  if (!snapshot) return '<section class="empty-state"><h3>No report preview yet</h3><p>Generate a report preview to review customer-ready output, print, or export CSV.</p></section>';
  return `<section class="panel-card report-preview"><div class="section-heading"><p class="eyebrow">Report Preview</p><h2>${snapshot.type}</h2><p>${snapshot.farm} · ${snapshot.block} · ${snapshot.generatedAt}</p></div>${table(
    ["Field", "Value"],
    [
      ["Farm", snapshot.farm], ["Block", snapshot.block], ["Crop", snapshot.crop], ["Controller source", snapshot.controllerSource], ["Recommendation", snapshot.recommendation], ["Scheduled action", snapshot.scheduledAction], ["Applied action", snapshot.appliedAction], ["Observed outcome", snapshot.observedOutcome], ["Verification status", snapshot.verificationStatus], ["Confidence", snapshot.confidence], ["Data quality", snapshot.dataQuality], ["Key drivers", snapshot.keyDrivers.join("; ")], ["Water efficiency note", snapshot.waterEfficiencyNote],
    ]
  )}<div class="runtime-actions"><button class="button secondary" data-action="print-report" type="button">Print Report</button><button class="button primary" data-action="export-csv" type="button">Export CSV</button></div></section>`;
}

export function renderReports(state) {
  const isDemo = state.session.mode === "demo";
  const reports = isDemo ? demoReports : liveReports;
  const snapshot = state.demoRuntime.reportSnapshots?.[0];
  return `<div class="screen-stack"><section class="panel-card"><div class="section-heading"><p class="eyebrow">Report Center</p><h2>Executive-ready reporting</h2><p>Each report explains its purpose, coverage, readiness status, and the next action with customer-ready language.</p></div><div class="report-grid">${reports
    .map((report) => isDemo ? reportCard({ ...report, action: "Preview Report", status: report.status || "Sample preview available", actionAttrs: `data-action="preview-report" data-report-type="${report.name}"` }) : reportCard(report))
    .join("")}</div></section>${isDemo ? reportPreview(snapshot) : ""}</div>`;
}
