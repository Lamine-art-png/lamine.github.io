import { actions, useCommandStore } from "../state/commandStore";

export function VerifiedDecision() {
  const decision = useCommandStore((s) => s.decision);
  const phase = useCommandStore((s) => s.analysisPhase);
  const ready = phase === "complete";

  return (
    <section className="card panel decision" aria-label="Verified water decision">
      <p className="eyebrow">Verified water decision</p>
      <h2 className="decision-headline">{decision.action}</h2>
      <p className="decision-sub value">
        Window {decision.start} · Net {decision.appliedWater}
      </p>

      <dl className="decision-grid">
        <div>
          <dt>Crop</dt>
          <dd className="value">{decision.crop}</dd>
        </div>
        <div>
          <dt>Block</dt>
          <dd className="value">{decision.block}</dd>
        </div>
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
          <dt>Calibration</dt>
          <dd className="value">{decision.calibrationStatus || "representative_fallback"}</dd>
        </div>
        <div>
          <dt>Origin</dt>
          <dd className="value">{decision.recommendationOrigin}</dd>
        </div>
        <div className="span-2">
          <dt>Verification</dt>
          <dd className="value">{decision.verificationStatus || decision.verification}</dd>
        </div>
      </dl>

      <div className="decision-actions">
        <button className="btn primary" disabled={!ready} onClick={() => actions.advanceEvidence("scheduled")}>
          Approve schedule
        </button>
        <button className="btn" disabled={!ready} onClick={() => actions.advanceEvidence("applied")}>
          Confirm applied water
        </button>
        <button className="btn" disabled={!ready} onClick={() => actions.advanceEvidence("observed")}>
          Add field observation
        </button>
        <button className="btn" disabled={!ready} onClick={() => actions.advanceEvidence("verified")}>
          Verify outcome
        </button>
        <button className="btn ghost" onClick={() => actions.navigate("reports")}>
          Open report
        </button>
      </div>
    </section>
  );
}
