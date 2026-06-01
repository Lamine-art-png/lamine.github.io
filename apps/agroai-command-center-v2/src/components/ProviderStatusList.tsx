import { actions, useCommandStore } from "../state/commandStore";
import { StatusBadge } from "./StatusBadge";
import type { ProviderStatus } from "../api/contracts";

function tone(status: ProviderStatus["connectionState"]): "ok" | "warn" | "danger" | "neutral" {
  if (status === "Live") return "ok";
  if (status === "Unavailable") return "danger";
  if (status === "Configured" || status === "Limited" || status === "Target selection required") return "warn";
  return "neutral";
}

export function ProviderStatusList({ compact = false }: { compact?: boolean }) {
  const statuses = useCommandStore((s) => s.providerStatuses);
  const phase = useCommandStore((s) => s.providerStatusPhase);
  return (
    <div className="provider-status-list">
      <div className="provider-status-head">
        <p className="muted">{phase === "loading" ? "Refreshing provider status..." : "Runtime status from backend provider routes."}</p>
        <button className="btn compact" onClick={() => void actions.refreshProviderStatuses()}>
          Refresh status
        </button>
      </div>
      {statuses.map((status) => (
        <article className="provider-status-card" key={status.provider}>
          <div className="drawer-item-head">
            <h3>{status.provider}</h3>
            <StatusBadge label={status.connectionState} tone={tone(status.connectionState)} />
          </div>
          <dl className={compact ? "provider-status-grid compact" : "provider-status-grid"}>
            <div>
              <dt>Runtime</dt>
              <dd>{status.runtimeState}</dd>
            </div>
            <div>
              <dt>Farms / targets</dt>
              <dd>{status.farms ?? status.targets ?? "—"}</dd>
            </div>
            <div>
              <dt>Zones / sensors</dt>
              <dd>{status.zones ?? status.sensors ?? "—"}</dd>
            </div>
            <div>
              <dt>Last checked</dt>
              <dd>{status.lastChecked ? new Date(status.lastChecked).toLocaleTimeString() : "—"}</dd>
            </div>
          </dl>
          <p className="muted">{status.limitations.join(" ")}</p>
        </article>
      ))}
      {!statuses.length && <p className="muted">Provider status has not been loaded yet.</p>}
    </div>
  );
}
