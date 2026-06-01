import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { Toast } from "./Toast";
import { SourceDrawer } from "./SourceDrawer";
import { useCommandStore } from "../state/commandStore";

export function AppShell({ children }: { children: ReactNode }) {
  const drawerOpen = useCommandStore((s) => s.drawerOpen);
  return (
    <div className="layout">
      <Sidebar />
      <main className="main">
        <Header />
        <div className="page">{children}</div>
      </main>
      {drawerOpen && <SourceDrawer />}
      <Toast />
    </div>
  );
}
