import { useEffect } from "react";
import { AppShell } from "./components/AppShell";
import { CommandPage } from "./pages/CommandPage";
import { SourcesPage } from "./pages/SourcesPage";
import { ReportsPage } from "./pages/ReportsPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { AuditPage } from "./pages/AuditPage";
import { SettingsPage } from "./pages/SettingsPage";
import { actions, useCommandStore } from "./state/commandStore";

export function App() {
  const route = useCommandStore((s) => s.route);

  useEffect(() => {
    // Derive backend state from a real health probe on mount.
    void actions.init();
  }, []);

  return (
    <AppShell>
      {route === "command" && <CommandPage />}
      {route === "sources" && <SourcesPage />}
      {route === "reports" && <ReportsPage />}
      {route === "integrations" && <IntegrationsPage />}
      {route === "audit" && <AuditPage />}
      {route === "settings" && <SettingsPage />}
    </AppShell>
  );
}
