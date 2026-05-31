import { useCommandStore } from "../state/commandStore";

function fmt(ts: string): string {
  if (!ts || ts === "—") return "—";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function AnalysisTrace() {
  const trace = useCommandStore((s) => s.trace);
  return (
    <details className="card panel analysis-trace">
      <summary>Analysis trace</summary>
      <p className="muted trace-note">Structured operational sequence. Source records are ingested, normalized, reconciled, scored, and prepared for verification.</p>
      <div className="trace-rows">
        {trace.map((step) => (
          <div className="trace-row" key={step.title}>
            <div className="trace-row-head">
              <strong>{step.title}</strong>
              <span className={`trace-status trace-${step.status}`}>{step.status}</span>
            </div>
            <p className="muted">{step.detail}</p>
            <div className="trace-meta muted">
              <span>Records processed: {step.recordsProcessed.toLocaleString()}</span>
              <span>{fmt(step.timestamp)}</span>
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
