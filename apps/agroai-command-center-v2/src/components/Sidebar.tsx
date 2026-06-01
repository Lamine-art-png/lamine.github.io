import type { Route } from "../state/commandStore";

const navItems: Array<{ route: Route; label: string; complianceOnly?: boolean }> = [
  { route: "command", label: "Command" },
  { route: "sources", label: "Sources" },
  { route: "reports", label: "Reports" },
  { route: "integrations", label: "Integrations" },
  { route: "compliance", label: "Compliance", complianceOnly: true },
  { route: "settings", label: "Settings" },
];

export function Sidebar({ activeRoute, complianceEnabled, onNavigate }: { activeRoute: Route; complianceEnabled: boolean; onNavigate: (route: Route) => void }) {
  return <aside className="sidebar">
    <div className="brand">AGRO-AI</div>
    <nav aria-label="Water Command Center navigation">
      {navItems.filter((item) => !item.complianceOnly || complianceEnabled).map((item) => (
        <button key={item.route} className={activeRoute === item.route ? "active" : ""} type="button" onClick={() => onNavigate(item.route)}>{item.label}</button>
      ))}
    </nav>
  </aside>;
}
