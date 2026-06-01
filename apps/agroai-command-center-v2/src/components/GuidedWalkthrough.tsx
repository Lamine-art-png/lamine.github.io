import { useEffect } from "react";
import { actions, useCommandStore } from "../state/commandStore";

const STEPS = [
  ["source-intelligence", "Source intelligence", "Review provider, uploaded, weather, soil, flow, observation, and earth-observation signals."],
  ["decision-pipeline", "Decision pipeline", "Follow normalization, reconciliation, confidence scoring, recommendation, and verification planning."],
  ["verified-decision", "Verified water decision", "Inspect the action, timing, depths, confidence, calibration status, and missing precision."],
  ["evidence-chain", "Evidence chain", "Record schedule approval, applied water, field observation, and outcome verification."],
  ["executive-report", "Executive report", "Open the report for the decision, evidence completeness, variance, and export-ready summary."],
] as const;

export function GuidedWalkthrough() {
  const active = useCommandStore((s) => s.walkthroughActive);
  const index = useCommandStore((s) => s.walkthroughStep);
  const [target, title, body] = STEPS[index] ?? STEPS[0];

  useEffect(() => {
    document.body.classList.toggle("walkthrough-active", active);
    document.querySelectorAll(".walkthrough-focus-target").forEach((el) => el.classList.remove("walkthrough-focus-target"));
    if (!active) return;
    const el = document.querySelector(`[data-walkthrough-target="${target}"]`);
    if (el instanceof HTMLElement) {
      el.classList.add("walkthrough-focus-target");
      el.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
    return () => {
      document.body.classList.remove("walkthrough-active");
      document.querySelectorAll(".walkthrough-focus-target").forEach((node) => node.classList.remove("walkthrough-focus-target"));
    };
  }, [active, target]);

  if (!active) return null;
  return (
    <div className="walkthrough" role="dialog" aria-live="polite" aria-label="Guided walkthrough" aria-describedby="walkthrough-copy">
      <p className="eyebrow">Guided walkthrough</p>
      <h2>{title}</h2>
      <p className="muted" id="walkthrough-copy">
        {body}
      </p>
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
