import { useCommandStore } from "../state/commandStore";

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="metric">
      <p className="metric-label">{label}</p>
      <p className="metric-value value">{value}</p>
      <p className="metric-detail muted">{detail}</p>
    </article>
  );
}

export function ExecutiveStrip() {
  const decision = useCommandStore((s) => s.decision);
  const phase = useCommandStore((s) => s.analysisPhase);
  return (
    <section className="executive-strip" aria-label="Executive decision summary">
      <Metric label="Current decision" value={decision.action} detail={phase === "complete" ? "Decision ready" : "Refreshing…"} />
      <Metric label="Confidence" value={decision.confidence} detail="Decision confidence score" />
      <Metric label="Evidence completeness" value={decision.evidenceCompleteness} detail="Cross-source reconciliation" />
      <Metric label="Estimated water savings" value={decision.estimatedWaterSavings} detail="vs historical baseline" />
    </section>
  );
}
