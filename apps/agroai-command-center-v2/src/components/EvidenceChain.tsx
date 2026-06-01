import { useCommandStore } from "../state/commandStore";

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
              </div>
              <p className="muted value">{step.evidence}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
