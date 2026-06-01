import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import CompliancePage from "./pages/CompliancePage";
import { initialCommandState, type Route } from "./state/commandStore";

function PlaceholderPage({ route }: { route: Route }) {
  return <main className="page"><h1>{route}</h1><p>Water Command Center V2 route preserved for upstream integration.</p></main>;
}

export default function App() {
  const [activeRoute, setActiveRoute] = useState<Route>(initialCommandState.activeRoute);
  return <div className="command-center-v2">
    <Sidebar activeRoute={activeRoute} complianceEnabled={initialCommandState.complianceEnabled} onNavigate={setActiveRoute} />
    {activeRoute === "compliance" ? <CompliancePage /> : <PlaceholderPage route={activeRoute} />}
  </div>;
}
