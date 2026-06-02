import { actions, useCommandStore, ORIGIN_LABEL } from "../state/commandStore";

function flowTone(state?: string): string {
  if (!state) return "muted";
  const lower = state.toLowerCase();
  if (lower.includes("validated") || lower.includes("reconciled")) return "flow-ok";
  if (lower.includes("inconsistent")) return "flow-warn";
  if (lower.includes("incomplete") || lower.includes("signal")) return "flow-incomplete";
  return "muted";
}

export function VerifiedDecision() {
  const decision = useCommandStore((s) => s.decision);
  const phase = useCommandStore((s) => s.analysisPhase);
  const evidence = useCommandStore((s) => s.evidence);
  const scenarioId = useCommandStore((s) => s.scenarioId);
  const ready = phase === "complete";
  const isIncomplete = scenarioId === "incomplete-evidence";

  const byKey = Object.fromEntries(evidence.map((s) => [s.key, s]));
  const canSchedule = ready && !isIncomplete && byKey.recommended?.status === "Complete";
  const canApply = ready && byKey.scheduled?.status === "Complete";
  const canObserve = ready && byKey.applied?.status === "Complete";
  const canVerify = ready && byKey.observed?.status === "Complete";

  const originLabel = ORIGIN_LABEL[decision.recommendationOrigin] ?? decision.recommendationOrigin;
  const flowLabel = decision.flowValidationState ?? "Flow status unknown";
  const flowClass = flowTone(decision.flowValidationState);

  return (
    <section
      className={`card panel decision ${isIncomplete ? "decision--review" : ""}`}
      aria-label="Verified water decision"
      data-walkthrough-target="verified-decision"
    >
      <p className="eyebrow">
        {isIncomplete ? "Evidence review" : "Verified water decision"}
      </p>
      <h2 className="decision-headline">{decision.action}</h2>

      {!isIncomplete && (
        <p className="decision-sub value">
          {decision.start} · Net {decision.appliedWater}
        </p>
      )}

      {isIncomplete && decision.limitations && decision.limitations.length > 0 && (
        <div className="decision-limitations">
          <p className="eyebrow" style={{ marginBottom: "8px" }}>Limitations</p>
          <ul className="limitations-list">
            {decision.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      )}

      <dl className="decision-grid">
        <div>
          <dt>Crop</dt>
          <dd className="value">{decision.crop}</dd>
        </div>
        <div>
          <dt>Block</dt>
          <dd className="value">{decision.block}</dd>
        </div>
        {decision.area && (
          <div>
            <dt>Area</dt>
            <dd className="value">{decision.area}</dd>
          </div>
        )}
        {decision.irrigationMethod && (
          <div>
            <dt>Irrigation method</dt>
            <dd className="value">{decision.irrigationMethod}</dd>
          </div>
        )}
        {decision.controller && (
          <div className="span-2">
            <dt>Controller</dt>
            <dd className="value">{decision.controller}</dd>
          </div>
        )}
        <div className="span-2">
          <dt>Driver</dt>
          <dd className="value">{decision.driver}</dd>
        </div>
        <div>
          <dt>Gross depth</dt>
          <dd className="value">{decision.grossWater || "Pending flow evidence"}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd className="value">{decision.duration || "Withheld until flow is validated"}</dd>
        </div>
        <div>
          <dt>Estimated volume</dt>
          <dd className="value">{decision.estimatedVolume || "Requires field area"}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd className="value">{decision.confidence}</dd>
        </div>
        <div>
          <dt>Evidence completeness</dt>
          <dd className="value">{decision.evidenceCompleteness}</dd>
        </div>
        <div>
          <dt>Estimated savings</dt>
          <dd className="value">{decision.estimatedWaterSavings}</dd>
        </div>
        <div>
          <dt>Calibration</dt>
          <dd className="value">{decision.calibrationStatus || "Defaults applied — not farm-specific"}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd className="value">{originLabel}</dd>
        </div>
        <div className="span-2">
          <dt>Flow validation</dt>
          <dd className={`value flow-state ${flowClass}`}>{flowLabel}</dd>
        </div>
        <div className="span-2">
          <dt>Verification requirement</dt>
          <dd className="value">{decision.verificationStatus || decision.verification}</dd>
        </div>
      </dl>

      {isIncomplete && decision.nextEvidenceRequired && decision.nextEvidenceRequired.length > 0 && (
        <div className="next-evidence">
          <p className="eyebrow" style={{ marginBottom: "8px" }}>Next evidence required</p>
          <ol className="next-evidence-list">
            {decision.nextEvidenceRequired.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </div>
      )}

      <div className="decision-actions">
        {!isIncomplete && (
          <>
            <button className="btn primary" disabled={!canSchedule} onClick={() => actions.advanceEvidence("scheduled")}>
              Approve schedule
            </button>
            <button className="btn" disabled={!canApply} onClick={() => actions.advanceEvidence("applied")}>
              Confirm applied water
            </button>
            <button className="btn" disabled={!canObserve} onClick={() => actions.advanceEvidence("observed")}>
              Add field observation
            </button>
            <button className="btn" disabled={!canVerify} onClick={() => actions.advanceEvidence("verified")}>
              Verify outcome
            </button>
          </>
        )}
        <button className="btn ghost" onClick={() => actions.navigate("reports")}>
          Open report
        </button>
      </div>
    </section>
  );
}
