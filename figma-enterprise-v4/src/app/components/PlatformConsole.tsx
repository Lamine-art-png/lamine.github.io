import {
  Activity,
  ArrowRight,
  BookOpen,
  Boxes,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Code2,
  Copy,
  CreditCard,
  ExternalLink,
  FileClock,
  Gauge,
  Globe2,
  KeyRound,
  Layers3,
  LifeBuoy,
  Loader2,
  LockKeyhole,
  Menu,
  MoreHorizontal,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  ServerCog,
  Settings2,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Trash2,
  Webhook,
  X,
  Zap,
} from "lucide-react";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Navigate, NavLink, useLocation, useNavigate } from "react-router";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";


type UnknownRecord = Record<string, any>;
type Project = {
  id: string;
  name: string;
  slug: string;
  environment: "test" | "live" | string;
  status: string;
  created_at?: string;
  updated_at?: string;
  default_rate_limit_policy?: UnknownRecord;
};
type ServiceAccount = {
  id: string;
  api_project_id: string;
  name: string;
  description?: string;
  status: string;
  scopes: string[];
  created_at?: string;
};
type ApiKey = {
  id: string;
  api_project_id: string;
  service_account_id: string;
  name: string;
  status: string;
  environment: string;
  fingerprint: string;
  key_prefix: string;
  scopes?: string[];
  expires_at?: string;
  last_used_at?: string;
  created_at?: string;
};
type Overview = {
  program?: string;
  enrollment_status?: string;
  allowed_environments?: string[];
  sections?: Record<string, boolean>;
  limits?: Record<string, number>;
};
type PlatformState = {
  overview?: Overview;
  projects: Project[];
  serviceAccounts: ServiceAccount[];
  keys: ApiKey[];
  usage: UnknownRecord[];
  requestLogs: UnknownRecord[];
  webhooks: UnknownRecord[];
  billing?: UnknownRecord;
  liveAccess: UnknownRecord[];
  support: UnknownRecord[];
};
type PlaygroundResult = {
  request_id?: string;
  latency_ms?: number;
  credit_cost?: number;
  request?: UnknownRecord;
  response?: { status?: number; body?: unknown };
  code?: Record<string, string>;
  execution_mode?: string;
};
type PlatformContextValue = {
  state: PlatformState;
  loading: boolean;
  error: string;
  selectedProjectId: string;
  selectedProject?: Project;
  setSelectedProjectId: (id: string) => void;
  refresh: () => Promise<void>;
  secret: string;
  secretTitle: string;
  revealSecret: (title: string, value: string) => void;
  clearSecret: () => void;
};

const PlatformContext = createContext<PlatformContextValue | null>(null);

const DEFAULT_SCOPES = [
  "projects:read",
  "fields:read",
  "sources:read",
  "observations:read",
  "recommendations:read",
  "reports:read",
  "jobs:read",
  "usage:read",
  "request_logs:read",
  "webhooks:read",
];

const NAV = [
  ["/home", "Home", Gauge],
  ["/projects", "Projects", Boxes],
  ["/service-accounts", "Service accounts", ServerCog],
  ["/api-keys", "API keys", KeyRound],
  ["/playground", "Playground", TerminalSquare],
  ["/usage", "Usage", Activity],
  ["/logs", "Logs", FileClock],
  ["/webhooks", "Webhooks", Webhook],
  ["/billing", "Billing", CreditCard],
  ["/docs", "Documentation", BookOpen],
  ["/live-access", "Live access", ShieldCheck],
  ["/support", "Support", LifeBuoy],
  ["/settings", "Settings", Settings2],
] as const;

const PLAYGROUND_OPERATIONS = [
  ["sandbox_summary", "Sandbox summary", "Inspect the deterministic project fixture."],
  ["list_fields", "List fields", "Return synthetic fields using the public API response shape."],
  ["get_field", "Retrieve a field", "Read one project-scoped synthetic field."],
  ["list_observations", "List observations", "Inspect measurements and provenance."],
  ["list_recommendations", "List recommendations", "Review advisory-only recommendations."],
  ["list_reports", "List reports", "Inspect generated synthetic report artifacts."],
  ["list_jobs", "List jobs", "Inspect deterministic ingestion jobs."],
] as const;

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function rows(value: unknown, key: string): UnknownRecord[] {
  const source = record(value)[key];
  return Array.isArray(source) ? source : [];
}

function platformHost() {
  return window.location.hostname.toLowerCase() === "platform.agroai-pilot.com";
}

function platformPath(path: string) {
  return `${platformHost() ? "" : "/platform"}${path}`;
}

function relativeRoute(pathname: string) {
  const route = pathname.replace(/^\/platform(?=\/|$)/, "") || "/home";
  return route === "/" ? "/home" : route;
}

function formatDate(value?: string) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function statusTone(status?: string) {
  const normalized = String(status || "").toLowerCase();
  if (["active", "ready", "approved", "succeeded"].includes(normalized)) return "border-[#B8D3AF] bg-[#F0F8EB] text-[#285A35]";
  if (["submitted", "pending", "processing", "queued"].includes(normalized)) return "border-[#E4D6A8] bg-[#FFF9E8] text-[#7B5A13]";
  if (["disabled", "revoked", "failed", "suspended"].includes(normalized)) return "border-[#E4B9AE] bg-[#FFF2EE] text-[#8A3528]";
  return "border-[#D7DED2] bg-[#F5F7F3] text-[#5C6960]";
}

function StatusPill({ status }: { status?: string }) {
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold capitalize ${statusTone(status)}`}>{status || "unknown"}</span>;
}

function PageHeader({ eyebrow, title, body, action }: { eyebrow?: string; title: string; body?: string; action?: ReactNode }) {
  return (
    <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-3xl">
        {eyebrow ? <div className="text-[11px] font-bold uppercase tracking-[0.19em] text-[#4E725D]">{eyebrow}</div> : null}
        <h1 className="mt-2 text-[30px] font-semibold tracking-[-0.035em] text-[#10231B] md:text-[38px]">{title}</h1>
        {body ? <p className="mt-3 max-w-2xl text-[14px] leading-7 text-[#65736A]">{body}</p> : null}
      </div>
      {action}
    </header>
  );
}

function Surface({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-[#D8DED3] bg-[#FFFDF8] shadow-[0_18px_50px_rgba(18,48,32,0.055)] ${className}`}>{children}</section>;
}

