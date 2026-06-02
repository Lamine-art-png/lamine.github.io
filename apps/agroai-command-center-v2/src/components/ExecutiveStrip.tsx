import { useCommandStore } from "../state/commandStore";

function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: string }) {
  return (
    <article className={`metric ${tone ? `metric-${tone}` : ""}`}>
      <p className="metric-label">{label}</p>
      <p className="metric-value value">{value}</p>
      <p className="metric-detail muted">{detail}</p>
    </article>
  );
}

export function ExecutiveStrip() {
  const decision = useCommandStore((s) => s.decision);
  const phase = useCommandStore((s) => s.analysisPhase);
  const scenarioId = useCommandStore((s) => s.scenarioId);

  const isIncomplete = scenarioId === "incomplete-evidence";
  const decisionDetail = phase === "running"
    ? "Analyzing source records…"
    : isIncomplete
    ? "Evidence review required"
    : "Decision ready";

  const confidenceTone = isIncomplete ? undefined : undefined;

  return (
    <section className="executive-strip" aria-label="Executive decision summary">
      <Metric
        label="Current decision"
        value={decision.action}
        detail={decisionDetail}
      />
      <Metric
        label="Confidence"
        value={decision.confidence}
        detail={isIncomplete ? "Evidence incomplete" : "Cross-source confidence score"}
        tone={confidenceTone}
      />
      <Metric
        label="Evidence completeness"
        value={decision.evidenceCompleteness}
        detail={isIncomplete ? "Missing sources flagged" : "Cross-source reconciliation"}
      />
      <Metric
        label="Estimated water savings"
        value={decision.estimatedWaterSavings}
        detail={isIncomplete ? "Withheld — evidence incomplete" : "vs evaluation baseline"}
      />
    </section>
  );
}
