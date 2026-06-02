import { actions, useCommandStore } from "../state/commandStore";
import type { Route } from "../state/commandStore";

const PRIMARY: { route: Route; label: string; complianceOnly?: boolean }[] = [
  { route: "command", label: "Command" },
  { route: "sources", label: "Sources" },
  { route: "reports", label: "Reports" },
  { route: "integrations", label: "Integrations" },
  { route: "compliance", label: "Compliance", complianceOnly: true },
];
const SECONDARY: { route: Route; label: string }[] = [
  { route: "audit", label: "Audit" },
  { route: "settings", label: "Settings" },
];
function complianceFeatureEnabled() {
  return import.meta.env.VITE_CALIFORNIA_COMPLIANCE_PACK_ENABLED === "true" || Boolean(import.meta.env.VITE_NON_PRODUCTION_COMPLIANCE_DEMO_TOKEN);
}
export function Sidebar() {
  const route = useCommandStore((s) => s.route);
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">AA</span>
        <div><div className="brand-name">AGRO-AI</div><div className="brand-sub">Water Command Center</div></div>
      </div>
      <nav aria-label="Primary">
        <p className="nav-label">Primary</p>
        {PRIMARY.filter((item) => !item.complianceOnly || complianceFeatureEnabled()).map((item) => (
          <button key={item.route} className={`nav-item ${route === item.route ? "active" : ""}`} onClick={() => actions.navigate(item.route)} aria-current={route === item.route ? "page" : undefined}>{item.label}</button>
        ))}
      </nav>
      <nav aria-label="Secondary">
        <p className="nav-label">Secondary</p>
        {SECONDARY.map((item) => (
          <button key={item.route} className={`nav-item ${route === item.route ? "active" : ""}`} onClick={() => actions.navigate(item.route)} aria-current={route === item.route ? "page" : undefined}>{item.label}</button>
        ))}
      </nav>
      <div className="sidebar-foot"><div className="sidebar-mode">Evaluation workspace</div><p className="sidebar-note">Representative records until production targets are connected.</p></div>
    </aside>
  );
}
