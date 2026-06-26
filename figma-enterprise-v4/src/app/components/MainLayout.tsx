import { Outlet, NavLink } from "react-router";
import { LogOut } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { OperatingStatusBar } from "./OperatingStatusBar";

export function MainLayout() {
  const { currentOrganization, currentWorkspace, logout } = useAuth();

  const navItems = [
    { name: "Command Center", path: "/" },
    { name: "Decisions", path: "/operations" },
    { name: "Evidence", path: "/evidence" },
    { name: "Reports", path: "/reports" },
    { name: "Connectors", path: "/integrations" },
    { name: "Ask AGRO-AI", path: "/intelligence" },
    { name: "Settings", path: "/admin" },
  ];

  const plan = currentOrganization?.plan || "Free";
  const role = currentOrganization?.role || "Owner";
  const workspace = currentWorkspace?.name || "Demo workspace";

  return (
    <div className="flex h-screen" style={{ background: "#F6F4EE" }}>
      <aside className="w-[280px] flex-shrink-0 flex flex-col" style={{ background: "#061D15" }}>
        <div className="px-6 pt-6 pb-5" style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl overflow-hidden flex items-center justify-center flex-shrink-0" style={{ background: "#16533C" }}>
              <ImageWithFallback src={logoImg} alt="AGRO-AI" className="w-full h-full object-contain" />
            </div>
            <div>
              <div className="text-white font-semibold text-[13px] tracking-tight leading-tight">AGRO-AI</div>
              <div className="text-[11px] leading-tight" style={{ color: "rgba(255,255,255,0.42)" }}>
                Water Intelligence OS
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-5 overflow-y-auto">
          <div className="text-[10px] font-semibold uppercase tracking-widest px-3 mb-2" style={{ color: "rgba(255,255,255,0.28)" }}>
            Product
          </div>

          <div className="space-y-1">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                className="flex items-center px-3 rounded-lg text-[13px] transition-colors"
                style={({ isActive }) => ({
                  height: 43,
                  background: isActive ? "#0B2A1F" : "transparent",
                  color: isActive ? "white" : "rgba(255,255,255,0.56)",
                  fontWeight: isActive ? 600 : 400,
                  borderLeft: isActive ? "2px solid #9BD84B" : "2px solid transparent",
                })}
              >
                {item.name}
              </NavLink>
            ))}
          </div>
        </nav>

        <div className="px-3 pb-4">
          <div className="rounded-xl px-4 py-4" style={{ background: "rgba(255,255,255,0.045)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(255,255,255,0.3)" }}>
              Workspace
            </div>

            <div className="space-y-1.5 text-[11px] leading-relaxed" style={{ color: "rgba(255,255,255,0.46)" }}>
              <div>Plan: <span style={{ color: "rgba(255,255,255,0.72)" }}>{String(plan)}</span></div>
              <div>Role: <span style={{ color: "rgba(255,255,255,0.72)" }}>{String(role)}</span></div>
              <div>Mode: <span style={{ color: "rgba(255,255,255,0.72)" }}>Demo / evaluation</span></div>
              <div className="truncate">Workspace: <span style={{ color: "rgba(255,255,255,0.72)" }}>{String(workspace)}</span></div>
            </div>

            <button
              type="button"
              onClick={logout}
              className="mt-4 flex h-8 w-full items-center justify-center gap-2 rounded-md text-[12px] font-medium transition-colors hover:bg-white/10"
              style={{ color: "rgba(255,255,255,0.72)" }}
            >
              <LogOut className="w-3.5 h-3.5" />
              Logout
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <OperatingStatusBar />
        <Outlet />
      </main>
    </div>
  );
}
