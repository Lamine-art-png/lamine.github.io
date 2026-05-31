import { useState } from "react";
import { useCommandStore } from "../state/commandStore";
import { SCENARIO_OPTIONS } from "../state/commandStore";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";
import { BackendBadge, StatusBadge } from "./StatusBadge";

export function Header() {
  const scenarioId = useCommandStore((s) => s.scenarioId);
  const backend = useCommandStore((s) => s.backend);
  const [menuOpen, setMenuOpen] = useState(false);
  const scenarioName = SCENARIO_OPTIONS.find((s) => s.id === scenarioId)?.name ?? "Alpha Vineyard";

  return (
    <header className="app-header">
      <div className="header-titleblock">
        <div className="header-title-row">
          <h1 className="value">{scenarioName} · Water Command Center</h1>
          <WorkspaceSwitcher />
          <span className="provenance" title="Representative records are used until production targets are connected.">
            Representative data
          </span>
        </div>
        <p className="header-subtitle">Scattered irrigation data becomes a verified water decision.</p>
        <div className="status-row" aria-label="Workspace status">
          <StatusBadge label="Mixed sources" tone="neutral" />
          <StatusBadge label="Evidence chain active" tone="ok" />
          <BackendBadge status={backend.status} detail={backend.detail} />
        </div>
      </div>

      <div className="header-toolbar">
        <details className="user-menu" open={menuOpen} onToggle={(e) => setMenuOpen((e.target as HTMLDetailsElement).open)}>
          <summary aria-label="Account menu">
            <span className="avatar">OU</span>
          </summary>
          <div className="menu-panel" role="menu">
            <div className="menu-identity">
              <strong>Operations user</strong>
              <span>Evaluation workspace</span>
            </div>
            <a className="menu-item" href="mailto:support@agroai-pilot.com?subject=AGRO-AI%20Water%20Command%20Center">
              Help
            </a>
          </div>
        </details>
      </div>
    </header>
  );
}
