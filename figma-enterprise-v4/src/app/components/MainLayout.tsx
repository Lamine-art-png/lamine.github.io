import { Outlet, NavLink } from "react-router";
import { LogOut } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { OperatingStatusBar } from "./OperatingStatusBar";

export function MainLayout() {
  const { currentOrganization, currentWorkspace, logout } = useAuth();

  const operateItems = [
    { name: "Command Center", path: "/" },
    { name: "Decisions", path: "/operations" },
    { name: "Evidence", path: "/evidence" },
    { name: "Reports", path: "/reports" },
    { name: "Connectors", path: "/integrations" },
  ];

  const intelligenceItems = [
    { name: "Automations", path: "/agents" },
    { name: "Ask AGRO-AI", path: "/intelligence" },
  ];

  const adminItems = [
    { name: "Sources", path: "/sources" },
    { name: "Admin", path: "/admin" },
  ];

  return (
    <div className="flex h-screen" style={{ background: "#F6F4EE" }}>
      <aside className="w-[280px] flex-shrink-0 flex flex-col" style={{ background: "#061D15" }}>
        <div className="px-6 pt-6 pb-5" style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg overflow-hidden flex items-center justify-center flex-shrink-0" style={{ background: "#16533C" }}>
              <ImageWithFallback src={logoImg} alt="AGRO-AI" className="w-full h-full object-contain" />
            </div>
            <div>
              <div className="text-white font-semibold text-[13px] tracking-tight leading-tight">AGRO-AI</div>
              <div className="text-[11px] leading-tight" style={{ color: "rgba(255,255,255,0.38)" }}>
                Water Intelligence OS
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-5 overflow-y-auto">
          <NavSection title="Operate" items={operateItems} />
          <NavSection title="Intelligence" items={intelligenceItems} />
          <NavSection title="Admin" items={adminItems} />
        </nav>

        <div className="px-3 pb-4">
          <div className="rounded-lg px-4 py-3" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: "rgba(255,255,255,0.28)" }}>
              {currentOrganization?.name || "Organization"}
            </div>
            <div className="space-y-1 text-[11px] leading-relaxed" style={{ color: "rgba(255,255,255,0.42)" }}>
              <div>Plan: <span style={{ color: "rgba(255,255,255,0.62)" }}>{currentOrganization?.plan || "free"}</span></div>
              <div>Status: <span style={{ color: "rgba(255,255,255,0.62)" }}>{currentOrganization?.subscription_status || "inactive"}</span></div>
              <div>Role: <span style={{ color: "rgba(255,255,255,0.62)" }}>{currentOrganization?.role || "member"}</span></div>
              <div>Workspace: <span style={{ color: "rgba(255,255,255,0.62)" }}>{currentWorkspace?.name || "Evaluation workspace"}</span></div>
            </div>
            <button
              type="button"
              onClick={logout}
              className="mt-3 flex h-8 w-full items-center justify-center gap-2 rounded-md text-[12px] font-medium transition-colors hover:bg-white/10"
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

function NavSection({ title, items }: { title: string; items: { name: string; path: string }[] }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-widest px-3 mb-1" style={{ color: "rgba(255,255,255,0.25)" }}>
        {title}
      </div>
      <div>
        {items.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            className="flex items-center px-3 rounded-md text-[13px] transition-colors"
            style={({ isActive }) => ({
              height: 44,
              background: isActive ? "#0B2A1F" : "transparent",
              color: isActive ? "white" : "rgba(255,255,255,0.52)",
              fontWeight: isActive ? 500 : 400,
              borderLeft: isActive ? "2px solid #1F7350" : "2px solid transparent",
            })}
          >
            {item.name}
          </NavLink>
        ))}
      </div>
    </div>
  );
}
