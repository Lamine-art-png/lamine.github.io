import { useCommandStore } from "../state/commandStore";

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  system_generated: "System",
  operator_attestation: "Operator attestation",
  controller_confirmed: "Controller confirmed",
  flow_meter_confirmed: "Flow-meter confirmed",
  field_observation: "Field observation",
  verified_outcome: "Verified outcome",
};

export function EvidenceChain() {
  const evidence = useCommandStore((s) => s.evidence);
  return (
    <section className="card panel evidence-chain" aria-label="Evidence chain" data-walkthrough-target="evidence-chain">
      <p className="eyebrow">Evidence chain</p>
      <ol className="evidence-list">
        {evidence.map((step) => (
          <li key={step.key} className={`evidence-step ${step.status === "Complete" ? "done" : "pending"}`}>
            <span className="evidence-marker" aria-hidden="true" />
            <div className="evidence-body">
              <div className="evidence-top">
                <strong>{step.label}</strong>
                <span className="evidence-status">{step.status}</span>
                {step.status === "Complete" && step.evidenceType && (
                  <span className="evidence-type-badge muted">
                    {EVIDENCE_TYPE_LABELS[step.evidenceType] ?? step.evidenceType}
                  </span>
                )}
              </div>
              <p className="muted value">{step.evidence}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
