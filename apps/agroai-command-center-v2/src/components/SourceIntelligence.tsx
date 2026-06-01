import { actions, useCommandStore } from "../state/commandStore";
import { StatusBadge } from "./StatusBadge";
import type { SourceStatus } from "../api/contracts";

function tone(status: SourceStatus): "ok" | "warn" | "neutral" {
  if (status === "Matched" || status === "Accepted" || status === "Connected source") return "ok";
  if (status === "Review" || status === "Pending" || status === "Pending target") return "warn";
  return "neutral";
}

export function SourceIntelligence() {
  const sources = useCommandStore((s) => s.sources);
  const providers = useCommandStore((s) => s.providerStatuses);
  return (
    <section className="card panel source-intel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Source intelligence</p>
          <h2>Signals used to understand field conditions</h2>
        </div>
        <button className="btn ghost compact" onClick={() => actions.openDrawer()}>
          Add or manage sources
        </button>
      </div>
      <div className="source-table" role="table" aria-label="Source intelligence">
        <div className="source-row source-row--head" role="row">
          <span role="columnheader">Source</span>
          <span role="columnheader">Latest signal</span>
          <span role="columnheader">Records</span>
          <span role="columnheader">Contribution</span>
          <span role="columnheader">Status</span>
        </div>
        {sources.map((row) => (
          <div className="source-row" role="row" key={row.source}>
            <span className="source-name value" role="cell">
              {row.source}
            </span>
            <span className="value" role="cell">
              {row.latestSignal}
            </span>
            <span className="num" role="cell">
              {row.records}
            </span>
            <span className="num" role="cell">
              {row.contribution}
            </span>
            <span role="cell">
              <StatusBadge label={row.status} tone={tone(row.status)} />
            </span>
          </div>
        ))}
      </div>
      <div className="source-provider-summary" aria-label="Provider runtime summary">
        {providers.slice(0, 3).map((p) => (
          <span key={p.provider} className="provider-summary-item">
            <strong>{p.provider}</strong> {p.connectionState}
          </span>
        ))}
        <button className="btn ghost compact" onClick={() => void actions.refreshProviderStatuses()}>
          Refresh status
        </button>
      </div>
    </section>
  );
}
