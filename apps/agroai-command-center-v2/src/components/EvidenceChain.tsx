import { useCommandStore } from "../state/commandStore";

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  system_generated: "System generated",
  operator_attestation: "Operator attestation",
  controller_confirmed: "Controller confirmed",
  flow_meter_confirmed: "Flow-meter confirmed",
  field_observation: "Field observation",
  verified_outcome: "Verified outcome",
};

const NEXT_ACTION: Record<string, string> = {
  recommended: "Approve schedule to continue",
  scheduled: "Confirm applied water to continue",
  applied: "Add field observation to continue",
  observed: "Verify outcome to complete chain",
  verified: "Evidence chain complete",
};

function fmtTime(ts: string): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function EvidenceChain() {
  const evidence = useCommandStore((s) => s.evidence);
  const lastComplete = evidence.filter((s) => s.status === "Complete");
  const nextPending = evidence.find((s) => s.status === "Pending");

  return (
    <section className="card panel evidence-chain" aria-label="Evidence chain" data-walkthrough-target="evidence-chain">
      <div className="panel-head" style={{ marginBottom: "var(--s-3)" }}>
        <div>
          <p className="eyebrow">Evidence chain</p>
          <h2>Applied-water verification sequence</h2>
        </div>
        <span className="evidence-progress muted">
          {lastComplete.length}/{evidence.length} complete
        </span>
      </div>
      <ol className="evidence-list">
        {evidence.map((step, i) => {
          const isDone = step.status === "Complete";
          const isNext = step === nextPending;
          return (
            <li key={step.key} className={`evidence-step ${isDone ? "done" : isNext ? "is-next" : "pending"}`}>
              <span className="evidence-marker" aria-hidden="true">
                {isDone ? "✓" : <span className="evidence-num">{i + 1}</span>}
              </span>
              <div className="evidence-body">
                <div className="evidence-top">
                  <strong className="evidence-label">{step.label}</strong>
                  <span className={`evidence-status-chip ${isDone ? "chip-done" : isNext ? "chip-next" : "chip-pending"}`}>
                    {isDone ? "Complete" : isNext ? "Ready" : "Pending"}
                  </span>
                </div>
                <p className="evidence-owner muted">{step.owner}</p>
                {isDone && step.timestamp && (
                  <p className="evidence-time muted">{fmtTime(step.timestamp)}</p>
                )}
                {isDone && step.evidenceType && (
                  <span className="evidence-type-badge muted">
                    {EVIDENCE_TYPE_LABELS[step.evidenceType] ?? step.evidenceType}
                  </span>
                )}
                {isDone && step.evidence && (
                  <p className="evidence-detail muted">{step.evidence}</p>
                )}
                {isNext && (
                  <p className="evidence-next-action">{NEXT_ACTION[step.key]}</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
