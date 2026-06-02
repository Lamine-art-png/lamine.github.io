import { actions, useCommandStore, ORIGIN_LABEL } from "../state/commandStore";
import type { AnalysisMode } from "../api/contracts";

const STAGES = [
  { key: "collect", label: "Collecting" },
  { key: "normalize", label: "Normalizing" },
  { key: "reconcile", label: "Reconciling" },
  { key: "calculate", label: "Calculating" },
  { key: "validate", label: "Validating" },
  { key: "publish", label: "Publishing" },
  { key: "prepare", label: "Preparing" },
] as const;

const STAGE_DETAILS = [
  "Collecting source records",
  "Normalizing field context",
  "Reconciling source evidence",
  "Calculating agronomic demand",
  "Validating execution evidence",
  "Publishing water recommendation",
  "Preparing verification plan",
];

const MODE_LABEL: Record<AnalysisMode, string> = {
  representative: "Representative evaluation mode",
  uploaded: "Evaluation package analysis",
  live: "Live connected analysis",
};

export function DecisionPipeline() {
  const phase = useCommandStore((s) => s.analysisPhase);
  const message = useCommandStore((s) => s.pipelineMessage);
  const mode = useCommandStore((s) => s.analysisMode);
  const origin = useCommandStore((s) => s.recommendationOrigin);
  const running = phase === "running";

  const buttonLabel = running
    ? "Analyzing source records…"
    : phase === "complete"
    ? "Refresh intelligence"
    : "Ready to analyze";

  const originLabel = ORIGIN_LABEL[origin] ?? origin;

  return (
    <section
      className={`card panel pipeline ${running ? "is-running" : ""}`}
      data-walkthrough-target="decision-pipeline"
    >
      <div className="panel-head">
        <div>
          <p className="eyebrow">Decision processing</p>
          <h2>Source normalization, reconciliation, and recommendation</h2>
        </div>
        <button className="btn primary" onClick={() => actions.refreshIntelligence()} disabled={running}>
          {buttonLabel}
        </button>
      </div>

      <div className="pipeline-track" aria-label="Decision processing stages" role="list">
        <span className="field-lines" aria-hidden="true" />
        <span className="water-line" aria-hidden="true" />
        {STAGES.map((stage, i) => (
          <div
            key={stage.key}
            role="listitem"
            className={`stage ${running ? "stage-active" : phase === "complete" ? "stage-complete" : ""}`}
            style={{ animationDelay: `${i * 0.14}s` }}
            title={STAGE_DETAILS[i]}
          >
            <span className="node" aria-hidden="true" />
            <strong>{stage.label}</strong>
            {phase === "complete" && !running && (
              <span className="stage-check" aria-hidden="true">✓</span>
            )}
          </div>
        ))}
      </div>

      <div className="pipeline-foot">
        <span className="pill">{MODE_LABEL[mode]}</span>
        <span className="pill pill--origin">{originLabel}</span>
        {message && <span className="pipeline-message muted">{message}</span>}
      </div>
    </section>
  );
}
