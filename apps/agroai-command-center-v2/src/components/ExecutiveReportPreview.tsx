import { getState, useCommandStore } from "../state/commandStore";
import type { ReportModel } from "../state/commandStore";

function toCsv(report: ReportModel): string {
  const rows: [string, string][] = [
    ["Farm", report.farm],
    ["Block", report.block],
    ["Recommendation", report.recommendation],
    ["Planned water", report.plannedWater],
    ["Applied water", report.appliedWater],
    ["Variance", report.variance],
    ["Evidence completeness", report.evidenceCompleteness],
    ["Estimated water savings", report.estimatedWaterSavings],
    ["Verification", report.verification],
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
  ];
  return (
    <section className="card panel report-preview">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Executive report preview</p>
          <h2>Export-ready decision record</h2>
        </div>
        <div className="report-actions">
          <button className="btn ghost compact" onClick={() => window.print()}>
            Print report
          </button>
          <button
            className="btn ghost compact"
            onClick={() => download(`agroai-report-${Date.now()}.csv`, toCsv(getState().report), "text/csv")}
          >
            Export CSV
          </button>
        </div>
      </div>
      <table className="report-table">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td className="value">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
