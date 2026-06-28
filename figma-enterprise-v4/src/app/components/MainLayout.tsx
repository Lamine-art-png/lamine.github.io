import { Outlet, NavLink } from "react-router";
import { CreditCard, HelpCircle, LogOut, Plus, Settings, Shield, UserCircle } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { OperatingStatusBar } from "./OperatingStatusBar";

export function MainLayout() {
  const { currentOrganization, currentWorkspace, logout } = useAuth();

  const operateItems = [
    { name: "Command Center", path: "/" },
    { name: "Field Queue", path: "/field-queue" },
    { name: "Tasks", path: "/tasks" },
    { name: "Decisions", path: "/operations" },
    { name: "Evidence", path: "/evidence" },
    { name: "Reports", path: "/reports" },
    { name: "Connectors", path: "/integrations" },
  ];

  const intelligenceItems = [
    { name: "Ask AGRO-AI", path: "/intelligence" },
    { name: "Readiness", path: "/readiness" },
    { name: "Exceptions", path: "/exceptions" },
  ];

  const workspaceItems = [
    { name: "Sources", path: "/sources" },
    { name: "Team", path: "/team" },
    { name: "Settings", path: "/settings" },
  ];

  const accountItems = [
    { name: "Profile", path: "/profile", icon: UserCircle },
    { name: "Billing", path: "/billing", icon: CreditCard },
    { name: "Security", path: "/security", icon: Shield },
    { name: "Support", path: "/support", icon: HelpCircle },
    { name: "Admin", path: "/admin", icon: Settings },
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
                Field operating room
              </div>
            </div>
          </div>
          <div className="mt-5 rounded-lg px-3 py-3" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
            <div className="text-[10px] font-semibold uppercase" style={{ color: "rgba(255,255,255,0.34)" }}>Workspace</div>
            <div className="mt-1 truncate text-[13px] font-medium" style={{ color: "white" }}>{currentWorkspace?.name || "Evaluation workspace"}</div>
            <div className="mt-1 truncate text-[11px]" style={{ color: "rgba(255,255,255,0.46)" }}>{currentOrganization?.name || "Organization"}</div>
          </div>
          <NavLink
            to="/"
            className="mt-3 flex h-9 items-center justify-center gap-2 rounded-lg text-[12px] font-semibold"
            style={{ background: "#DDEB8F", color: "#10231B" }}
          >
            <Plus className="h-3.5 w-3.5" />
            New operation
          </NavLink>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-5 overflow-y-auto">
          <NavSection title="Operate" items={operateItems} />
          <NavSection title="Intelligence" items={intelligenceItems} />
          <NavSection title="Workspace" items={workspaceItems} />
        </nav>

        <div className="space-y-2 px-3 pb-4">
          <NavLink
            to="/pricing"
            className="flex h-10 items-center justify-between rounded-md px-3 text-[12px] font-medium"
            style={({ isActive }) => ({
              background: isActive ? "#0B2A1F" : "rgba(255,255,255,0.04)",
              color: "rgba(255,255,255,0.78)",
              border: "1px solid rgba(255,255,255,0.07)",
            })}
          >
            <span>{currentOrganization?.plan === "network" ? "Network" : currentOrganization?.plan === "professional" ? "Professional" : "Free"}</span>
            <span style={{ color: "rgba(255,255,255,0.42)" }}>Plan</span>
          </NavLink>
          <div className="rounded-lg p-2" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
            <div className="px-2 pb-2 text-[11px]" style={{ color: "rgba(255,255,255,0.44)" }}>
              Account
            </div>
            <div className="space-y-1">
              {accountItems.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className="flex h-8 items-center gap-2 rounded-md px-2 text-[12px]"
                  style={({ isActive }) => ({
                    background: isActive ? "rgba(255,255,255,0.08)" : "transparent",
                    color: isActive ? "white" : "rgba(255,255,255,0.56)",
                  })}
                >
                  <item.icon className="h-3.5 w-3.5" />
                  {item.name}
                </NavLink>
              ))}
              <button
                type="button"
                onClick={logout}
                className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[12px] transition-colors hover:bg-white/10"
                style={{ color: "rgba(255,255,255,0.56)" }}
              >
                <LogOut className="h-3.5 w-3.5" />
                Log out
              </button>
            </div>
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
