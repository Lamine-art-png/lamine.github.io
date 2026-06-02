import { getState, useCommandStore } from "../state/commandStore";
import type { ReportModel } from "../state/commandStore";

function toCsv(report: ReportModel, extra: Record<string, string>): string {
  const rows: [string, string][] = [
    ["Farm", report.farm],
    ["Block", report.block],
    ["Recommendation", report.recommendation],
    ["Planned water", report.plannedWater],
    ["Applied water", report.appliedWater],
    ["Variance", report.variance],
    ["Evidence completeness", report.evidenceCompleteness],
    ["Estimated water savings", report.estimatedWaterSavings],
    ["Verification status", report.verification],
    ...Object.entries(extra).map(([k, v]) => [k, v] as [string, string]),
  ];
  return rows.map(([k, v]) => `"${k}","${String(v).replace(/"/g, '""')}"`).join("\n");
}

function download(name: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function ExecutiveReportPreview() {
  const report = useCommandStore((s) => s.report);
  const decision = useCommandStore((s) => s.decision);
  const scenarioId = useCommandStore((s) => s.scenarioId);
  const isIncomplete = scenarioId === "incomplete-evidence";
  const now = new Date().toLocaleString();

  const mainRows: [string, string][] = [
    ["Farm", report.farm],
    ["Block", report.block],
    ["Crop", decision.crop],
    ["Recommendation", report.recommendation],
    ["Timing window", decision.start],
    ["Planned water (gross)", report.plannedWater],
    ["Applied water", report.appliedWater],
    ["Planned vs applied variance", report.variance],
    ["Field observation", isIncomplete ? "Withheld" : "Pending — add field observation"],
    ["Verification status", report.verification],
    ["Estimated water savings", report.estimatedWaterSavings],
    ["Calibration status", decision.calibrationStatus || "Defaults applied — not farm-specific"],
    ["Evidence completeness", report.evidenceCompleteness],
  ];

  const limitationsRows: [string, string][] = isIncomplete && decision.limitations
    ? decision.limitations.map((l, i) => [`Limitation ${i + 1}`, l])
    : [];

  const extraCsvFields = {
    "Crop": decision.crop,
    "Timing window": decision.start,
    "Calibration status": decision.calibrationStatus || "Defaults applied",
    "Report generated": now,
  };

  return (
    <section className="card panel report-preview" data-walkthrough-target="executive-report">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Executive report preview</p>
          <h2>
            {isIncomplete ? "Evidence review record" : "Export-ready decision record"}
          </h2>
        </div>
        <div className="report-actions">
          <button className="btn ghost compact" onClick={() => window.print()}>
            Print report
          </button>
          <button
            className="btn ghost compact"
            onClick={() =>
              download(
                `agroai-report-${Date.now()}.csv`,
                toCsv(getState().report, extraCsvFields),
                "text/csv",
              )
            }
          >
            Export CSV
          </button>
        </div>
      </div>

      <table className="report-table">
        <tbody>
          {mainRows.map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td className="value">{v}</td>
            </tr>
          ))}
          {limitationsRows.map(([k, v]) => (
            <tr key={k} className="report-row-limitation">
              <th>{k}</th>
              <td className="value muted">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="report-timestamp muted">Report generated: {now}</p>
    </section>
  );
}
