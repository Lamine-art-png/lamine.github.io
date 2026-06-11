import { actions, useCommandStore } from "../state/commandStore";
import type { Route } from "../state/commandStore";

const PRIMARY: { route: Route; label: string }[] = [
  { route: "command", label: "Command" },
  { route: "sources", label: "Sources" },
  { route: "reports", label: "Reports" },
  { route: "integrations", label: "Integrations" },
];

const COMPLIANCE_ENABLED = import.meta.env.VITE_COMPLIANCE_ENABLED === "true";

const SECONDARY: { route: Route; label: string }[] = [
  ...(COMPLIANCE_ENABLED ? [{ route: "compliance" as Route, label: "Compliance" }] : []),
  { route: "audit", label: "Audit" },
  { route: "settings", label: "Settings" },
];

export function Sidebar() {
  const route = useCommandStore((s) => s.route);
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          AA
        </span>
        <div>
          <div className="brand-name">AGRO-AI</div>
          <div className="brand-sub">Water Command Center</div>
        </div>
      </div>

      <nav aria-label="Primary">
        <p className="nav-label">Primary</p>
        {PRIMARY.map((item) => (
          <button
            key={item.route}
            className={`nav-item ${route === item.route ? "active" : ""}`}
            onClick={() => actions.navigate(item.route)}
            aria-current={route === item.route ? "page" : undefined}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <nav aria-label="Secondary">
        <p className="nav-label">Secondary</p>
        {SECONDARY.map((item) => (
          <button
            key={item.route}
            className={`nav-item ${route === item.route ? "active" : ""}`}
            onClick={() => actions.navigate(item.route)}
            aria-current={route === item.route ? "page" : undefined}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="sidebar-foot">
        <div className="sidebar-mode">Evaluation workspace</div>
        <p className="sidebar-note">Representative records until production targets are connected.</p>
      </div>
    </aside>
  );
}
