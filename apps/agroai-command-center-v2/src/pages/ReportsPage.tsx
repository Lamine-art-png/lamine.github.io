import { ExecutiveReportPreview } from "../components/ExecutiveReportPreview";

const REPORTS = [
  ["Irrigation Intelligence Report", "Daily decision narrative with recommendations, drivers, and next actions."],
  ["Planned vs Applied Report", "Compares scheduled tasks against controller-applied evidence and exceptions."],
  ["Verification Compliance Report", "Which recommendations were scheduled, applied, observed, and verified."],
  ["Executive ROI Summary", "Water, energy, cost, and operational value for executive stakeholders."],
];

export function ReportsPage() {
  return (
    <div className="stack">
      <section className="card panel">
        <p className="eyebrow">Report center</p>
        <h2>Executive-ready reporting</h2>
        <div className="report-grid">
          {REPORTS.map(([name, purpose]) => (
            <article className="report-card" key={name}>
              <h3>{name}</h3>
              <p className="muted">{purpose}</p>
            </article>
          ))}
        </div>
      </section>
      <ExecutiveReportPreview />
    </div>
  );
}