function EmptyState({ icon: Icon = Boxes, title, body, action }: { icon?: typeof Boxes; title: string; body: string; action?: ReactNode }) {
  return (
    <div className="flex min-h-[240px] flex-col items-center justify-center px-6 py-10 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-[#D8DED3] bg-[#F5F7F2] text-[#315D46]"><Icon className="h-5 w-5" /></div>
      <h3 className="mt-4 text-[16px] font-semibold text-[#10231B]">{title}</h3>
      <p className="mt-2 max-w-md text-[13px] leading-6 text-[#65736A]">{body}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

function PrimaryButton({ children, onClick, disabled = false, type = "button" }: { children: ReactNode; onClick?: () => void; disabled?: boolean; type?: "button" | "submit" }) {
  return <button type={type} onClick={onClick} disabled={disabled} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-[#102F22] px-4 text-[12px] font-semibold text-white shadow-[0_8px_24px_rgba(16,47,34,0.16)] transition hover:bg-[#17432F] disabled:cursor-not-allowed disabled:opacity-45">{children}</button>;
}

function SecondaryButton({ children, onClick, disabled = false }: { children: ReactNode; onClick?: () => void; disabled?: boolean }) {
  return <button type="button" onClick={onClick} disabled={disabled} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-[#D2DAD0] bg-white px-4 text-[12px] font-semibold text-[#183427] transition hover:bg-[#F5F7F2] disabled:cursor-not-allowed disabled:opacity-45">{children}</button>;
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="block"><span className="mb-2 block text-[11px] font-bold uppercase tracking-[0.12em] text-[#53665A]">{label}</span>{children}{hint ? <span className="mt-2 block text-[11px] leading-5 text-[#7A867E]">{hint}</span> : null}</label>;
}

const inputClass = "h-11 w-full rounded-xl border border-[#D3DBD1] bg-white px-3 text-[13px] text-[#10231B] outline-none transition placeholder:text-[#98A39C] focus:border-[#6C987A] focus:ring-4 focus:ring-[#DCEADB]";

function PlatformProvider({ children }: { children: ReactNode }) {
  const { platformDeveloper } = useAuth();
  const [state, setState] = useState<PlatformState>({
    projects: [], serviceAccounts: [], keys: [], usage: [], requestLogs: [], webhooks: [], liveAccess: [], support: [],
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [secret, setSecret] = useState("");
  const [secretTitle, setSecretTitle] = useState("");

  const refresh = useCallback(async () => {
    if (!platformDeveloper) return;
    setLoading(true);
    setError("");
    try {
      const overview = record(await apiClient.platformDeveloper.overview());
      const optional = async (enabled: boolean, work: () => Promise<unknown>) => enabled ? work().catch(() => null) : null;
      const [projectsResult, serviceAccountsResult, keysResult, usageResult, logsResult, webhooksResult, billingResult, liveResult, supportResult] = await Promise.all([
        apiClient.platformDeveloper.projects(),
        apiClient.platformDeveloper.serviceAccounts(),
        apiClient.platformDeveloper.keys(),
        apiClient.platformDeveloper.usage(),
        apiClient.platformDeveloper.requestLogs(),
        apiClient.platformDeveloper.webhooks(),
        optional(Boolean(overview.sections?.billing), apiClient.platformDeveloper.billing),
        optional(Boolean(overview.sections?.live_access), apiClient.platformDeveloper.liveAccess),
        optional(Boolean(overview.sections?.support), apiClient.platformDeveloper.support),
      ]);
      const projects = rows(projectsResult, "projects") as Project[];
      setState({
        overview,
        projects,
        serviceAccounts: rows(serviceAccountsResult, "service_accounts") as ServiceAccount[],
        keys: rows(keysResult, "keys") as ApiKey[],
        usage: rows(usageResult, "usage"),
        requestLogs: rows(logsResult, "items"),
        webhooks: rows(webhooksResult, "webhooks"),
        billing: billingResult ? record(billingResult) : undefined,
        liveAccess: rows(liveResult, "requests"),
        support: rows(supportResult, "support_requests"),
      });
      setSelectedProjectId((current) => projects.some((item) => item.id === current) ? current : projects[0]?.id || "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The Platform API console could not load.");
    } finally {
      setLoading(false);
    }
  }, [platformDeveloper]);

  useEffect(() => { void refresh(); }, [refresh]);

  const selectedProject = state.projects.find((item) => item.id === selectedProjectId) || state.projects[0];
  const revealSecret = (title: string, value: string) => { setSecretTitle(title); setSecret(value); };
  const clearSecret = () => { setSecret(""); setSecretTitle(""); };

  return (
    <PlatformContext.Provider value={{ state, loading, error, selectedProjectId, selectedProject, setSelectedProjectId, refresh, secret, secretTitle, revealSecret, clearSecret }}>
      {children}
    </PlatformContext.Provider>
  );
}

function usePlatform() {
  const value = useContext(PlatformContext);
  if (!value) throw new Error("Platform console context is unavailable");
  return value;
}

function AccessGate() {
  const { currentOrganization } = useAuth();
  return (
    <div className="min-h-screen bg-[#F3F1E9] px-5 py-12 text-[#10231B]">
      <div className="mx-auto max-w-[920px] overflow-hidden rounded-[26px] border border-[#D5DCCF] bg-[#FFFDF8] shadow-[0_28px_90px_rgba(16,35,27,0.12)]">
        <div className="grid lg:grid-cols-[0.9fr_1.1fr]">
          <div className="relative overflow-hidden bg-[#092218] px-8 py-10 text-white md:px-10">
            <div className="absolute inset-0 opacity-30" style={{ backgroundImage: "radial-gradient(circle at 18% 10%, rgba(186,222,117,.38), transparent 28%), linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px)", backgroundSize: "auto, 32px 32px, 32px 32px" }} />
            <div className="relative">
              <div className="text-[12px] font-semibold tracking-[0.18em] text-[#C6E57D]">AGRO-AI</div>
              <div className="mt-1 text-[13px] text-white/55">Platform API</div>
              <h1 className="mt-16 text-[36px] font-semibold leading-[1.05] tracking-[-0.04em]">Build field intelligence into your product.</h1>
              <p className="mt-5 text-[14px] leading-7 text-white/68">Projects, service accounts, scoped keys, deterministic sandbox data, usage, logs, and controlled live-access review.</p>
            </div>
          </div>
          <div className="px-7 py-10 md:px-10">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#D7E2D3] bg-[#F4F8F0] px-3 py-1.5 text-[11px] font-semibold text-[#315D46]"><LockKeyhole className="h-3.5 w-3.5" /> Private beta enrollment required</div>
            <h2 className="mt-5 text-[28px] font-semibold tracking-[-0.03em]">Your organization is not enrolled yet.</h2>
            <p className="mt-3 text-[14px] leading-7 text-[#65736A]">{currentOrganization?.name || "This organization"} does not currently have an active Platform API developer enrollment. Access is granted to verified organizations through the controlled private-beta program.</p>
            <div className="mt-7 flex flex-wrap gap-3">
              <a href="https://agroai-pilot.com/platform-api" className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#102F22] px-4 text-[12px] font-semibold text-white">Review the Platform API <ArrowRight className="h-4 w-4" /></a>
              <a href="https://app.agroai-pilot.com" className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#D3DBD1] bg-white px-4 text-[12px] font-semibold text-[#183427]">Enterprise Portal <ExternalLink className="h-4 w-4" /></a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SecretDrawer() {
  const { secret, secretTitle, clearSecret } = usePlatform();
  const [copied, setCopied] = useState(false);
  if (!secret) return null;
  const copy = async () => {
    await navigator.clipboard?.writeText(secret);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };
  return (
    <div className="fixed inset-0 z-[120] flex items-end justify-center bg-[#06140D]/55 p-4 backdrop-blur-sm md:items-center" role="dialog" aria-modal="true" aria-label={secretTitle}>
      <div className="w-full max-w-[640px] rounded-[24px] border border-[#CAD7C5] bg-[#FFFDF8] p-6 shadow-[0_30px_100px_rgba(0,0,0,.28)] md:p-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#4D745C]">One-time secret</div>
            <h2 className="mt-2 text-[23px] font-semibold tracking-[-0.025em] text-[#10231B]">{secretTitle}</h2>
          </div>
          <button type="button" onClick={clearSecret} className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#D5DDD1] bg-white text-[#526159]" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="mt-5 rounded-2xl border border-[#C8D9BE] bg-[#F4FAEF] p-4">
          <code className="block break-all font-mono text-[12px] leading-6 text-[#193C29]">{secret}</code>
        </div>
        <div className="mt-4 rounded-xl border border-[#E3D5A8] bg-[#FFF9E8] px-4 py-3 text-[12px] leading-6 text-[#705518]">This value will not be shown again. Store it in a secure server-side secret manager; never place it in frontend code.</div>
        <div className="mt-6 flex justify-end gap-3"><SecondaryButton onClick={clearSecret}>Done</SecondaryButton><PrimaryButton onClick={copy}>{copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}{copied ? "Copied" : "Copy secret"}</PrimaryButton></div>
      </div>
    </div>
  );
}

function PlatformShell() {
  const { platformDeveloper, currentOrganization, user, logout } = useAuth();
  const { state, loading, error, selectedProjectId, setSelectedProjectId, refresh } = usePlatform();
  const location = useLocation();
  const navigate = useNavigate();
  const route = relativeRoute(location.pathname);
  const [mobileOpen, setMobileOpen] = useState(false);
  const prefix = platformHost() ? "" : "/platform";

  if (!platformDeveloper) return <AccessGate />;
  if (route === "/") return <Navigate to={`${prefix}/home`} replace />;

  const environment = state.projects.find((item) => item.id === selectedProjectId)?.environment || "test";

  return (
    <div className="min-h-screen bg-[#F3F1E9] text-[#10231B]">
      <aside className={`fixed inset-y-0 left-0 z-50 flex w-[272px] flex-col border-r border-white/8 bg-[#071F16] text-white transition-transform duration-200 lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-[76px] items-center justify-between border-b border-white/8 px-5">
          <a href={platformPath("/home")} className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#173B2B] text-[#C8E878] shadow-[0_8px_24px_rgba(0,0,0,.2)]"><Layers3 className="h-5 w-5" /></div>
            <div><div className="text-[14px] font-semibold tracking-tight">AGRO-AI</div><div className="text-[11px] text-white/45">Platform API</div></div>
          </a>
          <button className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 text-white/60 lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X className="h-4 w-4" /></button>
        </div>
        <div className="px-4 py-4">
          <label className="block rounded-2xl border border-white/10 bg-white/[0.045] p-3">
            <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-white/40">Organization</span>
            <span className="mt-1 block truncate text-[13px] font-semibold text-white/90">{currentOrganization?.name || "AGRO-AI organization"}</span>
          </label>
          <label className="mt-3 block">
            <span className="sr-only">Project</span>
            <div className="relative">
              <select value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)} className="h-11 w-full appearance-none rounded-xl border border-white/10 bg-[#102C20] px-3 pr-9 text-[12px] font-medium text-white outline-none focus:border-[#8FB85A]">
                {state.projects.length ? state.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>) : <option value="">No API projects</option>}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-3.5 h-4 w-4 text-white/45" />
            </div>
          </label>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 pb-4" aria-label="Platform API">
          <div className="mb-2 px-3 text-[9px] font-bold uppercase tracking-[0.2em] text-white/30">Build</div>
          {NAV.map(([path, label, Icon], index) => (
            <div key={path} className={index === 9 ? "mt-4 border-t border-white/8 pt-4" : ""}>
              <NavLink to={platformPath(path)} onClick={() => setMobileOpen(false)} className={({ isActive }) => `mb-1 flex h-10 items-center gap-3 rounded-xl px-3 text-[12px] font-medium transition ${isActive || route === path || (path === "/projects" && route.startsWith("/projects/")) ? "bg-[#DCEF8B] text-[#10231B] shadow-[0_8px_22px_rgba(0,0,0,.15)]" : "text-white/62 hover:bg-white/[0.055] hover:text-white"}`}>
                <Icon className="h-4 w-4" /><span>{label}</span>
              </NavLink>
            </div>
          ))}
        </nav>
        <div className="border-t border-white/8 p-4">
          <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
            <div className="truncate text-[12px] font-semibold text-white/85">{user?.name || user?.email || "Account"}</div>
            <div className="mt-1 truncate text-[10px] text-white/38">{user?.email}</div>
            <div className="mt-3 flex gap-2"><a href="https://app.agroai-pilot.com" className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/10 px-2 py-2 text-[10px] font-semibold text-white/62">Enterprise <ExternalLink className="h-3 w-3" /></a><button onClick={() => void logout()} className="rounded-lg border border-white/10 px-3 py-2 text-[10px] font-semibold text-white/62">Log out</button></div>
          </div>
        </div>
      </aside>

      {mobileOpen ? <button className="fixed inset-0 z-40 bg-black/35 lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation overlay" /> : null}

      <div className="lg:pl-[272px]">
        <header className="sticky top-0 z-30 flex h-[68px] items-center justify-between border-b border-[#D7DED2] bg-[#FFFDF8]/92 px-4 backdrop-blur-xl md:px-7">
          <div className="flex items-center gap-3">
            <button className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#D5DDD1] bg-white lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu className="h-4 w-4" /></button>
            <div className="hidden items-center gap-2 text-[12px] text-[#718078] sm:flex"><span className="font-semibold text-[#183427]">Platform API</span><span>/</span><span className="capitalize">{route.split("/").filter(Boolean).join(" / ")}</span></div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.11em] ${environment === "live" ? "border-[#E4C8A7] bg-[#FFF7EB] text-[#8A571F]" : "border-[#BBD5B1] bg-[#F1F8ED] text-[#315D46]"}`}><span className={`h-1.5 w-1.5 rounded-full ${environment === "live" ? "bg-[#C57927]" : "bg-[#4F8F5D]"}`} />{environment}</span>
            <a href="https://agroai-pilot.com/platform-api/docs/" target="_blank" rel="noreferrer" className="hidden h-9 items-center gap-2 rounded-xl border border-[#D5DDD1] bg-white px-3 text-[11px] font-semibold text-[#354A3D] sm:inline-flex">Docs <ExternalLink className="h-3.5 w-3.5" /></a>
            <button onClick={() => void refresh()} className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#D5DDD1] bg-white text-[#526159]" aria-label="Refresh Platform API console"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /></button>
          </div>
        </header>
        <main className="px-4 py-6 md:px-7 md:py-8">
          <div className="mx-auto max-w-[1420px]">
            {error ? <div role="alert" className="mb-5 flex items-start gap-3 rounded-2xl border border-[#E4B9AE] bg-[#FFF2EE] px-4 py-3 text-[12px] leading-6 text-[#823628]"><CircleHelp className="mt-0.5 h-4 w-4 shrink-0" />{error}</div> : null}
            <PlatformRoute route={route} navigate={navigate} />
          </div>
        </main>
      </div>
      <SecretDrawer />
    </div>
  );
}

export function PlatformConsoleApp() {
  return <PlatformProvider><PlatformShell /></PlatformProvider>;
}

function PlatformRoute({ route, navigate }: { route: string; navigate: ReturnType<typeof useNavigate> }) {
  if (route === "/home") return <HomePage navigate={navigate} />;
  if (route === "/projects") return <ProjectsPage navigate={navigate} />;
  if (route.startsWith("/projects/")) return <ProjectDetailPage projectId={decodeURIComponent(route.slice("/projects/".length))} navigate={navigate} />;
  if (route === "/service-accounts") return <ServiceAccountsPage />;
  if (route === "/api-keys") return <ApiKeysPage />;
  if (route === "/playground") return <PlaygroundPage />;
  if (route === "/usage") return <UsagePage />;
  if (route === "/logs") return <LogsPage />;
  if (route === "/webhooks") return <WebhooksPage />;
  if (route === "/billing") return <BillingPage />;
  if (route === "/docs") return <DocsPage />;
  if (route === "/live-access") return <LiveAccessPage />;
  if (route === "/support") return <SupportPage />;
  if (route === "/settings") return <SettingsPage />;
  return <NotFoundPage />;
}

function HomePage({ navigate }: { navigate: ReturnType<typeof useNavigate> }) {
  const { state, selectedProject } = usePlatform();
  const completed = [state.projects.length > 0, state.serviceAccounts.length > 0, state.keys.length > 0, state.requestLogs.length > 0].filter(Boolean).length;
  const progress = Math.round((completed / 4) * 100);
  const recentLogs = state.requestLogs.slice(0, 5);
  const base = platformHost() ? "" : "/platform";
  const steps = [
    [state.projects.length > 0, "Create a test project", "/projects"],
    [state.serviceAccounts.length > 0, "Create a service account", "/service-accounts"],
    [state.keys.length > 0, "Generate a scoped test key", "/api-keys"],
    [state.requestLogs.length > 0, "Make and inspect the first request", "/playground"],
  ] as const;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Developer control plane" title="Build operational intelligence into your product." body="Create isolated test projects, issue scoped machine credentials, explore deterministic field data, and graduate to reviewed live access when your integration is ready." action={<PrimaryButton onClick={() => navigate(`${base}/projects`)}><Plus className="h-4 w-4" /> New project</PrimaryButton>} />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          ["Projects", state.projects.length, Boxes, "Test and reviewed live environments"],
          ["Service accounts", state.serviceAccounts.length, ServerCog, "Machine identities with bounded scopes"],
          ["Active keys", state.keys.filter((item) => item.status === "active").length, KeyRound, "Secrets are revealed only once"],
          ["Recorded requests", state.requestLogs.length, Activity, "Customer-safe request metadata"],
        ].map(([label, value, Icon, note]) => <Surface key={String(label)} className="p-5"><div className="flex items-center justify-between"><div className="text-[11px] font-bold uppercase tracking-[0.14em] text-[#708078]">{String(label)}</div><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#EEF4E9] text-[#315D46]"><Icon className="h-4 w-4" /></div></div><div className="mt-5 text-[32px] font-semibold tracking-[-0.04em]">{String(value)}</div><div className="mt-2 text-[11px] leading-5 text-[#79867E]">{String(note)}</div></Surface>)}
      </div>
      <div className="grid gap-5 xl:grid-cols-[0.92fr_1.08fr]">
        <Surface className="p-6">
          <div className="flex items-center justify-between"><div><div className="text-[11px] font-bold uppercase tracking-[0.16em] text-[#58715F]">Launch checklist</div><h2 className="mt-2 text-[20px] font-semibold tracking-[-0.025em]">From enrollment to first request</h2></div><div className="relative flex h-14 w-14 items-center justify-center rounded-full" style={{ background: `conic-gradient(#315D46 ${progress}%, #E5EAE1 ${progress}% 100%)` }}><div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#FFFDF8] text-[11px] font-bold">{progress}%</div></div></div>
          <div className="mt-6 space-y-2">{steps.map(([done, label, path], index) => <button key={label} onClick={() => navigate(`${base}${path}`)} className="flex w-full items-center gap-3 rounded-xl border border-[#E0E5DC] bg-white px-4 py-3 text-left transition hover:border-[#B9CDB6] hover:bg-[#FAFCF8]"><span className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold ${done ? "bg-[#DDEBCF] text-[#315D46]" : "bg-[#F0F2EE] text-[#7E8982]"}`}>{done ? <Check className="h-3.5 w-3.5" /> : index + 1}</span><span className="flex-1 text-[12px] font-semibold">{label}</span><ArrowRight className="h-3.5 w-3.5 text-[#89958E]" /></button>)}</div>
        </Surface>
        <Surface className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-[#DDE3D9] px-6 py-4"><div><div className="text-[11px] font-bold uppercase tracking-[0.16em] text-[#58715F]">Quickstart</div><h2 className="mt-1 text-[17px] font-semibold">List fields from your server</h2></div><span className="rounded-full border border-[#CBDCC5] bg-[#F2F8EE] px-2.5 py-1 text-[10px] font-semibold text-[#315D46]">{selectedProject?.environment || "test"}</span></div>
          <div className="bg-[#071A12] p-6 font-mono text-[12px] leading-6 text-[#D6E8D3]"><div className="text-[#7EA98A]"># Keep the key in your server-side secret manager</div><div className="mt-3">curl https://api.agroai-pilot.com/v1/platform/fields \</div><div className="pl-4 text-[#C5E879]">-H "Authorization: Bearer $AGROAI_API_KEY"</div></div>
          <div className="flex items-center justify-between px-6 py-4"><p className="text-[11px] text-[#748179]">Test projects return deterministic synthetic data until live access is approved.</p><button onClick={() => navigate(`${base}/playground`)} className="text-[11px] font-semibold text-[#315D46]">Open Playground →</button></div>
        </Surface>
      </div>
      <Surface className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-[#DDE3D9] px-6 py-4"><div><div className="text-[11px] font-bold uppercase tracking-[0.16em] text-[#58715F]">Recent activity</div><h2 className="mt-1 text-[17px] font-semibold">Request log</h2></div><button onClick={() => navigate(`${base}/logs`)} className="text-[11px] font-semibold text-[#315D46]">View all</button></div>
        {recentLogs.length ? <div className="overflow-x-auto"><table className="min-w-full text-left text-[11px]"><thead className="bg-[#F6F7F3] text-[#6D7972]"><tr><th className="px-6 py-3 font-semibold">Operation</th><th className="px-4 py-3 font-semibold">Status</th><th className="px-4 py-3 font-semibold">Latency</th><th className="px-4 py-3 font-semibold">Environment</th><th className="px-6 py-3 font-semibold">Time</th></tr></thead><tbody>{recentLogs.map((log, index) => <tr key={String(log.request_id || index)} className="border-t border-[#E5E9E2]"><td className="px-6 py-3 font-mono text-[#254734]">{String(log.operation_id || log.operation || "request")}</td><td className="px-4 py-3"><StatusPill status={String(log.status_code || log.status || "ok")} /></td><td className="px-4 py-3 text-[#637169]">{Number(log.latency_ms || 0)} ms</td><td className="px-4 py-3 capitalize text-[#637169]">{String(log.environment || "test")}</td><td className="px-6 py-3 text-[#637169]">{formatDate(log.created_at)}</td></tr>)}</tbody></table></div> : <EmptyState icon={FileClock} title="No API requests yet" body="Run a test operation in the Playground or call the API from your server. Safe request metadata will appear here." />}
      </Surface>
    </div>
  );
}

function ProjectsPage({ navigate }: { navigate: ReturnType<typeof useNavigate> }) {
  const { state, refresh, setSelectedProjectId } = usePlatform();
  const [name, setName] = useState("");
  const [working, setWorking] = useState(false);
  const [localError, setLocalError] = useState("");
  const base = platformHost() ? "" : "/platform";
  const create = async () => {
    if (!name.trim()) return;
    setWorking(true); setLocalError("");
    try {
      const result = record(await apiClient.platformDeveloper.createProject({ name: name.trim(), environment: "test" }));
      const id = String(result.project?.id || "");
      setName("");
      await refresh();
      if (id) { setSelectedProjectId(id); navigate(`${base}/projects/${encodeURIComponent(id)}`); }
    } catch (cause) { setLocalError(cause instanceof Error ? cause.message : "Project creation failed."); }
    finally { setWorking(false); }
  };
  return <div className="space-y-6"><PageHeader eyebrow="Projects" title="Isolate every product, environment, and integration." body="Projects are the top-level security and metering boundary. Test and live environments remain structurally separate." />
    <div className="grid gap-5 xl:grid-cols-[0.72fr_1.28fr]">
      <Surface className="p-6"><h2 className="text-[18px] font-semibold">Create a test project</h2><p className="mt-2 text-[12px] leading-6 text-[#6D7A72]">Private-beta projects start in a deterministic sandbox. Live access always requires a separate reviewed decision.</p><div className="mt-5"><Field label="Project name"><input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="Field intelligence integration" maxLength={120} /></Field></div>{localError ? <div className="mt-3 text-[12px] text-[#8A3528]">{localError}</div> : null}<div className="mt-5"><PrimaryButton onClick={() => void create()} disabled={working || !name.trim()}>{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Create project</PrimaryButton></div></Surface>
      <div className="grid gap-4 md:grid-cols-2">{state.projects.map((project) => <button key={project.id} onClick={() => { setSelectedProjectId(project.id); navigate(`${base}/projects/${encodeURIComponent(project.id)}`); }} className="group rounded-2xl border border-[#D8DED3] bg-[#FFFDF8] p-5 text-left shadow-[0_14px_40px_rgba(18,48,32,.045)] transition hover:-translate-y-0.5 hover:border-[#AFC4AC] hover:shadow-[0_20px_50px_rgba(18,48,32,.09)]"><div className="flex items-start justify-between gap-4"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#EDF4E8] text-[#315D46]"><Boxes className="h-5 w-5" /></div><StatusPill status={project.status} /></div><h3 className="mt-5 text-[17px] font-semibold tracking-[-0.02em]">{project.name}</h3><p className="mt-1 font-mono text-[10px] text-[#819087]">{project.slug}</p><div className="mt-5 flex items-center justify-between border-t border-[#E3E7DF] pt-4"><span className="rounded-full border border-[#CADBC4] bg-[#F3F8F0] px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.1em] text-[#315D46]">{project.environment}</span><span className="flex items-center gap-1 text-[10px] font-semibold text-[#6B7A71]">Open <ArrowRight className="h-3 w-3 transition group-hover:translate-x-0.5" /></span></div></button>)}{!state.projects.length ? <Surface className="md:col-span-2"><EmptyState title="No API projects yet" body="Create your first test project to unlock service accounts, scoped keys, and the server-mediated Playground." /></Surface> : null}</div>
    </div></div>;
}

function ProjectDetailPage({ projectId, navigate }: { projectId: string; navigate: ReturnType<typeof useNavigate> }) {
  const { state, refresh, setSelectedProjectId } = usePlatform();
  const project = state.projects.find((item) => item.id === projectId);
  const [working, setWorking] = useState(false);
  const base = platformHost() ? "" : "/platform";
  useEffect(() => { if (project) setSelectedProjectId(project.id); }, [project?.id]);
  if (!project) return <NotFoundPage />;
  const accounts = state.serviceAccounts.filter((item) => item.api_project_id === project.id);
  const keys = state.keys.filter((item) => item.api_project_id === project.id);
  const reset = async () => { setWorking(true); try { await apiClient.platformDeveloper.resetSandbox(project.id); await refresh(); } finally { setWorking(false); } };
  return <div className="space-y-6"><PageHeader eyebrow={`${project.environment} project`} title={project.name} body="Project-scoped credentials, resources, usage, and safety controls." action={<div className="flex gap-3"><SecondaryButton onClick={() => navigate(`${base}/projects`)}>All projects</SecondaryButton>{project.environment === "test" ? <PrimaryButton onClick={() => void reset()} disabled={working}>{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />} Reset sandbox</PrimaryButton> : null}</div>} />
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{[["Environment", project.environment, Globe2], ["Status", project.status, ShieldCheck], ["Service accounts", accounts.length, ServerCog], ["API keys", keys.length, KeyRound]].map(([label, value, Icon]) => <Surface key={String(label)} className="p-5"><div className="flex items-center justify-between"><div className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#718078]">{String(label)}</div><Icon className="h-4 w-4 text-[#50705C]" /></div><div className="mt-5 text-[23px] font-semibold capitalize">{String(value)}</div></Surface>)}</div>
    <div className="grid gap-5 xl:grid-cols-2"><Surface className="p-6"><div className="text-[11px] font-bold uppercase tracking-[0.15em] text-[#5A7461]">Project identity</div><dl className="mt-5 space-y-4 text-[12px]"><div className="flex items-start justify-between gap-6"><dt className="text-[#75827A]">Project ID</dt><dd className="max-w-[65%] break-all font-mono text-right text-[#234433]">{project.id}</dd></div><div className="flex items-start justify-between gap-6"><dt className="text-[#75827A]">Slug</dt><dd className="font-mono text-[#234433]">{project.slug}</dd></div><div className="flex items-start justify-between gap-6"><dt className="text-[#75827A]">Created</dt><dd>{formatDate(project.created_at)}</dd></div><div className="flex items-start justify-between gap-6"><dt className="text-[#75827A]">Rate policy</dt><dd className="max-w-[65%] break-all font-mono text-right text-[10px] text-[#234433]">{JSON.stringify(project.default_rate_limit_policy || {})}</dd></div></dl></Surface><Surface className="p-6"><div className="text-[11px] font-bold uppercase tracking-[0.15em] text-[#5A7461]">Safety boundary</div><div className="mt-5 space-y-3">{[["Synthetic data", project.environment === "test"], ["Provider credentials", false], ["Physical execution", false], ["Automatic live approval", false]].map(([label, enabled]) => <div key={String(label)} className="flex items-center justify-between rounded-xl border border-[#E1E6DE] bg-white px-4 py-3"><span className="text-[12px] font-medium">{String(label)}</span><span className={`text-[11px] font-semibold ${enabled ? "text-[#315D46]" : "text-[#8A5D2D]"}`}>{enabled ? "Enabled" : "Disabled"}</span></div>)}</div></Surface></div>
  </div>;
}

function ServiceAccountsPage() {
  const { state, selectedProjectId, setSelectedProjectId, refresh } = usePlatform();
  const [name, setName] = useState("");
  const [working, setWorking] = useState(false);
  const create = async () => { if (!selectedProjectId || !name.trim()) return; setWorking(true); try { await apiClient.platformDeveloper.createServiceAccount(selectedProjectId, { name: name.trim(), description: "Platform console service account", scopes: DEFAULT_SCOPES }); setName(""); await refresh(); } finally { setWorking(false); } };
  const visible = state.serviceAccounts.filter((item) => !selectedProjectId || item.api_project_id === selectedProjectId);
  return <div className="space-y-6"><PageHeader eyebrow="Machine identities" title="Service accounts" body="Create narrow, project-bound identities before issuing keys. Key scopes can never exceed the parent service account." />
    <Surface className="p-5"><div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">Select a project</option>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>)}</select></Field><Field label="Service account name"><input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="backend-production" /></Field><PrimaryButton onClick={() => void create()} disabled={working || !selectedProjectId || !name.trim()}>{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Create</PrimaryButton></div></Surface>
    <div className="grid gap-4 lg:grid-cols-2">{visible.map((account) => <Surface key={account.id} className="p-5"><div className="flex items-start justify-between"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#EEF4E9] text-[#315D46]"><ServerCog className="h-5 w-5" /></div><StatusPill status={account.status} /></div><h3 className="mt-5 text-[17px] font-semibold">{account.name}</h3><p className="mt-1 font-mono text-[10px] text-[#819087]">{account.id}</p><div className="mt-4 flex flex-wrap gap-1.5">{(account.scopes || []).slice(0, 8).map((scope) => <span key={scope} className="rounded-md border border-[#D8E1D4] bg-[#F5F8F2] px-2 py-1 font-mono text-[9px] text-[#3B5B48]">{scope}</span>)}{(account.scopes || []).length > 8 ? <span className="rounded-md border border-[#D8E1D4] px-2 py-1 text-[9px] text-[#6B7A71]">+{account.scopes.length - 8}</span> : null}</div><div className="mt-5 border-t border-[#E3E7DF] pt-4 text-[10px] text-[#7A877F]">Created {formatDate(account.created_at)}</div></Surface>)}{!visible.length ? <Surface className="lg:col-span-2"><EmptyState icon={ServerCog} title="No service accounts" body="Select a project and create a scoped machine identity before issuing an API key." /></Surface> : null}</div>
  </div>;
}

function ApiKeysPage() {
  const { state, selectedProjectId, setSelectedProjectId, refresh, revealSecret } = usePlatform();
  const accounts = state.serviceAccounts.filter((item) => !selectedProjectId || item.api_project_id === selectedProjectId);
  const [accountId, setAccountId] = useState("");
  const [name, setName] = useState("");
  const [working, setWorking] = useState("");
  useEffect(() => { if (!accounts.some((item) => item.id === accountId)) setAccountId(accounts[0]?.id || ""); }, [selectedProjectId, state.serviceAccounts.length]);
  const create = async () => { if (!accountId || !name.trim()) return; setWorking("create"); try { const result = record(await apiClient.platformDeveloper.createKey(accountId, { name: name.trim(), scopes: DEFAULT_SCOPES, expires_days: 90 })); revealSecret("Store this API key now", String(result.plaintext_key || "")); setName(""); await refresh(); } finally { setWorking(""); } };
  const rotate = async (key: ApiKey) => { setWorking(key.id); try { const result = record(await apiClient.platformDeveloper.rotateKey(key.id)); revealSecret(`Rotated key · ${key.name}`, String(result.plaintext_key || "")); await refresh(); } finally { setWorking(""); } };
  const revoke = async (key: ApiKey) => { if (!window.confirm(`Revoke ${key.name}? Existing integrations using it will stop authenticating.`)) return; setWorking(key.id); try { await apiClient.platformDeveloper.revokeKey(key.id); await refresh(); } finally { setWorking(""); } };
  const visible = state.keys.filter((item) => !selectedProjectId || item.api_project_id === selectedProjectId);
  return <div className="space-y-6"><PageHeader eyebrow="Credentials" title="API keys" body="Issue one-time machine credentials from bounded service accounts. Only prefixes and fingerprints remain visible after creation." />
    <Surface className="p-5"><div className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr_auto] xl:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">Select a project</option>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>)}</select></Field><Field label="Service account"><select className={inputClass} value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">Select an identity</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></Field><Field label="Key name"><input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="production-backend" /></Field><PrimaryButton onClick={() => void create()} disabled={working === "create" || !accountId || !name.trim()}>{working === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} Create key</PrimaryButton></div></Surface>
    <Surface className="overflow-hidden">{visible.length ? <div className="overflow-x-auto"><table className="min-w-full text-left text-[11px]"><thead className="bg-[#F5F7F3] text-[#68766D]"><tr><th className="px-5 py-3 font-semibold">Key</th><th className="px-4 py-3 font-semibold">Environment</th><th className="px-4 py-3 font-semibold">Fingerprint</th><th className="px-4 py-3 font-semibold">Last used</th><th className="px-4 py-3 font-semibold">Expires</th><th className="px-5 py-3 text-right font-semibold">Actions</th></tr></thead><tbody>{visible.map((key) => <tr key={key.id} className="border-t border-[#E2E7DF]"><td className="px-5 py-4"><div className="font-semibold text-[#183427]">{key.name}</div><div className="mt-1 font-mono text-[9px] text-[#89958E]">{key.key_prefix}</div></td><td className="px-4 py-4"><StatusPill status={key.environment} /></td><td className="px-4 py-4 font-mono text-[10px] text-[#45604F]">{key.fingerprint}</td><td className="px-4 py-4 text-[#65736A]">{formatDate(key.last_used_at)}</td><td className="px-4 py-4 text-[#65736A]">{formatDate(key.expires_at)}</td><td className="px-5 py-4"><div className="flex justify-end gap-2"><button onClick={() => void rotate(key)} disabled={working === key.id || key.status !== "active"} className="flex h-8 items-center gap-1.5 rounded-lg border border-[#D5DDD1] px-2.5 text-[10px] font-semibold text-[#3D5848] disabled:opacity-40"><RotateCw className="h-3 w-3" /> Rotate</button><button onClick={() => void revoke(key)} disabled={working === key.id || key.status !== "active"} className="flex h-8 items-center gap-1.5 rounded-lg border border-[#E4C2B9] px-2.5 text-[10px] font-semibold text-[#8A3D30] disabled:opacity-40"><Trash2 className="h-3 w-3" /> Revoke</button></div></td></tr>)}</tbody></table></div> : <EmptyState icon={KeyRound} title="No API keys" body="Create a service account, then issue a test key. The plaintext secret is shown exactly once." />}</Surface>
  </div>;
}

function PlaygroundPage() {
  const { state, selectedProjectId, setSelectedProjectId } = usePlatform();
  const testProjects = state.projects.filter((item) => item.environment === "test" && item.status === "active");
  const [operation, setOperation] = useState("sandbox_summary");
  const [resourceId, setResourceId] = useState("");
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [error, setError] = useState("");
  const [codeTab, setCodeTab] = useState("curl");
  useEffect(() => { if (!testProjects.some((item) => item.id === selectedProjectId)) setSelectedProjectId(testProjects[0]?.id || ""); }, [testProjects.length]);
  const run = async () => { if (!selectedProjectId) return; setWorking(true); setError(""); try { const response = await apiClient.post("/v1/platform/developer/playground/execute", { project_id: selectedProjectId, operation, resource_id: resourceId || undefined }); setResult(record(response) as PlaygroundResult); } catch (cause) { setError(cause instanceof Error ? cause.message : "The Playground request failed."); } finally { setWorking(false); } };
  const code = result?.code?.[codeTab] || "Run an operation to generate a server-side integration example.";
  return <div className="space-y-6"><PageHeader eyebrow="Safe API Explorer" title="Playground" body="Execute test-safe operations through your authenticated portal session. Permanent API keys never enter browser JavaScript." action={<div className="inline-flex items-center gap-2 rounded-full border border-[#BED4B7] bg-[#F1F8ED] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-[#315D46]"><ShieldCheck className="h-3.5 w-3.5" /> Server-mediated</div>} />
    <div className="grid gap-5 xl:grid-cols-[0.78fr_1.22fr]">
      <Surface className="p-6"><div className="text-[11px] font-bold uppercase tracking-[0.16em] text-[#58715F]">Request builder</div><div className="mt-5 space-y-5"><Field label="Test project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">Select a test project</option>{testProjects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></Field><Field label="Operation"><select className={inputClass} value={operation} onChange={(event) => setOperation(event.target.value)}>{PLAYGROUND_OPERATIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><span className="mt-2 block text-[11px] leading-5 text-[#7A877F]">{PLAYGROUND_OPERATIONS.find(([id]) => id === operation)?.[2]}</span></Field>{operation === "get_field" ? <Field label="Field ID" hint="Leave blank to use the first deterministic sandbox field."><input className={inputClass} value={resourceId} onChange={(event) => setResourceId(event.target.value)} placeholder="Synthetic field UUID" /></Field> : null}<div className="rounded-xl border border-[#DCE4D7] bg-[#F7F9F5] p-4 text-[11px] leading-6 text-[#65736A]"><div className="font-semibold text-[#315D46]">Safety guarantees</div><ul className="mt-2 space-y-1"><li>• Test projects only</li><li>• Deterministic synthetic data</li><li>• No provider credentials</li><li>• No physical execution</li><li>• Zero Playground credits</li></ul></div>{error ? <div className="text-[12px] text-[#8A3528]">{error}</div> : null}<PrimaryButton onClick={() => void run()} disabled={working || !selectedProjectId}>{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} Run operation</PrimaryButton></div></Surface>
      <Surface className="overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#DDE3D9] px-5 py-4"><div className="flex items-center gap-3"><span className="rounded-md bg-[#315D46] px-2 py-1 font-mono text-[9px] font-bold text-white">{String(result?.request?.method || "GET")}</span><code className="text-[11px] text-[#315D46]">{String(result?.request?.path || "/v1/platform/...")}</code></div>{result ? <div className="flex gap-3 text-[10px] text-[#748179]"><span>{result.latency_ms || 0} ms</span><span>{result.credit_cost || 0} credits</span><span className="font-mono">{result.request_id}</span></div> : null}</div><div className="min-h-[420px] bg-[#071A12] p-5 font-mono text-[11px] leading-6 text-[#D7E7D4]"><pre className="whitespace-pre-wrap break-words">{result ? JSON.stringify(result.response?.body, null, 2) : "// Run a test-safe operation.\n// The response will appear here without exposing an API key."}</pre></div><div className="border-t border-[#DDE3D9]"><div className="flex gap-1 bg-[#F5F7F3] px-4 py-2">{["curl", "python", "typescript"].map((tab) => <button key={tab} onClick={() => setCodeTab(tab)} className={`rounded-lg px-3 py-1.5 text-[10px] font-semibold capitalize ${codeTab === tab ? "bg-white text-[#183427] shadow-sm" : "text-[#718078]"}`}>{tab}</button>)}</div><pre className="max-h-[230px] overflow-auto bg-[#0C2419] p-5 font-mono text-[11px] leading-6 text-[#D7E7D4] whitespace-pre-wrap">{code}</pre></div></Surface>
    </div></div>;
}

function UsagePage() {
  const { state } = usePlatform();
  const totalEvents = state.usage.reduce((sum, item) => sum + Number(item.events || 0), 0);
  const totalQuantity = state.usage.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
  const max = Math.max(1, ...state.usage.map((item) => Number(item.quantity || item.events || 0)));
  return <div className="space-y-6"><PageHeader eyebrow="Metering" title="Usage" body="Customer-visible usage is derived from durable server events, separated by operation and environment." /><div className="grid gap-4 md:grid-cols-3"><Surface className="p-5"><div className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#718078]">Recorded events</div><div className="mt-5 text-[32px] font-semibold">{totalEvents}</div></Surface><Surface className="p-5"><div className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#718078]">Quantity</div><div className="mt-5 text-[32px] font-semibold">{totalQuantity}</div></Surface><Surface className="p-5"><div className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#718078]">Billing state</div><div className="mt-5 text-[18px] font-semibold">{state.overview?.sections?.billing ? "Enabled for this program" : "Private beta · no billing"}</div></Surface></div><Surface className="p-6">{state.usage.length ? <div className="space-y-5">{state.usage.map((item, index) => { const value = Number(item.quantity || item.events || 0); return <div key={`${item.metric || "metric"}-${index}`}><div className="flex items-center justify-between text-[11px]"><span className="font-semibold text-[#264534]">{String(item.metric || item.operation || "usage")}</span><span className="font-mono text-[#6D7A72]">{value}</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-[#E7ECE4]"><div className="h-full rounded-full bg-gradient-to-r from-[#315D46] to-[#88AD55]" style={{ width: `${Math.max(2, (value / max) * 100)}%` }} /></div></div>; })}</div> : <EmptyState icon={Activity} title="No metered usage yet" body="Usage will appear after API requests are recorded for your projects." />}</Surface></div>;
}

function LogsPage() {
  const { state } = usePlatform();
  const [query, setQuery] = useState("");
  const filtered = state.requestLogs.filter((log) => JSON.stringify(log).toLowerCase().includes(query.toLowerCase()));
  return <div className="space-y-6"><PageHeader eyebrow="Observability" title="Request logs" body="Search customer-safe request metadata. Authorization headers, full keys, credentials, sensitive bodies, and internal stack traces are never displayed." /><Surface className="p-4"><div className="relative"><Search className="absolute left-3 top-3.5 h-4 w-4 text-[#87938C]" /><input className={`${inputClass} pl-10`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search request ID, operation, project, status…" /></div></Surface><Surface className="overflow-hidden">{filtered.length ? <div className="overflow-x-auto"><table className="min-w-full text-left text-[10px]"><thead className="bg-[#F5F7F3] text-[#66736B]"><tr><th className="px-5 py-3 font-semibold">Request ID</th><th className="px-4 py-3 font-semibold">Operation</th><th className="px-4 py-3 font-semibold">Status</th><th className="px-4 py-3 font-semibold">Latency</th><th className="px-4 py-3 font-semibold">Environment</th><th className="px-5 py-3 font-semibold">Created</th></tr></thead><tbody>{filtered.map((log, index) => <tr key={String(log.request_id || index)} className="border-t border-[#E2E7DF]"><td className="max-w-[220px] truncate px-5 py-3 font-mono text-[#355342]">{String(log.request_id || "—")}</td><td className="px-4 py-3 font-mono text-[#355342]">{String(log.operation_id || log.operation || "request")}</td><td className="px-4 py-3"><StatusPill status={String(log.status_code || log.status || "ok")} /></td><td className="px-4 py-3 text-[#65736A]">{Number(log.latency_ms || 0)} ms</td><td className="px-4 py-3 capitalize text-[#65736A]">{String(log.environment || "test")}</td><td className="px-5 py-3 text-[#65736A]">{formatDate(log.created_at)}</td></tr>)}</tbody></table></div> : <EmptyState icon={FileClock} title="No matching request logs" body="Change the filter or run a test operation in the Playground." />}</Surface></div>;
}

function WebhooksPage() {
  const { state, selectedProjectId, setSelectedProjectId, refresh, revealSecret } = usePlatform();
  const enabled = state.overview?.sections?.webhooks !== false;
  const [url, setUrl] = useState("");
  const [working, setWorking] = useState("");
  const create = async () => { if (!selectedProjectId || !url.trim()) return; setWorking("create"); try { const result = record(await apiClient.platformDeveloper.createWebhook({ api_project_id: selectedProjectId, url: url.trim(), description: "Platform console endpoint", subscribed_event_types: ["recommendation.created", "source.created", "sync.completed"] })); revealSecret("Store this webhook signing secret", String(result.signing_secret || "")); setUrl(""); await refresh(); } finally { setWorking(""); } };
  const rotate = async (endpoint: UnknownRecord) => { setWorking(String(endpoint.id)); try { const result = record(await apiClient.platformDeveloper.rotateWebhookSecret(String(endpoint.id))); revealSecret("Rotated webhook signing secret", String(result.signing_secret || "")); await refresh(); } finally { setWorking(""); } };
  const disable = async (endpoint: UnknownRecord) => { setWorking(String(endpoint.id)); try { await apiClient.platformDeveloper.disableWebhook(String(endpoint.id)); await refresh(); } finally { setWorking(""); } };
  return <div className="space-y-6"><PageHeader eyebrow="Event delivery" title="Webhooks" body="Signed endpoints, bounded subscriptions, delivery custody, rotation, and safe redelivery controls." />{!enabled ? <Surface><EmptyState icon={Webhook} title="Webhook delivery is not active for this program" body="The interface is staged, but production delivery remains disabled until the reviewed queue, keyring, and launch flags are enabled." /></Surface> : <><Surface className="p-5"><div className="grid gap-4 md:grid-cols-[1fr_1.4fr_auto] md:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></Field><Field label="HTTPS endpoint"><input className={inputClass} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/agroai/events" /></Field><PrimaryButton onClick={() => void create()} disabled={working === "create" || !url.trim()}>{working === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add endpoint</PrimaryButton></div></Surface><div className="grid gap-4 lg:grid-cols-2">{state.webhooks.map((endpoint, index) => <Surface key={String(endpoint.id || index)} className="p-5"><div className="flex items-start justify-between"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#EEF4E9] text-[#315D46]"><Webhook className="h-5 w-5" /></div><StatusPill status={String(endpoint.status || "active")} /></div><div className="mt-5 break-all font-mono text-[11px] text-[#244835]">{String(endpoint.url || endpoint.endpoint_url || "Webhook endpoint")}</div><div className="mt-4 flex flex-wrap gap-1.5">{(endpoint.subscribed_event_types || endpoint.events || []).map((event: string) => <span key={event} className="rounded-md border border-[#D8E1D4] bg-[#F5F8F2] px-2 py-1 font-mono text-[9px] text-[#3B5B48]">{event}</span>)}</div><div className="mt-5 flex gap-2 border-t border-[#E3E7DF] pt-4"><SecondaryButton onClick={() => void rotate(endpoint)} disabled={working === String(endpoint.id)}><RotateCw className="h-3.5 w-3.5" /> Rotate secret</SecondaryButton><SecondaryButton onClick={() => void disable(endpoint)} disabled={working === String(endpoint.id)}><X className="h-3.5 w-3.5" /> Disable</SecondaryButton></div></Surface>)}{!state.webhooks.length ? <Surface className="lg:col-span-2"><EmptyState icon={Webhook} title="No webhook endpoints" body="Add an HTTPS endpoint to receive selected Platform API events after delivery is enabled for your program." /></Surface> : null}</div></>}</div>;
}

function BillingPage() {
  const { state } = usePlatform();
  const enabled = Boolean(state.overview?.sections?.billing);
  return <div className="space-y-6"><PageHeader eyebrow="Commercial controls" title="Billing" body="Platform API commercial state is independent from the Enterprise Portal subscription." />{!enabled ? <Surface className="overflow-hidden"><div className="grid lg:grid-cols-[1.05fr_.95fr]"><div className="p-7 md:p-9"><div className="inline-flex items-center gap-2 rounded-full border border-[#C7D9C1] bg-[#F3F8F0] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.13em] text-[#315D46]"><Sparkles className="h-3.5 w-3.5" /> Private beta</div><h2 className="mt-5 text-[26px] font-semibold tracking-[-0.03em]">No self-service charges are active.</h2><p className="mt-3 max-w-xl text-[13px] leading-7 text-[#65736A]">Your current enrollment is test-only. No checkout, invoice, payment method, overage, or production billing action is available until pricing and live access are explicitly approved.</p></div><div className="border-t border-[#DDE3D9] bg-[#F6F7F3] p-7 lg:border-l lg:border-t-0"><div className="text-[11px] font-bold uppercase tracking-[0.16em] text-[#5B7361]">Current program</div><div className="mt-4 text-[20px] font-semibold">{state.overview?.program || "Developer private beta"}</div><div className="mt-2 text-[12px] text-[#6D7A72]">Enrollment: {state.overview?.enrollment_status || "active"}</div><div className="mt-5 rounded-xl border border-[#D7DED2] bg-white p-4 text-[11px] leading-6 text-[#65736A]">Live projects, pricing, and payment collection remain disabled by policy.</div></div></div></Surface> : <Surface className="p-6"><pre className="overflow-auto rounded-xl bg-[#071A12] p-5 font-mono text-[11px] leading-6 text-[#D7E7D4]">{JSON.stringify(state.billing || {}, null, 2)}</pre></Surface>}</div>;
}

function DocsPage() {
  const topics = [["Overview", "Architecture, environments, programs, and the test-to-live path.", "/platform-api/docs/"], ["Authentication", "Server-side agro_test_ and agro_live_ keys, rotation, and restrictions.", "/platform-api/docs/authentication.html"], ["Pagination", "Opaque cursors and bounded list requests.", "/platform-api/docs/pagination.html"], ["Errors", "Stable error types, codes, messages, and request IDs.", "/platform-api/docs/errors.html"], ["Rate limits", "RateLimit headers and production-safe backoff.", "/platform-api/docs/rate-limits.html"], ["API reference", "The curated public OpenAPI contract only.", "/platform-api/reference.html"]] as const;
  return <div className="space-y-6"><PageHeader eyebrow="Developer documentation" title="Build against the real contract." body="The public reference is generated from the reviewed Platform API surface. Portal, admin, and internal routes are excluded." action={<a href="https://agroai-pilot.com/platform-api/reference.html" target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#102F22] px-4 text-[12px] font-semibold text-white">Open API reference <ExternalLink className="h-4 w-4" /></a>} /><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{topics.map(([title, body, href]) => <a key={title} href={`https://agroai-pilot.com${href}`} target="_blank" rel="noreferrer" className="group rounded-2xl border border-[#D8DED3] bg-[#FFFDF8] p-5 shadow-[0_14px_40px_rgba(18,48,32,.045)] transition hover:-translate-y-0.5 hover:border-[#AFC4AC]"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#EEF4E9] text-[#315D46]"><BookOpen className="h-5 w-5" /></div><h3 className="mt-5 text-[17px] font-semibold">{title}</h3><p className="mt-2 text-[12px] leading-6 text-[#65736A]">{body}</p><div className="mt-5 flex items-center gap-1 text-[10px] font-semibold text-[#315D46]">Read documentation <ArrowRight className="h-3 w-3 transition group-hover:translate-x-0.5" /></div></a>)}</div></div>;
}

function LiveAccessPage() {
  const { state } = usePlatform();
  const enabled = Boolean(state.overview?.sections?.live_access);
  return <div className="space-y-6"><PageHeader eyebrow="Production review" title="Live access" body="Test success does not automatically grant production access. Every live project remains an explicit security, use-case, provider, billing, and operational decision." />{!enabled ? <Surface><EmptyState icon={ShieldCheck} title="Live-access requests are not enabled for this program" body="Continue validating with deterministic test projects. AGRO-AI will expose the live-access application only after the required commercial and operational gates are active." /></Surface> : <div className="grid gap-4">{state.liveAccess.map((request, index) => <Surface key={String(request.id || index)} className="p-5"><div className="flex items-start justify-between gap-4"><div><div className="text-[11px] font-bold uppercase tracking-[0.14em] text-[#607466]">Live-access request</div><div className="mt-2 font-mono text-[10px] text-[#819087]">{String(request.id || request.live_access_request_id || "")}</div></div><StatusPill status={String(request.status || "submitted")} /></div><p className="mt-5 text-[12px] leading-6 text-[#65736A]">{String(request.intended_production_use || request.reason || "Production review in progress.")}</p></Surface>)}{!state.liveAccess.length ? <Surface><EmptyState icon={ShieldCheck} title="No live-access requests" body="When enabled, submit a project-specific application with expected volume, data categories, incident contacts, network strategy, and retention policy." /></Surface> : null}</div>}</div>;
}

function SupportPage() {
  const { state } = usePlatform();
  return <div className="space-y-6"><PageHeader eyebrow="Technical support" title="Support" body="Review private-beta support requests and open the correct channel for implementation, security, billing, or production-readiness questions." action={<a href="mailto:support@agroai-pilot.com" className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#102F22] px-4 text-[12px] font-semibold text-white">Email support <ArrowRight className="h-4 w-4" /></a>} /><div className="grid gap-5 xl:grid-cols-[1fr_.75fr]"><Surface className="overflow-hidden">{state.support.length ? <div>{state.support.map((item, index) => <div key={String(item.id || index)} className="border-b border-[#E2E7DF] p-5 last:border-b-0"><div className="flex items-start justify-between gap-4"><div><div className="text-[13px] font-semibold">{String(item.subject || item.type || "Support request")}</div><div className="mt-1 text-[11px] text-[#7A877F]">{formatDate(item.created_at)}</div></div><StatusPill status={String(item.status || "open")} /></div><p className="mt-3 text-[12px] leading-6 text-[#65736A]">{String(item.message || item.description || "")}</p></div>)}</div> : <EmptyState icon={LifeBuoy} title="No Platform API support requests" body="Use the private-beta support channel when an implementation, access, or production-readiness question needs review." />}</Surface><Surface className="p-6"><div className="text-[11px] font-bold uppercase tracking-[0.16em] text-[#58715F]">Support boundary</div><div className="mt-5 space-y-3">{["Include a request ID when available", "Never email API keys or signing secrets", "Report suspected credential exposure immediately", "Production incidents use the approved incident contact"].map((line) => <div key={line} className="flex gap-3 rounded-xl border border-[#E0E5DC] bg-white px-4 py-3 text-[11px] leading-5 text-[#58685E]"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#477553]" />{line}</div>)}</div></Surface></div></div>;
}

function SettingsPage() {
  const { currentOrganization, user } = useAuth();
  const { state, selectedProject } = usePlatform();
  return <div className="space-y-6"><PageHeader eyebrow="Platform configuration" title="Settings" body="Identity, program, environment, and product boundaries for the active organization." /><div className="grid gap-5 xl:grid-cols-2"><Surface className="p-6"><div className="text-[11px] font-bold uppercase tracking-[0.16em] text-[#58715F]">Organization</div><dl className="mt-5 space-y-4 text-[12px]"><div className="flex justify-between gap-5"><dt className="text-[#748179]">Name</dt><dd className="font-semibold">{currentOrganization?.name || "—"}</dd></div><div className="flex justify-between gap-5"><dt className="text-[#748179]">Role</dt><dd className="capitalize">{currentOrganization?.role || "—"}</dd></div><div className="flex justify-between gap-5"><dt className="text-[#748179]">Signed in as</dt><dd>{user?.email || "—"}</dd></div><div className="flex justify-between gap-5"><dt className="text-[#748179]">Program</dt><dd>{state.overview?.program || "Developer private beta"}</dd></div><div className="flex justify-between gap-5"><dt className="text-[#748179]">Enrollment</dt><dd><StatusPill status={state.overview?.enrollment_status || "active"} /></dd></div></dl></Surface><Surface className="p-6"><div className="text-[11px] font-bold uppercase tracking-[0.16em] text-[#58715F]">Active context</div><dl className="mt-5 space-y-4 text-[12px]"><div className="flex justify-between gap-5"><dt className="text-[#748179]">Project</dt><dd className="font-semibold">{selectedProject?.name || "No project"}</dd></div><div className="flex justify-between gap-5"><dt className="text-[#748179]">Environment</dt><dd className="capitalize">{selectedProject?.environment || "—"}</dd></div><div className="flex justify-between gap-5"><dt className="text-[#748179]">Allowed environments</dt><dd>{(state.overview?.allowed_environments || ["test"]).join(", ")}</dd></div><div className="flex justify-between gap-5"><dt className="text-[#748179]">API base URL</dt><dd className="font-mono text-[10px]">https://api.agroai-pilot.com/v1</dd></div></dl><div className="mt-6 flex flex-wrap gap-3"><a href="https://app.agroai-pilot.com" className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#D3DBD1] bg-white px-4 text-[11px] font-semibold text-[#183427]">Enterprise Portal <ExternalLink className="h-3.5 w-3.5" /></a><a href="https://agroai-pilot.com/platform-api" className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#D3DBD1] bg-white px-4 text-[11px] font-semibold text-[#183427]">Platform website <ExternalLink className="h-3.5 w-3.5" /></a></div></Surface></div></div>;
}

function NotFoundPage() {
  return <Surface><EmptyState icon={CircleHelp} title="This Platform route does not exist" body="Use the product navigation to return to a supported developer-console surface." action={<a className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#102F22] px-4 text-[12px] font-semibold text-white" href={platformPath("/home")}>Return home <ArrowRight className="h-4 w-4" /></a>} /></Surface>;
}
