import { actions, useCommandStore } from "../state/commandStore";
import type { AnalysisMode, RecommendationOrigin } from "../api/contracts";

const STAGES = ["Sources", "Normalize", "Reconcile", "Decide", "Verify"] as const;

const MODE_LABEL: Record<AnalysisMode, string> = {
  representative: "Representative analysis",
  uploaded: "Uploaded-record analysis",
  live: "Live connected analysis",
};

const ORIGIN_LABEL: Record<RecommendationOrigin, string> = {
  representative_fallback: "Representative fallback",
  deterministic_engine: "Deterministic engine",
  live_intelligence_engine: "Live intelligence engine",
  uploaded_intelligence_engine: "Uploaded intelligence engine",
  insufficient_context: "Insufficient context",
};

export function DecisionPipeline() {
  const phase = useCommandStore((s) => s.analysisPhase);
  const message = useCommandStore((s) => s.pipelineMessage);
  const mode = useCommandStore((s) => s.analysisMode);
  const origin = useCommandStore((s) => s.recommendationOrigin);
  const running = phase === "running";

  const buttonLabel = running ? "Analyzing source records…" : phase === "complete" ? "Refresh intelligence" : "Ready to refresh representative analysis";

  return (
    <section className={`card panel pipeline ${running ? "is-running" : ""}`} data-walkthrough-target="decision-pipeline">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Decision pipeline</p>
          <h2>Source normalization, reconciliation, confidence scoring, and verification</h2>
        </div>
        <button className="btn primary" onClick={() => actions.refreshIntelligence()} disabled={running}>
          {buttonLabel}
        </button>
      </div>

      <div className="pipeline-track" aria-label="Decision pipeline stages">
        <span className="field-lines" aria-hidden="true" />
        <span className="water-line" aria-hidden="true" />
        {STAGES.map((stage, i) => (
          <div key={stage} className={`stage ${running ? "stage-active" : phase === "complete" ? "stage-complete" : ""}`} style={{ animationDelay: `${i * 0.12}s` }}>
            <span className="node" aria-hidden="true" />
            <strong>{stage}</strong>
          </div>
        ))}
      </div>

      <div className="pipeline-foot">
        <span className="pill">{MODE_LABEL[mode]}</span>
        <span className="pill pill--origin">{ORIGIN_LABEL[origin]}</span>
        <span className="pipeline-message muted">{message}</span>
      </div>
    </section>
  );
}
