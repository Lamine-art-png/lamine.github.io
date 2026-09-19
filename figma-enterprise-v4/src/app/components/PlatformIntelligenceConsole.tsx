import {
  Activity,
  ArrowRight,
  BookOpen,
  Check,
  Code2,
  Copy,
  CreditCard,
  ExternalLink,
  Gauge,
  KeyRound,
  Loader2,
  Menu,
  Play,
  Settings2,
  Sparkles,
  TerminalSquare,
  WalletCards,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { API_BASE_URL, apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";


type UnknownRecord = Record<string, any>;
type Project = { id: string; name: string; environment: string; status: string };
type ServiceAccount = { id: string; api_project_id: string; name: string; scopes?: string[]; status: string };
type ApiKey = { id: string; api_project_id: string; service_account_id: string; name: string; environment: string; key_prefix: string; fingerprint: string; status: string; created_at?: string };

type ConsoleState = {
  overview: UnknownRecord;
  projects: Project[];
  serviceAccounts: ServiceAccount[];
  keys: ApiKey[];
  billing: UnknownRecord;
  usage: UnknownRecord[];
  pricing: UnknownRecord;
};

const SAFE_INTELLIGENCE_SCOPES = [
  "projects:read",
  "fields:read",
  "observations:read",
  "recommendations:read",
  "reports:read",
  "usage:read",
];

const NAV = [
  ["/home", "Overview", Gauge],
  ["/api-keys", "API Keys", KeyRound],
  ["/playground", "Playground", TerminalSquare],
  ["/billing", "Usage & Billing", CreditCard],
  ["/docs", "Docs", BookOpen],
] as const;

function objectValue(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function rows(value: unknown, key: string): UnknownRecord[] {
  const found = objectValue(value)[key];
  return Array.isArray(found) ? found : [];
}

function platformPath(path: string) {
  return window.location.hostname.toLowerCase() === "platform.agroai-pilot.com" ? path : `/platform${path}`;
}

function routePath() {
  const pathname = window.location.pathname.replace(/^\/platform(?=\/|$)/, "") || "/home";
  return pathname === "/" ? "/home" : pathname;
}

function shellRequest<T>(path: string, token: string | null, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return fetch(`${API_BASE_URL}${path}`, { ...options, headers }).then(async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = objectValue(payload.detail);
      throw new Error(String(detail.message || payload.message || payload.detail || `Request failed (${response.status})`));
    }
    return payload as T;
  });
}

function Surface({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-[22px] border border-[#D8DED3] bg-[#FFFDF9] shadow-[0_16px_48px_rgba(16,47,34,0.055)] ${className}`}>{children}</section>;
}

function Button({ children, onClick, disabled = false, secondary = false }: { children: ReactNode; onClick?: () => void; disabled?: boolean; secondary?: boolean }) {
  return <button type="button" onClick={onClick} disabled={disabled} className={`inline-flex h-11 items-center justify-center gap-2 rounded-xl px-4 text-[13px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-45 ${secondary ? "border border-[#CFD8CE] bg-white text-[#143326] hover:bg-[#F4F7F2]" : "bg-[#102F22] text-white shadow-[0_10px_25px_rgba(16,47,34,.17)] hover:bg-[#174530]"}`}>{children}</button>;
}

function Pill({ children }: { children: ReactNode }) {
  return <span className="inline-flex rounded-full border border-[#C9DCC8] bg-[#EFF7EC] px-2.5 py-1 text-[11px] font-semibold text-[#285C37]">{children}</span>;
}

function Code({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return <div className="relative overflow-hidden rounded-2xl bg-[#0F211A] text-[#E9F1E9]"><button onClick={copy} className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11px] font-semibold text-white"><Copy className="h-3.5 w-3.5" />{copied ? "Copied" : "Copy"}</button><pre className="overflow-x-auto px-5 py-6 pr-24 text-[12px] leading-6"><code>{children}</code></pre></div>;
}

export function PlatformIntelligenceConsole() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [mobile, setMobile] = useState(false);
  const [state, setState] = useState<ConsoleState>({ overview: {}, projects: [], serviceAccounts: [], keys: [], billing: {}, usage: [], pricing: {} });
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [secret, setSecret] = useState("");
  const [playResult, setPlayResult] = useState<UnknownRecord | null>(null);
  const current = routePath();

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const overview = objectValue(await apiClient.platformDeveloper.overview());
      const [projectsResult, accountsResult, keysResult, usageResult, billingResult, pricingResult] = await Promise.all([
        apiClient.platformDeveloper.projects(),
        apiClient.platformDeveloper.serviceAccounts(),
        apiClient.platformDeveloper.keys(),
        apiClient.platformDeveloper.usage(),
        apiClient.platformDeveloper.billing().catch(() => ({})),
        shellRequest<UnknownRecord>("/v1/platform/pricing", token).catch(() => ({})),
      ]);
      setState({
        overview,
        projects: rows(projectsResult, "projects") as Project[],
        serviceAccounts: rows(accountsResult, "service_accounts") as ServiceAccount[],
        keys: rows(keysResult, "keys") as ApiKey[],
        usage: rows(usageResult, "usage"),
        billing: objectValue(billingResult),
        pricing: objectValue(pricingResult),
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Platform could not load.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { void refresh(); }, [refresh]);

  const subscription = objectValue(state.billing.subscription);
  const plan = objectValue(subscription.plan);
  const paid = ["active", "trialing", "enterprise_contract"].includes(String(subscription.status || ""));
  const liveProject = state.projects.find((item) => item.environment === "live" && item.status === "active");
  const testProject = state.projects.find((item) => item.environment === "test" && item.status === "active");
  const activeProject = liveProject || testProject;
  const activeKey = state.keys.find((item) => item.api_project_id === activeProject?.id && item.status === "active");
  const intelligenceCredits = useMemo(() => state.usage.reduce((total, row) => total + Number(row.quantity || 0), 0), [state.usage]);

  const checkout = async (selectedPlan: "developer" | "scale") => {
    setWorking(`checkout:${selectedPlan}`);
    setError("");
    try {
      const result = await shellRequest<UnknownRecord>("/v1/platform/developer/billing/checkout", token, {
        method: "POST",
        headers: { "Idempotency-Key": `checkout_${selectedPlan}_${crypto.randomUUID()}` },
        body: JSON.stringify({ plan: selectedPlan, billing_interval: "monthly" }),
      });
      if (!result.checkout_url) throw new Error("Checkout URL was not returned.");
      window.location.assign(String(result.checkout_url));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Checkout could not start.");
      setWorking("");
    }
  };

  const bootstrap = async () => {
    setWorking("bootstrap");
    setError("");
    setSecret("");
    try {
      let project = state.projects.find((item) => item.environment === (paid ? "live" : "test") && item.status === "active");
      if (!project) {
        const created = objectValue(await apiClient.platformDeveloper.createProject({
          name: paid ? "Production Intelligence" : "Intelligence Sandbox",
          environment: paid ? "live" : "test",
        }));
        project = objectValue(created.project) as Project;
      }
      let account = state.serviceAccounts.find((item) => item.api_project_id === project!.id && item.status === "active");
      if (!account) {
        const created = objectValue(await apiClient.platformDeveloper.createServiceAccount(project!.id, {
          name: "AGRO-AI Intelligence",
          description: "Advisory agricultural intelligence only. No physical execution scopes.",
          scopes: SAFE_INTELLIGENCE_SCOPES,
        }));
        account = objectValue(created.service_account) as ServiceAccount;
      }
      const createdKey = objectValue(await apiClient.platformDeveloper.createKey(account!.id, {
        name: paid ? "Production intelligence key" : "Sandbox intelligence key",
        scopes: SAFE_INTELLIGENCE_SCOPES,
      }));
      const plaintext = String(createdKey.plaintext_key || "");
      if (!plaintext) throw new Error("The one-time API key was not returned. Do not retry blindly; inspect the request log.");
      setSecret(plaintext);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "API key setup failed.");
    } finally {
      setWorking("");
    }
  };

  const runPlayground = async () => {
    setWorking("playground");
    setPlayResult(null);
    setError("");
    try {
      const result = await shellRequest<UnknownRecord>("/v1/platform/developer/playground/execute", token, {
        method: "POST",
        body: JSON.stringify({ operation: "list_recommendations", api_project_id: testProject?.id || activeProject?.id }),
      });
      setPlayResult(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Playground run failed.");
    } finally {
      setWorking("");
    }
  };

  const python = `from agroai_platform import AgroAI\n\nclient = AgroAI()\n\nrun = client.intelligence(\n    task="field_diagnosis",\n    question="What needs attention in this field today?",\n    input={\n        "crop": "tomato",\n        "location": "Fresno, California",\n        "soil_moisture_pct": 24.8,\n        "temperature_c": 34.1\n    }\n)\n\nprint(run["summary"])\nprint(run["recommendations"])`;
  const curl = `curl https://api.agroai-pilot.com/v1/platform/intelligence \\\n  -H "Authorization: Bearer $AGROAI_API_KEY" \\\n  -H "Idempotency-Key: intel-001" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "task": "field_diagnosis",\n    "question": "What needs attention today?",\n    "input": {"crop":"almond","location":"Fresno, CA"}\n  }'`;

  const go = (path: string) => { navigate(platformPath(path)); setMobile(false); };

  return <div className="min-h-screen bg-[#F3F1E9] text-[#10231B]">
    <div className="flex min-h-screen">
      <aside className={`fixed inset-y-0 left-0 z-40 w-[248px] border-r border-[#D8DED3] bg-[#FFFDF9] p-4 transition lg:static lg:block ${mobile ? "block" : "hidden"}`}>
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between px-2 py-3"><div><div className="text-[15px] font-bold tracking-[-.02em]">AGRO-AI</div><div className="mt-0.5 text-[11px] font-medium text-[#6B776F]">Developer Platform</div></div><button className="lg:hidden" onClick={() => setMobile(false)}><X className="h-5 w-5" /></button></div>
          <div className="mt-4 space-y-1">{NAV.map(([path, label, Icon]) => <button key={path} onClick={() => go(path)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[13px] font-semibold transition ${current === path || (path === "/home" && current === "/") ? "bg-[#E9F1E5] text-[#17472F]" : "text-[#5D6B63] hover:bg-[#F1F4EF]"}`}><Icon className="h-4 w-4" />{label}</button>)}</div>
          <div className="mt-auto border-t border-[#E0E5DC] pt-4"><button onClick={() => go("/projects")} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[12px] font-semibold text-[#6B776F] hover:bg-[#F1F4EF]"><Settings2 className="h-4 w-4" />Advanced</button></div>
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <div className="border-b border-[#D8DED3] bg-[#FFFDF9]/90 px-5 py-3 backdrop-blur lg:hidden"><button onClick={() => setMobile(true)}><Menu className="h-5 w-5" /></button></div>
        <div className="mx-auto max-w-[1120px] px-5 py-8 md:px-8 md:py-10">
          {loading ? <div className="flex min-h-[420px] items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-[#3D6D52]" /></div> : null}
          {!loading && error ? <div className="mb-5 rounded-xl border border-[#E6BDB3] bg-[#FFF2EE] px-4 py-3 text-[13px] text-[#813A2E]">{error}</div> : null}
          {!loading && current === "/home" ? <>
            <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between"><div><div className="text-[11px] font-bold uppercase tracking-[.18em] text-[#4C755B]">Agricultural intelligence API</div><h1 className="mt-2 max-w-3xl text-[38px] font-semibold tracking-[-.045em] md:text-[48px]">Put AGRO-AI intelligence inside your product.</h1><p className="mt-4 max-w-2xl text-[15px] leading-7 text-[#68766D]">Send agricultural context. Get evidence-grounded decisions, recommendations, risks, confidence and next actions through one API.</p></div>{paid ? <Pill>{plan.display_name || "Paid API"} · LIVE advisory</Pill> : <Pill>Sandbox ready</Pill>}</header>
            <div className="mt-8 grid gap-5 lg:grid-cols-[1.35fr_.65fr]">
              <Surface className="p-6 md:p-7"><div className="flex items-start gap-4"><div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#E9F2E5] text-[#285C37]"><Zap className="h-5 w-5" /></div><div><h2 className="text-[20px] font-semibold tracking-[-.025em]">From account to first intelligence call</h2><p className="mt-1 text-[13px] leading-6 text-[#6B776F]">No sales call. No integration project. Pay, create a key, call intelligence.</p></div></div>
                <div className="mt-7 grid gap-3 md:grid-cols-3"><div className="rounded-2xl border border-[#DCE2D9] bg-white p-4"><div className="text-[11px] font-bold uppercase tracking-[.14em] text-[#6A786E]">1 · Activate</div><div className="mt-2 text-[15px] font-semibold">Developer API</div><div className="mt-1 text-[12px] leading-5 text-[#738078]">$149/month. LIVE advisory intelligence + usage.</div>{paid ? <div className="mt-4 flex items-center gap-1.5 text-[12px] font-semibold text-[#2B673D]"><Check className="h-4 w-4" />Active</div> : <Button onClick={() => checkout("developer")} disabled={Boolean(working)}>{working === "checkout:developer" ? <Loader2 className="h-4 w-4 animate-spin" /> : <WalletCards className="h-4 w-4" />}Activate</Button>}</div>
                <div className="rounded-2xl border border-[#DCE2D9] bg-white p-4"><div className="text-[11px] font-bold uppercase tracking-[.14em] text-[#6A786E]">2 · Key</div><div className="mt-2 text-[15px] font-semibold">One-click bootstrap</div><div className="mt-1 text-[12px] leading-5 text-[#738078]">Creates the project, safe service account and API key.</div><div className="mt-4"><Button onClick={bootstrap} disabled={Boolean(working)}>{working === "bootstrap" ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}{paid ? "Create LIVE key" : "Create TEST key"}</Button></div></div>
                <div className="rounded-2xl border border-[#DCE2D9] bg-white p-4"><div className="text-[11px] font-bold uppercase tracking-[.14em] text-[#6A786E]">3 · Build</div><div className="mt-2 text-[15px] font-semibold">Call intelligence</div><div className="mt-1 text-[12px] leading-5 text-[#738078]">One endpoint for diagnosis, irrigation, risk, evidence and reports.</div><div className="mt-4"><Button onClick={() => go("/docs")} secondary><Code2 className="h-4 w-4" />Quickstart</Button></div></div></div>
                {secret ? <div className="mt-5 rounded-2xl border border-[#B9D6B6] bg-[#EFF8EC] p-5"><div className="flex items-center justify-between gap-4"><div><div className="text-[12px] font-bold text-[#235B35]">Your API key — shown once</div><div className="mt-1 text-[11px] text-[#5B725F]">Store it as AGROAI_API_KEY. AGRO-AI never shows the plaintext again.</div></div><button onClick={() => navigator.clipboard.writeText(secret)} className="rounded-lg border border-[#B9D6B6] bg-white p-2"><Copy className="h-4 w-4" /></button></div><code className="mt-4 block overflow-x-auto rounded-xl bg-[#143425] px-4 py-3 text-[12px] text-white">{secret}</code></div> : null}
              </Surface>
              <div className="grid gap-5"><Surface className="p-5"><div className="text-[11px] font-bold uppercase tracking-[.14em] text-[#65736A]">Environment</div><div className="mt-3 flex items-center gap-2"><div className={`h-2.5 w-2.5 rounded-full ${liveProject ? "bg-emerald-600" : "bg-amber-500"}`} /><div className="text-[16px] font-semibold">{liveProject ? "LIVE intelligence" : "TEST sandbox"}</div></div><p className="mt-2 text-[12px] leading-5 text-[#6B776F]">{liveProject ? "Real customer context may be processed for advisory intelligence. Physical/provider execution remains gated." : "Evaluation environment. Activate Developer to create a LIVE advisory key."}</p></Surface>
                <Surface className="p-5"><div className="flex items-center justify-between"><div><div className="text-[11px] font-bold uppercase tracking-[.14em] text-[#65736A]">Usage</div><div className="mt-2 text-[26px] font-semibold tracking-[-.04em]">{intelligenceCredits.toLocaleString()}</div><div className="text-[11px] text-[#758179]">recorded API events</div></div><Activity className="h-5 w-5 text-[#48745A]" /></div></Surface></div>
            </div>
            <Surface className="mt-5 p-6 md:p-7"><div className="flex items-center justify-between"><div><h2 className="text-[18px] font-semibold">Your first call</h2><p className="mt-1 text-[12px] text-[#6B776F]">The customer integration stays stable even as AGRO-AI improves its underlying intelligence stack.</p></div><Sparkles className="h-5 w-5 text-[#49745B]" /></div><div className="mt-5"><Code>{curl}</Code></div></Surface>
          </> : null}

          {!loading && current === "/api-keys" ? <><header><div className="text-[11px] font-bold uppercase tracking-[.18em] text-[#4C755B]">Credentials</div><h1 className="mt-2 text-[36px] font-semibold tracking-[-.04em]">API Keys</h1><p className="mt-3 text-[14px] text-[#69766E]">Use server-side only. LIVE keys can call advisory intelligence immediately on an active paid API plan.</p></header><div className="mt-7 flex gap-3"><Button onClick={bootstrap} disabled={Boolean(working)}><KeyRound className="h-4 w-4" />Create {paid ? "LIVE" : "TEST"} key</Button></div>{secret ? <div className="mt-5"><Code>{secret}</Code></div> : null}<Surface className="mt-5 overflow-hidden"><div className="divide-y divide-[#E1E6DE]">{state.keys.length ? state.keys.map((key) => <div key={key.id} className="flex flex-col gap-3 px-5 py-4 md:flex-row md:items-center md:justify-between"><div><div className="flex items-center gap-2"><span className="text-[13px] font-semibold">{key.name}</span><Pill>{key.environment.toUpperCase()}</Pill></div><div className="mt-1 font-mono text-[11px] text-[#77837B]">{key.key_prefix}… · {key.fingerprint}</div></div><span className="text-[11px] font-semibold capitalize text-[#647168]">{key.status}</span></div>) : <div className="px-6 py-12 text-center text-[13px] text-[#6D7971]">No API keys yet.</div>}</div></Surface></> : null}

          {!loading && current === "/playground" ? <><header><div className="text-[11px] font-bold uppercase tracking-[.18em] text-[#4C755B]">Try before wiring</div><h1 className="mt-2 text-[36px] font-semibold tracking-[-.04em]">Playground</h1><p className="mt-3 max-w-2xl text-[14px] leading-7 text-[#69766E]">Run the authenticated TEST fixture in-browser, then use your API key for LIVE agricultural intelligence from your server.</p></header><Surface className="mt-7 p-6"><div className="flex items-center justify-between"><div><div className="text-[15px] font-semibold">Sample agricultural recommendations</div><div className="mt-1 text-[12px] text-[#718078]">Deterministic TEST data. No credits charged to LIVE usage.</div></div><Button onClick={runPlayground} disabled={Boolean(working)}>{working === "playground" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}Run</Button></div>{playResult ? <pre className="mt-5 max-h-[420px] overflow-auto rounded-2xl bg-[#10231B] p-5 text-[11px] leading-5 text-[#E7F1E8]">{JSON.stringify(playResult, null, 2)}</pre> : null}</Surface><div className="mt-5"><Code>{python}</Code></div></> : null}

          {!loading && current === "/billing" ? <><header><div className="text-[11px] font-bold uppercase tracking-[.18em] text-[#4C755B]">Commerce</div><h1 className="mt-2 text-[36px] font-semibold tracking-[-.04em]">Usage & Billing</h1><p className="mt-3 text-[14px] text-[#69766E]">You pay for agricultural intelligence work. AGRO-AI meters successful billable operations; failed intelligence-provider runs are not charged.</p></header><div className="mt-7 grid gap-5 md:grid-cols-2"><Surface className="p-6"><div className="flex items-center gap-3"><CreditCard className="h-5 w-5 text-[#477258]" /><div className="text-[16px] font-semibold">Developer</div></div><div className="mt-4 text-[34px] font-semibold tracking-[-.05em]">$149<span className="text-[14px] font-medium text-[#6C7971]">/mo</span></div><p className="mt-3 text-[12px] leading-6 text-[#6B776F]">250,000 included credits, LIVE advisory intelligence, production API keys, usage logs and metered overage.</p><div className="mt-5">{paid && String(plan.plan_identifier || "").includes("developer") ? <Pill>Current plan</Pill> : <Button onClick={() => checkout("developer")} disabled={Boolean(working)}>Activate Developer</Button>}</div></Surface><Surface className="p-6"><div className="flex items-center gap-3"><Zap className="h-5 w-5 text-[#477258]" /><div className="text-[16px] font-semibold">Scale</div></div><div className="mt-4 text-[34px] font-semibold tracking-[-.05em]">$749<span className="text-[14px] font-medium text-[#6C7971]">/mo</span></div><p className="mt-3 text-[12px] leading-6 text-[#6B776F]">2,000,000 included credits, lower overage rate, more projects, keys and higher-scale production use.</p><div className="mt-5">{paid && String(plan.plan_identifier || "").includes("scale") ? <Pill>Current plan</Pill> : <Button onClick={() => checkout("scale")} disabled={Boolean(working)}>Choose Scale</Button>}</div></Surface></div><Surface className="mt-5 p-6"><div className="flex items-center justify-between"><div><div className="text-[15px] font-semibold">Current subscription</div><div className="mt-1 text-[12px] text-[#6D7A72]">{paid ? `${plan.display_name || "API plan"} · ${subscription.status}` : "No paid API plan active"}</div></div><WalletCards className="h-5 w-5 text-[#4C755B]" /></div></Surface></> : null}

          {!loading && current === "/docs" ? <><header><div className="text-[11px] font-bold uppercase tracking-[.18em] text-[#4C755B]">Quickstart</div><h1 className="mt-2 text-[36px] font-semibold tracking-[-.04em]">One endpoint. Agricultural intelligence.</h1><p className="mt-3 max-w-2xl text-[14px] leading-7 text-[#69766E]">Use stateless context for instant adoption or add a project field_id so AGRO-AI can assemble authorized field evidence automatically.</p></header><div className="mt-7 grid gap-5"><Surface className="p-6"><h2 className="text-[17px] font-semibold">Python</h2><div className="mt-4"><Code>{python}</Code></div></Surface><Surface className="p-6"><h2 className="text-[17px] font-semibold">cURL</h2><div className="mt-4"><Code>{curl}</Code></div></Surface><Surface className="p-6"><h2 className="text-[17px] font-semibold">Tasks</h2><div className="mt-4 flex flex-wrap gap-2">{["general","field_diagnosis","irrigation_plan","crop_risk","evidence_analysis","report","integration_diagnosis"].map((task) => <Pill key={task}>{task}</Pill>)}</div><p className="mt-4 text-[12px] leading-6 text-[#6D7A72]">Every run returns summary, decisions, recommendations, next actions, confidence, risk flags, missing data, citations, verification and usage metadata.</p><a href="https://api.agroai-pilot.com/v1/platform/openapi.json" target="_blank" rel="noreferrer" className="mt-5 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[#285C3C]">Open API reference <ExternalLink className="h-3.5 w-3.5" /></a></Surface></div></> : null}
        </div>
      </main>
    </div>
  </div>;
}
