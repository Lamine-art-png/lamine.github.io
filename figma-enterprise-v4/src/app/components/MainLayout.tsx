import { useEffect, useState } from "react";
import { Outlet, NavLink, useLocation } from "react-router";
import { CreditCard, HelpCircle, Lock, LogOut, Menu, Plus, Settings, Shield, UserCircle, X } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { OperatingStatusBar } from "./OperatingStatusBar";
import { ProductTour, replayProductTour } from "./ProductTour";
import { UploadStatusToast } from "./UploadStatusToast";

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
const PLAN_COPY_VALUES = Array.from(new Set(Object.values(PLAN_LABELS)));

function copyNamespacesForPath(pathname: string): string[] {
  if (pathname === "/operations") return ["operations", "shared"];
  if (["/", "/field-queue", "/tasks"].includes(pathname)) return ["overview", "shared"];
  if (["/readiness", "/fields", "/exceptions", "/decision-workbench", "/report-factory"].includes(pathname)) return ["cockpit", "shared"];
  return [];
}

const TOUR_TARGETS: Record<string, string> = {
  "/": "command-center",
  "/integrations": "connectors",
  "/evidence": "evidence",
  "/intelligence": "ask-agro-ai",
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
  const location = useLocation();
  const { tx } = usePortalCopy(copyNamespacesForPath(location.pathname), PLAN_COPY_VALUES);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const currentPlan = String(currentOrganization?.plan || "free").toLowerCase();
  const canInviteTeam = capabilityEnabled(entitlements, "team.invite", Boolean(entitlements.can_invite_team));
  const canAccessAdminRequests = capabilityEnabled(entitlements, "admin.requests", Boolean(entitlements.can_access_admin_requests));
  const canGeneratePdf = capabilityEnabled(entitlements, "reports.pdf_export", Boolean(entitlements.can_generate_pdf));
  const canAskAgroAi = capabilityEnabled(entitlements, "intelligence.ask", !["free", "pilot"].includes(currentPlan));
  const currentPlanLabel = PLAN_LABELS[currentPlan] || "Free";

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
    { name: t("askAgroAi"), path: "/intelligence", locked: !canAskAgroAi, upgradeTo: "professional" },
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

  const allPrimaryItems = [...operateItems, ...intelligenceItems, ...workspaceItems, ...accountItems];
  const activeLabel = allPrimaryItems.find((item) => item.path === location.pathname)?.name || "AGRO-AI";

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [mobileNavOpen]);

  const sidebarProps = {
    currentWorkspaceName: currentWorkspace?.name || "Evaluation workspace",
    currentOrganizationName: currentOrganization?.name || "Organization",
    currentPlanLabel: tx(currentPlanLabel),
    operateItems,
    intelligenceItems,
    workspaceItems,
    accountItems,
    onNavigate: () => setMobileNavOpen(false),
    onLogout: logout,
    t,
  };

  return (
    <div className="flex h-[100dvh] w-full min-w-0 overflow-hidden" style={{ background: "#F6F4EE" }} data-portal-shell>
      <aside className="hidden w-[280px] flex-shrink-0 flex-col md:flex" style={{ background: "#061D15" }}>
        <SidebarContent {...sidebarProps} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header
          className="z-40 flex h-14 flex-shrink-0 items-center gap-3 px-3 md:hidden"
          style={{ background: "#061D15", borderBottom: "1px solid rgba(255,255,255,0.08)" }}
          data-mobile-portal-header
        >
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl"
            style={{ color: "white", background: "rgba(255,255,255,0.07)" }}
            aria-label="Open navigation"
            aria-expanded={mobileNavOpen}
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <div className="h-8 w-8 flex-shrink-0 overflow-hidden rounded-lg" style={{ background: "#16533C" }}>
              <ImageWithFallback src={logoImg} alt="AGRO-AI" className="h-full w-full object-contain" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-[10px] font-semibold uppercase tracking-[0.14em]" style={{ color: "rgba(255,255,255,0.42)" }}>AGRO-AI</div>
              <div className="truncate text-[13px] font-semibold" style={{ color: "white" }}>{activeLabel}</div>
            </div>
          </div>
          <div className="max-w-[34vw] truncate rounded-full px-2.5 py-1 text-[10px] font-medium" style={{ color: "#DDEB8F", background: "rgba(221,235,143,0.09)" }}>
            {currentWorkspace?.name || t("workspace")}
          </div>
        </header>

        <main className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto" data-portal-content>
          <OperatingStatusBar />
          <Outlet />
        </main>
      </div>

      {mobileNavOpen ? (
        <div className="fixed inset-0 z-[100] md:hidden" data-mobile-navigation>
          <button
            type="button"
            className="absolute inset-0 bg-black/50 backdrop-blur-[1px]"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close navigation"
          />
          <aside
            className="absolute inset-y-0 left-0 flex w-[min(86vw,320px)] flex-col overflow-hidden shadow-2xl"
            style={{ background: "#061D15", paddingTop: "env(safe-area-inset-top)", paddingBottom: "env(safe-area-inset-bottom)" }}
          >
            <button
              type="button"
              onClick={() => setMobileNavOpen(false)}
              className="absolute right-3 top-3 z-10 flex h-10 w-10 items-center justify-center rounded-xl"
              style={{ color: "white", background: "rgba(255,255,255,0.08)" }}
              aria-label="Close navigation"
            >
              <X className="h-5 w-5" />
            </button>
            <SidebarContent {...sidebarProps} mobile />
          </aside>
        </div>
      ) : null}

      <UploadStatusToast />
      <ProductTour />
    </div>
  );
}

