import { actions, useCommandStore } from "../state/commandStore";

const STEPS = [
  ["Source intelligence", "Review provider, uploaded, weather, soil, flow, observation, and earth-observation signals."],
  ["Decision pipeline", "Follow normalization, reconciliation, confidence scoring, recommendation, and verification planning."],
  ["Verified water decision", "Inspect the action, timing, depths, confidence, calibration status, and missing precision."],
  ["Evidence chain", "Record schedule approval, applied water, field observation, and outcome verification."],
  ["Executive report", "Open the report for the decision, evidence completeness, variance, and export-ready summary."],
];

export function GuidedWalkthrough() {
  const active = useCommandStore((s) => s.walkthroughActive);
  const index = useCommandStore((s) => s.walkthroughStep);
  if (!active) return null;
  const [title, body] = STEPS[index] ?? STEPS[0];
  return (
    <div className="walkthrough" role="dialog" aria-live="polite" aria-label="Guided walkthrough">
      <p className="eyebrow">Guided walkthrough</p>
      <h2>{title}</h2>
      <p className="muted">{body}</p>
      <div className="walkthrough-actions">
        <span className="muted">
          {index + 1} / {STEPS.length}
        </span>
        <button className="btn ghost compact" onClick={() => actions.resetWalkthrough()}>
          Reset walkthrough
        </button>
        <button className="btn primary compact" onClick={() => actions.nextWalkthrough()}>
          {index === STEPS.length - 1 ? "Finish" : "Next"}
        </button>
      </div>
    </div>
  );
}
