import { Outlet, NavLink } from "react-router";
import { CreditCard, HelpCircle, Lock, LogOut, Plus, Settings, Shield, UserCircle } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { OperatingStatusBar } from "./OperatingStatusBar";

type NavItem = { name: string; path: string; locked?: boolean; upgradeTo?: string; icon?: any };

const PLAN_LABELS: Record<string, string> = {
  free: "Free",
  professional: "Professional",
  team: "Team",
  network: "Network",
  enterprise: "Enterprise",
  pilot: "Free",
  pro: "Professional",
  waterops: "Professional",
  assurance_audit: "Professional",
  assurance: "Team",
};

function capabilityEnabled(entitlements: Record<string, unknown>, key: string, fallback: boolean) {
  const capabilities = entitlements.capabilities;
  if (!capabilities || typeof capabilities !== "object" || Array.isArray(capabilities)) return fallback;
  const value = (capabilities as Record<string, unknown>)[key];
  return value === true || value === "enabled" || value === "preview";
}

export function MainLayout() {
  const { currentOrganization, currentWorkspace, entitlements, logout } = useAuth();
  const { t } = useLocale();
  const canInviteTeam = capabilityEnabled(entitlements, "team.invite", Boolean(entitlements.can_invite_team));
  const canAccessAdminRequests = capabilityEnabled(entitlements, "admin.requests", Boolean(entitlements.can_access_admin_requests));
  const canGeneratePdf = capabilityEnabled(entitlements, "reports.pdf_export", Boolean(entitlements.can_generate_pdf));
  const currentPlanLabel = PLAN_LABELS[String(currentOrganization?.plan || "free").toLowerCase()] || "Free";

  const operateItems: NavItem[] = [
    { name: t("commandCenter"), path: "/" },
    { name: t("fieldQueue"), path: "/field-queue" },
    { name: t("tasks"), path: "/tasks" },
    { name: t("decisions"), path: "/operations" },
    { name: t("evidence"), path: "/evidence" },
    { name: t("reports"), path: "/reports", locked: !canGeneratePdf, upgradeTo: "professional" },
    { name: t("connectors"), path: "/integrations" },
  ];

  const intelligenceItems: NavItem[] = [
    { name: t("askAgroAi"), path: "/intelligence" },
    { name: t("readiness"), path: "/readiness" },
    { name: t("exceptions"), path: "/exceptions" },
  ];

  const workspaceItems: NavItem[] = [
    { name: t("sources"), path: "/sources" },
    { name: t("team"), path: "/team", locked: !canInviteTeam, upgradeTo: "team" },
    { name: t("settings"), path: "/settings" },
  ];

  const accountItems: NavItem[] = [
    { name: t("profile"), path: "/profile", icon: UserCircle },
    { name: t("billing"), path: "/billing", icon: CreditCard },
    { name: t("security"), path: "/security", icon: Shield },
    { name: t("support"), path: "/support", icon: HelpCircle },
    { name: t("requests"), path: "/admin/requests", icon: HelpCircle, locked: !canAccessAdminRequests, upgradeTo: "team" },
    { name: t("admin"), path: "/admin", icon: Settings },
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
              <div className="text-[11px] leading-tight" style={{ color: "rgba(255,255,255,0.38)" }}>{t("fieldOperatingRoom")}</div>
            </div>
          </div>
          <div className="mt-5 rounded-lg px-3 py-3" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
            <div className="text-[10px] font-semibold uppercase" style={{ color: "rgba(255,255,255,0.34)" }}>{t("workspace")}</div>
            <div className="mt-1 truncate text-[13px] font-medium" style={{ color: "white" }}>{currentWorkspace?.name || "Evaluation workspace"}</div>
            <div className="mt-1 truncate text-[11px]" style={{ color: "rgba(255,255,255,0.46)" }}>{currentOrganization?.name || "Organization"}</div>
          </div>
          <NavLink to="/" className="mt-3 flex h-9 items-center justify-center gap-2 rounded-lg text-[12px] font-semibold" style={{ background: "#DDEB8F", color: "#10231B" }}>
            <Plus className="h-3.5 w-3.5" /> {t("newOperation")}
          </NavLink>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-5 overflow-y-auto">
          <NavSection title={t("operate")} items={operateItems} />
          <NavSection title={t("intelligence")} items={intelligenceItems} />
          <NavSection title={t("workspace")} items={workspaceItems} />
        </nav>

        <div className="space-y-2 px-3 pb-4">
          <NavLink to="/pricing" className="flex h-10 items-center justify-between rounded-md px-3 text-[12px] font-medium" style={({ isActive }) => ({ background: isActive ? "#0B2A1F" : "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.78)", border: "1px solid rgba(255,255,255,0.07)" })}>
            <span>{currentPlanLabel}</span>
            <span style={{ color: "rgba(255,255,255,0.42)" }}>{t("plan")}</span>
          </NavLink>
          <div className="rounded-lg p-2" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
            <div className="px-2 pb-2 text-[11px]" style={{ color: "rgba(255,255,255,0.44)" }}>{t("account")}</div>
            <div className="space-y-1">
              {accountItems.map((item) => <AccountNavItem key={item.path} item={item} />)}
              <button type="button" onClick={logout} className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[12px] transition-colors hover:bg-white/10" style={{ color: "rgba(255,255,255,0.56)" }}>
                <LogOut className="h-3.5 w-3.5" /> {t("logout")}
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

function AccountNavItem({ item }: { item: NavItem }) {
  const Icon = item.icon;
  const target = item.locked ? `/pricing?upgrade=${item.upgradeTo || "professional"}` : item.path;
  return (
    <NavLink key={item.path} to={target} className="flex h-8 items-center gap-2 rounded-md px-2 text-[12px]" style={({ isActive }) => ({ background: isActive && !item.locked ? "rgba(255,255,255,0.08)" : "transparent", color: isActive && !item.locked ? "white" : "rgba(255,255,255,0.56)" })}>
      {Icon ? <Icon className="h-3.5 w-3.5" /> : null}
      <span className="min-w-0 flex-1 truncate">{item.name}</span>
      {item.locked ? <Lock className="h-3.5 w-3.5 opacity-70" /> : null}
    </NavLink>
  );
}

function NavSection({ title, items }: { title: string; items: NavItem[] }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-widest px-3 mb-1" style={{ color: "rgba(255,255,255,0.25)" }}>{title}</div>
      <div>
        {items.map((item) => {
          const target = item.locked ? `/pricing?upgrade=${item.upgradeTo || "professional"}` : item.path;
          return (
            <NavLink key={item.path} to={target} end={item.path === "/"} className="flex items-center px-3 rounded-md text-[13px] transition-colors" style={({ isActive }) => ({ height: 40, background: isActive && !item.locked ? "#0B2A1F" : "transparent", color: isActive && !item.locked ? "white" : "rgba(255,255,255,0.58)", fontWeight: isActive && !item.locked ? 500 : 400, borderLeft: isActive && !item.locked ? "2px solid #1F7350" : "2px solid transparent" })}>
              <span className="flex min-w-0 items-center gap-2"><span className="truncate">{item.name}</span>{item.locked ? <Lock className="h-3.5 w-3.5 opacity-70" /> : null}</span>
            </NavLink>
          );
        })}
      </div>
    </div>
  );
}
