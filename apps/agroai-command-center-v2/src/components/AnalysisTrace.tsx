import { useCommandStore, ORIGIN_LABEL } from "../state/commandStore";

function fmt(ts: string): string {
  if (!ts || ts === "—") return "—";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const STATUS_LABEL: Record<string, string> = {
  complete: "Complete",
  running: "Running",
  pending: "Pending",
  review: "Review required",
  limited: "Limited",
};

export function AnalysisTrace() {
  const trace = useCommandStore((s) => s.trace);
  const decision = useCommandStore((s) => s.decision);
  const backend = useCommandStore((s) => s.backend);
  const sessionId = useCommandStore((s) => s.sessionId);
  const origin = useCommandStore((s) => s.recommendationOrigin);
  const mode = useCommandStore((s) => s.analysisMode);
  const backendMeta = useCommandStore((s) => s.backendMeta);
  const schedulable = decision.schedulable;
  const schedulingBlockReasons = decision.schedulingBlockReasons;

  const reviewSteps = trace.filter((s) => s.status === "review");
  const originLabel = ORIGIN_LABEL[origin] ?? origin;
  const nc = backendMeta?.normalizedContext ?? {};

  return (
    <details className="card panel technical-trace">
      <summary className="trace-summary">
        <span className="eyebrow">Technical trace</span>
        <span className="trace-summary-detail muted">
          {reviewSteps.length > 0
            ? `${reviewSteps.length} item${reviewSteps.length > 1 ? "s" : ""} require review`
            : `${trace.length} stages complete`}
          {" · "}Expand for technical review
        </span>
      </summary>

      <div className="trace-body">
        <p className="muted trace-note">
          Structured operational sequence for technical review and partner validation.
          Source records are collected, normalized, reconciled, analyzed, and prepared for verification.
        </p>

        <div className="trace-meta-grid">
          <div>
            <p className="trace-meta-label">Session ID</p>
            <p className="trace-meta-value identifier muted">{sessionId || "Local evaluation session"}</p>
          </div>
          <div>
            <p className="trace-meta-label">Analysis mode</p>
            <p className="trace-meta-value muted">{mode === "representative" ? "Representative evaluation mode" : mode === "uploaded" ? "Evaluation package analysis" : "Live connected analysis"}</p>
          </div>
          <div>
            <p className="trace-meta-label">Recommendation source</p>
            <p className="trace-meta-value muted">{originLabel}</p>
          </div>
          <div>
            <p className="trace-meta-label">Backend status</p>
            <p className="trace-meta-value muted">{backend.status} — {backend.detail}</p>
          </div>
          {decision.calibrationStatus && (
            <div>
              <p className="trace-meta-label">Calibration status</p>
              <p className="trace-meta-value muted">{decision.calibrationStatus}</p>
            </div>
          )}
          {decision.flowValidationState && (
            <div>
              <p className="trace-meta-label">Flow validation state</p>
              <p className="trace-meta-value muted">{decision.flowValidationState}</p>
            </div>
          )}
          {decision.recentIrrigationCreditStatus && (
            <div>
              <p className="trace-meta-label">Recent irrigation credit</p>
              <p className="trace-meta-value muted">{decision.recentIrrigationCreditStatus}</p>
            </div>
          )}
          {schedulable !== undefined && (
            <div>
              <p className="trace-meta-label">Schedulable</p>
              <p className="trace-meta-value muted">{schedulable ? "Yes — scheduling gate passed" : "No — scheduling gate blocked"}</p>
            </div>
          )}
          {!schedulable && schedulingBlockReasons && schedulingBlockReasons.length > 0 && (
            <div style={{ gridColumn: "1 / -1" }}>
              <p className="trace-meta-label">Scheduling block reasons</p>
              <p className="trace-meta-value muted">{schedulingBlockReasons.join("; ")}</p>
            </div>
          )}
          {typeof nc.region === "string" && nc.region && (
            <div>
              <p className="trace-meta-label">Region</p>
              <p className="trace-meta-value muted">{nc.region}</p>
            </div>
          )}
          {typeof nc.weather_window === "string" && nc.weather_window && (
            <div>
              <p className="trace-meta-label">Weather window</p>
              <p className="trace-meta-value muted">{nc.weather_window}</p>
            </div>
          )}
          {nc.area_ha !== undefined && nc.area_ha !== null && (
            <div>
              <p className="trace-meta-label">Field area</p>
              <p className="trace-meta-value muted">{String(nc.area_ha)} {String(nc.area_unit ?? "ha")}</p>
            </div>
          )}
          {backendMeta?.evaluationReferenceTime && (
            <div>
              <p className="trace-meta-label">Evaluation reference time</p>
              <p className="trace-meta-value muted">{fmt(backendMeta.evaluationReferenceTime)}</p>
            </div>
          )}
          {backendMeta?.baselineCalculationNote && (
            <div style={{ gridColumn: "1 / -1" }}>
              <p className="trace-meta-label">Baseline calculation</p>
              <p className="trace-meta-value muted">{backendMeta.baselineCalculationNote}</p>
            </div>
          )}
        </div>

        {backendMeta?.uploadedArtifacts && backendMeta.uploadedArtifacts.length > 0 && (
          <div className="trace-section">
            <p className="trace-section-label eyebrow">Uploaded artifacts used</p>
            <ul className="trace-artifact-list muted">
              {backendMeta.uploadedArtifacts.map((f) => <li key={f}>{f}</li>)}
            </ul>
          </div>
        )}

        {backendMeta?.flowValidationNotes && backendMeta.flowValidationNotes.length > 0 && (
          <div className="trace-section">
            <p className="trace-section-label eyebrow">Flow validation notes</p>
            <ul className="trace-limitation-list muted">
              {backendMeta.flowValidationNotes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          </div>
        )}

        {backendMeta?.recentIrrigationCreditNotes && backendMeta.recentIrrigationCreditNotes.length > 0 && (
          <div className="trace-section">
            <p className="trace-section-label eyebrow">Recent irrigation credit notes</p>
            <ul className="trace-limitation-list muted">
              {backendMeta.recentIrrigationCreditNotes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          </div>
        )}

        <div className="trace-rows">
          {trace.map((step, i) => (
            <div className="trace-row" key={step.title}>
              <div className="trace-row-head">
                <span className="trace-step-num muted">{i + 1}</span>
                <strong>{step.title}</strong>
                <span className={`trace-status trace-${step.status}`}>
                  {STATUS_LABEL[step.status] ?? step.status}
                </span>
              </div>
              <p className="muted trace-detail">{step.detail}</p>
              <div className="trace-meta-row muted">
                <span>Records processed: {step.recordsProcessed.toLocaleString()}</span>
                {step.timestamp && step.timestamp !== "—" && (
                  <span>{fmt(step.timestamp)}</span>
                )}
              </div>
            </div>
          ))}
        </div>

        {(decision.limitations ?? (backendMeta?.warnings ?? []).filter(Boolean)).length > 0 && (
          <div className="trace-limitations">
            <p className="eyebrow" style={{ marginBottom: "8px" }}>Limitations and warnings</p>
            <ul className="trace-limitation-list">
              {(decision.limitations ?? []).map((l) => (
                <li key={l} className="muted">{l}</li>
              ))}
              {(backendMeta?.warnings ?? []).map((w) => (
                <li key={w} className="muted">{w}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
