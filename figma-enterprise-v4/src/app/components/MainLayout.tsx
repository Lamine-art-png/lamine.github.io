import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import {
  AlertTriangle,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  CreditCard,
  FileSearch,
  FileText,
  FolderOpen,
  Gauge,
  HelpCircle,
  LayoutDashboard,
  ListTodo,
  Radio,
  Lock,
  LogOut,
  Menu,
  Plus,
  Settings,
  Shield,
  SlidersHorizontal,
  UserCircle,
  Users,
  X,
  PlugZap,
} from "lucide-react";
import { useAuth, type Workspace } from "../auth/AuthProvider";
import { SyncCenter } from "../fieldIntelligence/SyncCenter";
import { StagingBanner } from "./StagingBanner";
import { useLocale } from "../hooks/useLocale";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { OperatingStatusBar } from "./OperatingStatusBar";
import { ProductTour, replayProductTour } from "./ProductTour";
import { UploadStatusToast } from "./UploadStatusToast";

const sidebarPreferenceKey = "agroai_sidebar_collapsed_v1";

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

function readSidebarPreference() {
  try {
    return localStorage.getItem(sidebarPreferenceKey) === "true";
  } catch {
    return false;
  }
}

function operationLimitLabel(plan: string, entitlements: Record<string, unknown>) {
  const accessProfile = String(entitlements.access_profile || "customer");
  if (plan === "enterprise" || accessProfile === "internal" || accessProfile === "demo") return "Custom";
  const value = Number(entitlements.max_workspaces);
  return Number.isFinite(value) && value > 0 ? String(value) : "—";
}

