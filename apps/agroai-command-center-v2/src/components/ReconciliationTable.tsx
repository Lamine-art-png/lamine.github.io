import { useCommandStore } from "../state/commandStore";
import { StatusBadge } from "./StatusBadge";
import type { SourceStatus } from "../api/contracts";

function tone(status: SourceStatus): "ok" | "warn" | "neutral" {
  if (status === "Matched" || status === "Accepted") return "ok";
  if (status === "Review" || status === "Pending" || status === "Pending target") return "warn";
  return "neutral";
}

export function ReconciliationTable() {
  const rows = useCommandStore((s) => s.reconciliation);
  return (
    <section className="card panel reconciliation">
      <p className="eyebrow">Source reconciliation</p>
      <h2>How source signals resolve into one decision</h2>
      <div className="table-scroll">
        <table className="recon-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Signal</th>
              <th>Interpretation</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.source}>
                <td className="value">{row.source}</td>
                <td className="value">{row.signal}</td>
                <td className="value">{row.interpretation}</td>
                <td>
                  <StatusBadge label={row.status} tone={tone(row.status)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
