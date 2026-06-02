import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { actions, useCommandStore } from "../state/commandStore";

export function AppShell({ children }: { children: ReactNode }) {
  const backend = useCommandStore((s) => s.backend);
  const toast = useCommandStore((s) => s.toast);
  return <div className="app-shell">
    <Sidebar />
    <div className="workspace">
      <header className="topbar"><div><p className="eyebrow">Water Command Center V2</p><h1>Enterprise irrigation intelligence</h1></div><div className={`status-pill ${backend.status}`}>{backend.status}: {backend.detail}</div></header>
      {children}
      {toast ? <button className="toast" onClick={() => actions.dismissToast()}>{toast}</button> : null}
    </div>
  </div>;
}