export function MainLayout() {
  const {
    currentOrganization,
    currentWorkspace,
    workspaces,
    selectWorkspace,
    entitlements,
    platformAdmin,
    platformDeveloper,
    logout,
  } = useAuth();
  const { t } = useLocale();
  const location = useLocation();
  const { tx } = usePortalCopy(copyNamespacesForPath(location.pathname), PLAN_COPY_VALUES);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarPreference);
  const currentPlan = String(currentOrganization?.plan || "free").toLowerCase();
  const canInviteTeam = capabilityEnabled(entitlements, "team.invite", Boolean(entitlements.can_invite_team));
  const canAccessAdminRequests = capabilityEnabled(entitlements, "admin.requests", Boolean(entitlements.can_access_admin_requests));
  const canGeneratePdf = capabilityEnabled(entitlements, "reports.pdf_export", Boolean(entitlements.can_generate_pdf));
  const canAskAgroAi = capabilityEnabled(entitlements, "intelligence.ask", !["free", "pilot"].includes(currentPlan));
  const canFieldIntelligence = capabilityEnabled(entitlements, "field_intelligence.capture", true);
  const currentPlanLabel = PLAN_LABELS[currentPlan] || "Free";
  const organizationWorkspaces = useMemo(
    () => currentOrganization?.id
      ? workspaces.filter((workspace) => !workspace.organization_id || workspace.organization_id === currentOrganization.id)
      : workspaces,
    [currentOrganization?.id, workspaces],
  );
  const workspaceLimit = operationLimitLabel(currentPlan, entitlements);

  const operateItems: NavItem[] = [
    { name: t("commandCenter"), path: "/", icon: LayoutDashboard },
    { name: t("fieldQueue"), path: "/field-queue", icon: ListTodo },
    { name: t("fieldIntelligence"), path: "/field-intelligence", icon: Radio, locked: !canFieldIntelligence, upgradeTo: "professional" },
    { name: t("tasks"), path: "/tasks", icon: ClipboardCheck },
    { name: t("decisions"), path: "/operations", icon: SlidersHorizontal },
    { name: t("evidence"), path: "/evidence", icon: FileSearch },
    { name: t("reports"), path: "/reports", icon: FileText, locked: !canGeneratePdf, upgradeTo: "professional" },
    { name: t("connectors"), path: "/integrations", icon: PlugZap },
  ];

  const intelligenceItems: NavItem[] = [
    { name: t("askAgroAi"), path: "/intelligence", icon: BrainCircuit, locked: !canAskAgroAi, upgradeTo: "professional" },
    { name: t("readiness"), path: "/readiness", icon: Gauge },
    { name: t("exceptions"), path: "/exceptions", icon: AlertTriangle },
  ];

  const workspaceItems: NavItem[] = [
    { name: t("sources"), path: "/sources", icon: FolderOpen },
    { name: t("team"), path: "/team", icon: Users, locked: !canInviteTeam, upgradeTo: "team" },
    { name: t("settings"), path: "/settings", icon: Settings },
  ];

  const accountItems: NavItem[] = [
    { name: t("profile"), path: "/profile", icon: UserCircle },
    { name: t("billing"), path: "/billing", icon: CreditCard },
    { name: t("security"), path: "/security", icon: Shield },
    { name: t("support"), path: "/support", icon: HelpCircle },
    { name: t("requests"), path: "/admin/requests", icon: HelpCircle, locked: !canAccessAdminRequests, upgradeTo: "team" },
    { name: t("admin"), path: "/admin", icon: Settings },
    ...(platformDeveloper ? [
      { name: "Developers/API", path: "/developers/api", icon: Shield },
    ] : []),
    ...(platformAdmin ? [
      { name: "Customer accounts", path: "/admin/customers", icon: Users },
      { name: "Platform API review", path: "/admin/platform-api", icon: Shield },
    ] : []),
  ];

  const allPrimaryItems = [...operateItems, ...intelligenceItems, ...workspaceItems, ...accountItems];
  const activeLabel = location.pathname === "/operations/new"
    ? t("newOperation")
    : allPrimaryItems.find((item) => item.path === location.pathname)?.name || "AGRO-AI";

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

  useEffect(() => {
    try {
      localStorage.setItem(sidebarPreferenceKey, String(sidebarCollapsed));
    } catch {
      // Desktop layout preference is best effort.
    }
  }, [sidebarCollapsed]);

  const sidebarProps = {
    currentWorkspace,
    workspaces: organizationWorkspaces,
    currentOrganizationName: currentOrganization?.name || "Organization",
    currentPlanLabel: tx(currentPlanLabel),
    workspaceLimit,
    operateItems,
    intelligenceItems,
    workspaceItems,
    accountItems,
    onSelectWorkspace: selectWorkspace,
    onNavigate: () => setMobileNavOpen(false),
    onLogout: logout,
    t,
  };

  return (
    <div className="flex h-[100dvh] w-full min-w-0 overflow-hidden" style={{ background: "#F6F4EE" }} data-portal-shell>
      <aside
        className="relative hidden flex-shrink-0 flex-col transition-[width] duration-200 ease-out md:flex"
        style={{ background: "#061D15", width: sidebarCollapsed ? 76 : 280 }}
        data-desktop-sidebar
        data-collapsed={sidebarCollapsed ? "true" : "false"}
      >
        <SidebarContent
          {...sidebarProps}
          collapsed={sidebarCollapsed}
          onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
        />
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
          <StagingBanner />
          <div className="flex justify-end px-3 pt-2" data-sync-center>
            <SyncCenter />
          </div>
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
  currentWorkspace,
  workspaces,
  currentOrganizationName,
  currentPlanLabel,
  workspaceLimit,
  operateItems,
  intelligenceItems,
  workspaceItems,
  accountItems,
  onSelectWorkspace,
  onNavigate,
  onLogout,
  onToggleCollapsed,
  t,
  mobile = false,
  collapsed = false,
}: {
  currentWorkspace: Workspace | null;
  workspaces: Workspace[];
  currentOrganizationName: string;
  currentPlanLabel: string;
  workspaceLimit: string;
  operateItems: NavItem[];
  intelligenceItems: NavItem[];
  workspaceItems: NavItem[];
  accountItems: NavItem[];
  onSelectWorkspace: (workspaceId: string) => void;
  onNavigate: () => void;
  onLogout: () => void;
  onToggleCollapsed?: () => void;
  t: (key: string) => string;
  mobile?: boolean;
  collapsed?: boolean;
}) {
  const isCollapsed = collapsed && !mobile;
  return (
    <>
      <div className={mobile ? "px-5 pb-4 pt-5" : isCollapsed ? "px-2 pb-4 pt-4" : "px-6 pb-5 pt-6"} style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
        <div className={isCollapsed ? "flex flex-col items-center gap-3" : "flex items-center gap-3"}>
          <div className="h-8 w-8 flex-shrink-0 overflow-hidden rounded-lg" style={{ background: "#16533C" }} title="AGRO-AI">
            <ImageWithFallback src={logoImg} alt="AGRO-AI" className="h-full w-full object-contain" />
          </div>
          {!isCollapsed ? (
            <div className="min-w-0 flex-1 pr-8">
              <div className="text-[13px] font-semibold leading-tight tracking-tight text-white">AGRO-AI</div>
              <div className="truncate text-[11px] leading-tight" style={{ color: "rgba(255,255,255,0.38)" }}>{t("fieldOperatingRoom")}</div>
            </div>
          ) : null}
          {!mobile && onToggleCollapsed ? (
            <button
              type="button"
              onClick={onToggleCollapsed}
              className={isCollapsed ? "flex h-9 w-9 items-center justify-center rounded-lg" : "absolute right-3 top-4 flex h-9 w-9 items-center justify-center rounded-lg"}
              style={{ color: "rgba(255,255,255,0.68)", background: "rgba(255,255,255,0.06)" }}
              aria-label={isCollapsed ? "Open sidebar" : "Close sidebar"}
              title={isCollapsed ? "Open sidebar" : "Close sidebar"}
            >
              {isCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </button>
          ) : null}
        </div>

        {!isCollapsed ? (
          <div className="mt-5 rounded-xl px-3 py-3" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
            <div className="flex items-center justify-between gap-2">
              <div className="text-[10px] font-semibold uppercase" style={{ color: "rgba(255,255,255,0.34)" }}>Operation</div>
              <div className="text-[10px]" style={{ color: "rgba(255,255,255,0.38)" }}>{workspaces.length}/{workspaceLimit}</div>
            </div>
            <select
              value={currentWorkspace?.id || ""}
              onChange={(event) => onSelectWorkspace(event.target.value)}
              className="mt-2 h-9 w-full min-w-0 rounded-lg px-2 text-[12px] font-medium outline-none"
              style={{ color: "white", background: "#0B2A1F", border: "1px solid rgba(255,255,255,0.09)" }}
              aria-label="Switch operation"
            >
              {workspaces.length ? workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>{workspace.name || "Untitled operation"}</option>
              )) : <option value="">No operation yet</option>}
            </select>
            <div className="mt-2 truncate text-[11px]" style={{ color: "rgba(255,255,255,0.46)" }}>{currentOrganizationName}</div>
          </div>
        ) : (
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="mx-auto mt-4 flex h-10 w-10 items-center justify-center rounded-xl"
            style={{ color: "#DDEB8F", background: "rgba(221,235,143,0.08)", border: "1px solid rgba(221,235,143,0.13)" }}
            title={currentWorkspace?.name || "Current operation"}
            aria-label={`Current operation: ${currentWorkspace?.name || "none"}`}
          >
            <FolderOpen className="h-[18px] w-[18px]" />
          </button>
        )}

        <NavLink
          to="/operations/new"
          onClick={onNavigate}
          className={isCollapsed
            ? "mx-auto mt-3 flex h-11 w-11 items-center justify-center rounded-xl"
            : "mt-3 flex h-11 items-center justify-center gap-2 rounded-xl text-[13px] font-semibold"}
          style={{ background: "#DDEB8F", color: "#10231B" }}
          title={isCollapsed ? t("newOperation") : undefined}
          aria-label={t("newOperation")}
          data-new-operation
        >
          <Plus className="h-4 w-4" /> {!isCollapsed ? t("newOperation") : null}
        </NavLink>
      </div>

      <nav className={isCollapsed ? "flex-1 space-y-4 overflow-y-auto px-2 py-4" : "flex-1 space-y-5 overflow-y-auto px-3 py-4"} style={{ WebkitOverflowScrolling: "touch" }}>
        <NavSection title={t("operate")} items={operateItems} onNavigate={onNavigate} collapsed={isCollapsed} />
        <NavSection title={t("intelligence")} items={intelligenceItems} onNavigate={onNavigate} collapsed={isCollapsed} />
        <NavSection title={t("workspace")} items={workspaceItems} onNavigate={onNavigate} collapsed={isCollapsed} />
      </nav>

      <div className={isCollapsed ? "space-y-2 px-2 pb-4" : "space-y-2 px-3 pb-4"}>
        <NavLink
          to="/pricing"
          onClick={onNavigate}
          className={isCollapsed ? "flex h-11 items-center justify-center rounded-xl" : "flex h-11 items-center justify-between rounded-xl px-3 text-[12px] font-medium"}
          style={({ isActive }) => ({ background: isActive ? "#0B2A1F" : "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.78)", border: "1px solid rgba(255,255,255,0.07)" })}
          title={isCollapsed ? `${currentPlanLabel} plan` : undefined}
        >
          {isCollapsed ? <CreditCard className="h-4 w-4" /> : <><span>{currentPlanLabel}</span><span style={{ color: "rgba(255,255,255,0.42)" }}>{t("plan")}</span></>}
        </NavLink>
        <div className={isCollapsed ? "rounded-xl p-1" : "rounded-xl p-2"} style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
          {!isCollapsed ? <div className="px-2 pb-2 text-[11px]" style={{ color: "rgba(255,255,255,0.44)" }}>{t("account")}</div> : null}
          <div className="space-y-1">
            {accountItems.map((item) => <AccountNavItem key={item.path} item={item} onNavigate={onNavigate} collapsed={isCollapsed} />)}
            <button type="button" onClick={() => { onNavigate(); replayProductTour(); }} className={isCollapsed ? "flex h-10 w-full items-center justify-center rounded-lg" : "flex h-10 w-full items-center gap-2 rounded-lg px-2 text-left text-[12px] transition-colors hover:bg-white/10"} style={{ color: "rgba(255,255,255,0.62)" }} title={isCollapsed ? "Product tour" : undefined}>
              <HelpCircle className="h-4 w-4" /> {!isCollapsed ? "Product tour" : null}
            </button>
            <button type="button" onClick={() => { onNavigate(); onLogout(); }} className={isCollapsed ? "flex h-10 w-full items-center justify-center rounded-lg" : "flex h-10 w-full items-center gap-2 rounded-lg px-2 text-left text-[12px] transition-colors hover:bg-white/10"} style={{ color: "rgba(255,255,255,0.62)" }} title={isCollapsed ? t("logout") : undefined}>
              <LogOut className="h-4 w-4" /> {!isCollapsed ? t("logout") : null}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function AccountNavItem({ item, onNavigate, collapsed = false }: { item: NavItem; onNavigate: () => void; collapsed?: boolean }) {
  const Icon = item.icon;
  return (
    <NavLink
      key={item.path}
      to={item.path}
      onClick={onNavigate}
      className={collapsed ? "flex h-10 items-center justify-center rounded-lg" : "flex h-10 items-center gap-2 rounded-lg px-2 text-[12px]"}
      style={({ isActive }) => ({ background: isActive ? "rgba(255,255,255,0.08)" : "transparent", color: isActive ? "white" : "rgba(255,255,255,0.62)" })}
      title={collapsed ? item.name : undefined}
      aria-label={item.name}
    >
      {Icon ? <Icon className="h-4 w-4" /> : null}
      {!collapsed ? <span className="min-w-0 flex-1 truncate">{item.name}</span> : null}
      {item.locked && !collapsed ? <Lock className="h-3.5 w-3.5 opacity-70" /> : null}
    </NavLink>
  );
}

function NavSection({ title, items, onNavigate, collapsed = false }: { title: string; items: NavItem[]; onNavigate: () => void; collapsed?: boolean }) {
  return (
    <div>
      {!collapsed ? <div className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.25)" }}>{title}</div> : null}
      <div className={collapsed ? "space-y-1" : ""}>
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={onNavigate}
              end={item.path === "/"}
              data-tour={TOUR_TARGETS[item.path]}
              className={collapsed ? "flex h-11 items-center justify-center rounded-lg transition-colors" : "flex h-11 items-center rounded-lg px-3 text-[13px] transition-colors"}
              style={({ isActive }) => ({ background: isActive ? "#0B2A1F" : "transparent", color: isActive ? "white" : "rgba(255,255,255,0.62)", fontWeight: isActive ? 500 : 400, borderLeft: !collapsed && isActive ? "2px solid #1F7350" : "2px solid transparent" })}
              title={collapsed ? item.name : undefined}
              aria-label={item.name}
            >
              {collapsed ? (
                <span className="relative"><Icon className="h-[18px] w-[18px]" />{item.locked ? <Lock className="absolute -bottom-1 -right-1 h-2.5 w-2.5" /> : null}</span>
              ) : (
                <span className="flex min-w-0 items-center gap-2.5"><Icon className="h-4 w-4 flex-shrink-0" /><span className="truncate">{item.name}</span>{item.locked ? <Lock className="h-3.5 w-3.5 opacity-70" /> : null}</span>
              )}
            </NavLink>
          );
        })}
      </div>
    </div>
  );
}