function SidebarContent({
  currentWorkspaceName,
  currentOrganizationName,
  currentPlanLabel,
  operateItems,
  intelligenceItems,
  workspaceItems,
  accountItems,
  onNavigate,
  onLogout,
  t,
  mobile = false,
}: {
  currentWorkspaceName: string;
  currentOrganizationName: string;
  currentPlanLabel: string;
  operateItems: NavItem[];
  intelligenceItems: NavItem[];
  workspaceItems: NavItem[];
  accountItems: NavItem[];
  onNavigate: () => void;
  onLogout: () => void;
  t: (key: string) => string;
  mobile?: boolean;
}) {
  return (
    <>
      <div className={mobile ? "px-5 pb-4 pt-5" : "px-6 pb-5 pt-6"} style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
        <div className="flex items-center gap-3 pr-10">
          <div className="h-8 w-8 flex-shrink-0 overflow-hidden rounded-lg" style={{ background: "#16533C" }}>
            <ImageWithFallback src={logoImg} alt="AGRO-AI" className="h-full w-full object-contain" />
          </div>
          <div className="min-w-0">
            <div className="text-[13px] font-semibold leading-tight tracking-tight text-white">AGRO-AI</div>
            <div className="truncate text-[11px] leading-tight" style={{ color: "rgba(255,255,255,0.38)" }}>{t("fieldOperatingRoom")}</div>
          </div>
        </div>
        <div className="mt-5 rounded-xl px-3 py-3" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
          <div className="text-[10px] font-semibold uppercase" style={{ color: "rgba(255,255,255,0.34)" }}>{t("workspace")}</div>
          <div className="mt-1 truncate text-[13px] font-medium text-white">{currentWorkspaceName}</div>
          <div className="mt-1 truncate text-[11px]" style={{ color: "rgba(255,255,255,0.46)" }}>{currentOrganizationName}</div>
        </div>
        <NavLink to="/" onClick={onNavigate} className="mt-3 flex h-11 items-center justify-center gap-2 rounded-xl text-[13px] font-semibold" style={{ background: "#DDEB8F", color: "#10231B" }}>
          <Plus className="h-4 w-4" /> {t("newOperation")}
        </NavLink>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4" style={{ WebkitOverflowScrolling: "touch" }}>
        <NavSection title={t("operate")} items={operateItems} onNavigate={onNavigate} />
        <NavSection title={t("intelligence")} items={intelligenceItems} onNavigate={onNavigate} />
        <NavSection title={t("workspace")} items={workspaceItems} onNavigate={onNavigate} />
      </nav>

      <div className="space-y-2 px-3 pb-4">
        <NavLink to="/pricing" onClick={onNavigate} className="flex h-11 items-center justify-between rounded-xl px-3 text-[12px] font-medium" style={({ isActive }) => ({ background: isActive ? "#0B2A1F" : "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.78)", border: "1px solid rgba(255,255,255,0.07)" })}>
          <span>{currentPlanLabel}</span>
          <span style={{ color: "rgba(255,255,255,0.42)" }}>{t("plan")}</span>
        </NavLink>
        <div className="rounded-xl p-2" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
          <div className="px-2 pb-2 text-[11px]" style={{ color: "rgba(255,255,255,0.44)" }}>{t("account")}</div>
          <div className="space-y-1">
            {accountItems.map((item) => <AccountNavItem key={item.path} item={item} onNavigate={onNavigate} />)}
            <button type="button" onClick={() => { onNavigate(); replayProductTour(); }} className="flex h-10 w-full items-center gap-2 rounded-lg px-2 text-left text-[12px] transition-colors hover:bg-white/10" style={{ color: "rgba(255,255,255,0.62)" }}>
              <HelpCircle className="h-4 w-4" /> Product tour
            </button>
            <button type="button" onClick={() => { onNavigate(); onLogout(); }} className="flex h-10 w-full items-center gap-2 rounded-lg px-2 text-left text-[12px] transition-colors hover:bg-white/10" style={{ color: "rgba(255,255,255,0.62)" }}>
              <LogOut className="h-4 w-4" /> {t("logout")}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function AccountNavItem({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  const Icon = item.icon;
  return (
    <NavLink key={item.path} to={item.path} onClick={onNavigate} className="flex h-10 items-center gap-2 rounded-lg px-2 text-[12px]" style={({ isActive }) => ({ background: isActive ? "rgba(255,255,255,0.08)" : "transparent", color: isActive ? "white" : "rgba(255,255,255,0.62)" })}>
      {Icon ? <Icon className="h-4 w-4" /> : null}
      <span className="min-w-0 flex-1 truncate">{item.name}</span>
      {item.locked ? <Lock className="h-3.5 w-3.5 opacity-70" /> : null}
    </NavLink>
  );
}

function NavSection({ title, items, onNavigate }: { title: string; items: NavItem[]; onNavigate: () => void }) {
  return (
    <div>
      <div className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.25)" }}>{title}</div>
      <div>
        {items.map((item) => (
          <NavLink key={item.path} to={item.path} onClick={onNavigate} end={item.path === "/"} data-tour={TOUR_TARGETS[item.path]} className="flex h-11 items-center rounded-lg px-3 text-[13px] transition-colors" style={({ isActive }) => ({ background: isActive ? "#0B2A1F" : "transparent", color: isActive ? "white" : "rgba(255,255,255,0.62)", fontWeight: isActive ? 500 : 400, borderLeft: isActive ? "2px solid #1F7350" : "2px solid transparent" })}>
            <span className="flex min-w-0 items-center gap-2"><span className="truncate">{item.name}</span>{item.locked ? <Lock className="h-3.5 w-3.5 opacity-70" /> : null}</span>
          </NavLink>
        ))}
      </div>
    </div>
  );
}
