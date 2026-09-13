import {
  Activity,
  ArrowRight,
  BookOpen,
  Check,
  Copy,
  CreditCard,
  Gauge,
  KeyRound,
  Loader2,
  Menu,
  Settings2,
  Sparkles,
  TerminalSquare,
  WalletCards,
  X,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import { apiClient } from "../api/client";


type JsonRecord = Record<string, any>;
type Price = { id: string; name: string; price_cents: number; price: string };
type WalletActivity = { id: string; kind: string; status: string; amount_cents: number; amount: string; created_at?: string };
type WalletState = {
  balance_cents: number;
  balance: string;
  lifetime_funded_cents: number;
  lifetime_spent_cents: number;
  minimum_topup_cents: number;
  suggested_topups_cents: number[];
  recent_activity: WalletActivity[];
};

type PricingState = { model: string; currency: string; tasks: Price[]; failed_or_degraded_runs_are_refunded: boolean };

type KeyState = {
  status?: string;
  project?: { id?: string; name?: string; environment?: string };
  key?: { id?: string; prefix?: string; fingerprint?: string; scopes?: string[]; secret?: string | null; one_time_display?: boolean };
  endpoint?: string;
  model?: string;
};

const NAV = [
  ["/home", "Overview", Gauge],
  ["/api-keys", "API Keys", KeyRound],
  ["/playground", "Playground", TerminalSquare],
  ["/usage", "Usage", Activity],
  ["/billing", "Usage & Billing", CreditCard],
  ["/docs", "Docs", BookOpen],
] as const;

const inputClass = "h-11 w-full rounded-xl border border-[#D4DDD3] bg-white px-3 text-[13px] text-[#10231B] outline-none transition placeholder:text-[#98A39C] focus:border-[#72967D] focus:ring-4 focus:ring-[#DDE9DD]";
const textAreaClass = "w-full rounded-xl border border-[#D4DDD3] bg-white px-3 py-3 text-[13px] leading-6 text-[#10231B] outline-none transition placeholder:text-[#98A39C] focus:border-[#72967D] focus:ring-4 focus:ring-[#DDE9DD]";

function money(cents: number | undefined) {
  return `$${((cents || 0) / 100).toFixed(2)}`;
}

function idempotencyKey(prefix: string) {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  return `${prefix}-${random}`;
}

function safeObject(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function Surface({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-[#D8DED3] bg-[#FFFDF8] shadow-[0_18px_55px_rgba(16,47,34,0.055)] ${className}`}>{children}</section>;
}

function PageHeader({ eyebrow, title, body, action }: { eyebrow: string; title: string; body: string; action?: ReactNode }) {
  return (
    <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-3xl">
        <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#4D725D]">{eyebrow}</div>
        <h1 className="mt-2 text-[31px] font-semibold tracking-[-0.04em] text-[#10231B] md:text-[40px]">{title}</h1>
        <p className="mt-3 max-w-2xl text-[14px] leading-7 text-[#65736A]">{body}</p>
      </div>
      {action}
    </header>
  );
}

function PrimaryButton({ children, onClick, disabled = false }: { children: ReactNode; onClick?: () => void; disabled?: boolean }) {
  return <button type="button" disabled={disabled} onClick={onClick} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-[#102F22] px-4 text-[12px] font-semibold text-white shadow-[0_8px_24px_rgba(16,47,34,0.16)] transition hover:bg-[#17432F] disabled:cursor-not-allowed disabled:opacity-45">{children}</button>;
}

function SecondaryButton({ children, onClick, disabled = false }: { children: ReactNode; onClick?: () => void; disabled?: boolean }) {
  return <button type="button" disabled={disabled} onClick={onClick} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-[#D2DAD0] bg-white px-4 text-[12px] font-semibold text-[#183427] transition hover:bg-[#F5F7F2] disabled:cursor-not-allowed disabled:opacity-45">{children}</button>;
}

function ErrorBox({ error }: { error: string }) {
  if (!error) return null;
  return <div role="alert" className="rounded-xl border border-[#E4B9AE] bg-[#FFF2EE] px-4 py-3 text-[12px] leading-6 text-[#823628]">{error}</div>;
}

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <Surface className="p-5"><div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[#69776E]">{label}</div><div className="mt-2 text-[25px] font-semibold tracking-[-0.03em] text-[#10231B]">{value}</div>{detail ? <div className="mt-1 text-[12px] leading-5 text-[#7B877F]">{detail}</div> : null}</Surface>;
}

function CodeBlock({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="relative overflow-hidden rounded-2xl border border-[#243E31] bg-[#0D1E16]">
      <button type="button" onClick={copy} className="absolute right-3 top-3 inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 text-[11px] font-semibold text-white/80 hover:bg-white/10">{copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copied ? "Copied" : "Copy"}</button>
      <pre className="overflow-x-auto px-5 py-5 pr-20 text-[12px] leading-6 text-[#DCE8DF]"><code>{children}</code></pre>
    </div>
  );
}

function WalletButtons({ loading, onAdd }: { loading: boolean; onAdd: (cents: number) => void }) {
  return <div className="flex flex-wrap gap-2">{[1000, 2500, 10000].map((cents) => <SecondaryButton key={cents} disabled={loading} onClick={() => onAdd(cents)}>Add {money(cents)}</SecondaryButton>)}</div>;
}

export function PlatformIntelligenceConsole() {
  const location = useLocation();
  const navigate = useNavigate();
  const route = location.pathname === "/" ? "/home" : location.pathname;
  const [mobileOpen, setMobileOpen] = useState(false);
  const [wallet, setWallet] = useState<WalletState | null>(null);
  const [pricing, setPricing] = useState<PricingState | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [walletData, pricingData] = await Promise.all([
        apiClient.get<WalletState>("/v1/platform/developer/wallet"),
        apiClient.get<PricingState>("/v1/intelligence/pricing"),
      ]);
      setWallet(walletData);
      setPricing(pricingData);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The AGRO-AI Platform could not load.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { setMobileOpen(false); }, [route]);

  const addFunds = async (amountCents: number) => {
    setActionLoading(true);
    setError("");
    try {
      const result = await apiClient.request<JsonRecord>("/v1/platform/developer/wallet/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey("wallet") },
        body: JSON.stringify({ amount_cents: amountCents }),
      });
      const checkoutUrl = String(result.checkout_url || "");
      if (!checkoutUrl.startsWith("https://")) throw new Error("Secure checkout did not return a valid URL.");
      window.location.assign(checkoutUrl);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Checkout could not start.");
      setActionLoading(false);
    }
  };

  const page = route.startsWith("/api-keys") ? <ApiKeysPage onChanged={refresh} />
    : route.startsWith("/playground") ? <PlaygroundPage wallet={wallet} pricing={pricing} onWalletChanged={refresh} onAddFunds={addFunds} />
    : route.startsWith("/usage") ? <UsagePage wallet={wallet} pricing={pricing} />
    : route.startsWith("/billing") ? <BillingPage wallet={wallet} loading={actionLoading} onAddFunds={addFunds} onRefresh={refresh} />
    : route.startsWith("/docs") ? <DocsPage pricing={pricing} />
    : <OverviewPage wallet={wallet} pricing={pricing} loading={actionLoading} onAddFunds={addFunds} onNavigate={navigate} />;

  return (
    <div className="min-h-screen bg-[#F3F1E9] text-[#10231B]">
      <div className="flex min-h-screen">
        <aside className="hidden w-[236px] shrink-0 border-r border-[#D6DDD0] bg-[#F8F6EF] px-4 py-5 lg:flex lg:flex-col">
          <Brand />
          <nav className="mt-8 space-y-1">
            {NAV.map(([path, label, Icon]) => <NavLink key={path} to={path} className={({ isActive }) => `flex h-10 items-center gap-3 rounded-xl px-3 text-[12px] font-semibold transition ${isActive || route === path ? "bg-[#E7EFE5] text-[#163D2A]" : "text-[#68766D] hover:bg-[#EFEDE5] hover:text-[#193629]"}`}><Icon className="h-4 w-4" />{label}</NavLink>)}
          </nav>
          <div className="mt-auto space-y-3">
            <button type="button" onClick={() => navigate("/projects")} className="flex h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-[12px] font-semibold text-[#68766D] transition hover:bg-[#EFEDE5] hover:text-[#193629]"><Settings2 className="h-4 w-4" />Advanced</button>
            <div className="rounded-xl border border-[#D8DED3] bg-white px-3 py-3">
              <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#7A867E]">Balance</div>
              <div className="mt-1 text-[18px] font-semibold text-[#10231B]">{loading ? "—" : wallet?.balance || "$0.00"}</div>
            </div>
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="flex h-16 items-center justify-between border-b border-[#D6DDD0] bg-[#F8F6EF]/95 px-5 backdrop-blur lg:px-8">
            <div className="lg:hidden"><button type="button" onClick={() => setMobileOpen(true)} className="rounded-lg p-2 text-[#315D46]"><Menu className="h-5 w-5" /></button></div>
            <div className="hidden text-[12px] font-semibold text-[#65736A] lg:block">Agricultural intelligence, one API.</div>
            <div className="flex items-center gap-3"><span className="rounded-full border border-[#BDD4C3] bg-[#EDF7EE] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-[#2B6240]">Advisory LIVE</span><PrimaryButton disabled={actionLoading} onClick={() => addFunds(1000)}>{actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <WalletCards className="h-4 w-4" />}Add funds</PrimaryButton></div>
          </header>
          <main className="mx-auto max-w-[1180px] px-5 py-7 lg:px-9 lg:py-9"><ErrorBox error={error} /><div className={error ? "mt-6" : ""}>{page}</div></main>
        </div>
      </div>

      {mobileOpen ? <div className="fixed inset-0 z-50 bg-black/30 lg:hidden"><div className="h-full w-[286px] bg-[#F8F6EF] p-5 shadow-2xl"><div className="flex items-center justify-between"><Brand /><button type="button" onClick={() => setMobileOpen(false)} className="rounded-lg p-2"><X className="h-5 w-5" /></button></div><nav className="mt-8 space-y-1">{NAV.map(([path, label, Icon]) => <NavLink key={path} to={path} className="flex h-11 items-center gap-3 rounded-xl px-3 text-[13px] font-semibold text-[#52645A]"><Icon className="h-4 w-4" />{label}</NavLink>)}<button type="button" onClick={() => navigate("/projects")} className="flex h-11 w-full items-center gap-3 rounded-xl px-3 text-[13px] font-semibold text-[#52645A]"><Settings2 className="h-4 w-4" />Advanced</button></nav></div></div> : null}
    </div>
  );
}

function Brand() {
  return <div className="flex items-center gap-2.5"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#143B29] text-white"><Sparkles className="h-4 w-4" /></div><div><div className="text-[13px] font-bold tracking-[-0.02em] text-[#10231B]">AGRO-AI</div><div className="text-[10px] font-semibold text-[#718077]">Platform API</div></div></div>;
}

function OverviewPage({ wallet, pricing, loading, onAddFunds, onNavigate }: { wallet: WalletState | null; pricing: PricingState | null; loading: boolean; onAddFunds: (cents: number) => void; onNavigate: (path: string) => void }) {
  const cheapest = useMemo(() => pricing?.tasks.reduce((min, item) => Math.min(min, item.price_cents), Number.POSITIVE_INFINITY), [pricing]);
  return <div className="space-y-7"><PageHeader eyebrow="AGRO-AI Intelligence API" title="Put agricultural intelligence inside your product." body="Fund your balance, create one LIVE advisory key, and send agricultural context to one endpoint. AGRO-AI handles domain reasoning, evidence, model routing and safe fallbacks behind the API." action={<PrimaryButton onClick={() => onNavigate("/playground")}><Sparkles className="h-4 w-4" />Run intelligence</PrimaryButton>} />
    <div className="grid gap-4 md:grid-cols-3"><Stat label="Balance" value={wallet?.balance || "$0.00"} detail="Prepaid. No surprise invoice." /><Stat label="API" value="LIVE" detail="Advisory intelligence is self-serve." /><Stat label="Starting at" value={Number.isFinite(cheapest) ? money(cheapest) : "$0.05"} detail="Per completed intelligence run." /></div>
    <Surface className="overflow-hidden"><div className="grid lg:grid-cols-[1.2fr_0.8fr]"><div className="p-7"><div className="text-[11px] font-bold uppercase tracking-[0.15em] text-[#4F735E]">Start in minutes</div><div className="mt-6 grid gap-5 sm:grid-cols-3">{[["01","Add funds","Prepay $10 or more."],["02","Create key","Get an agro_live_ key."],["03","Call intelligence","POST to /v1/intelligence."]].map(([n,t,b]) => <div key={n}><div className="text-[11px] font-bold text-[#6B7A70]">{n}</div><div className="mt-2 text-[15px] font-semibold">{t}</div><div className="mt-1 text-[12px] leading-5 text-[#748078]">{b}</div></div>)}</div><div className="mt-7 flex flex-wrap gap-3"><PrimaryButton disabled={loading} onClick={() => onAddFunds(1000)}><WalletCards className="h-4 w-4" />Add $10</PrimaryButton><SecondaryButton onClick={() => onNavigate("/api-keys")}>Create API key <ArrowRight className="h-4 w-4" /></SecondaryButton></div></div><div className="border-t border-[#D8DED3] bg-[#F0F4EC] p-7 lg:border-l lg:border-t-0"><div className="text-[12px] font-semibold text-[#244634]">What you are buying</div><p className="mt-3 text-[13px] leading-6 text-[#5E7065]">Evidence-grounded agricultural answers, diagnoses, irrigation plans, risk analysis, decisions and reports—not generic model tokens.</p><div className="mt-5 rounded-xl border border-[#C8D7C9] bg-white/70 px-4 py-3 text-[11px] leading-5 text-[#50655A]">Physical execution is not included in self-serve keys. Machine, valve, chemical and provider-write actions remain separately controlled.</div></div></div></Surface>
  </div>;
}

function ApiKeysPage({ onChanged }: { onChanged: () => Promise<void> }) {
  const [state, setState] = useState<KeyState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const bootstrap = async (newKey: boolean) => {
    setLoading(true); setError("");
    try {
      const result = await apiClient.post<KeyState>("/v1/platform/developer/intelligence/bootstrap", { create_new_key: newKey, name: "Production intelligence" });
      setState(result); await onChanged();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "API key could not be created."); }
    finally { setLoading(false); }
  };
  useEffect(() => { void bootstrap(false); }, []);
  const secret = String(state?.key?.secret || "");
  const copy = async () => { if (!secret) return; await navigator.clipboard.writeText(secret); setCopied(true); window.setTimeout(() => setCopied(false), 1500); };
  return <div className="space-y-7"><PageHeader eyebrow="Credentials" title="One key. One intelligence endpoint." body="This LIVE key is intentionally limited to advisory intelligence. It cannot execute physical actions or write to agricultural equipment providers." />
    <ErrorBox error={error} />
    {secret ? <Surface className="border-[#AFCBAC] p-6"><div className="flex items-center gap-2 text-[12px] font-bold text-[#285A35]"><Check className="h-4 w-4" />Your LIVE API key was created</div><p className="mt-2 text-[12px] leading-6 text-[#66756B]">Copy it now. For security, the full secret is shown only once.</p><div className="mt-4 flex items-center gap-2 rounded-xl border border-[#CCD8CB] bg-[#F5F8F3] px-4 py-3"><code className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[12px] text-[#153928]">{secret}</code><button type="button" onClick={copy} className="rounded-lg p-2 text-[#315D46] hover:bg-[#E5EDE3]">{copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}</button></div></Surface> : null}
    <Surface className="p-6"><div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-[#315D46]" /><div className="text-[14px] font-semibold">Production intelligence</div><span className="rounded-full bg-[#EAF5E9] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.1em] text-[#2B6240]">LIVE</span></div><div className="mt-2 text-[12px] leading-5 text-[#718077]">{state?.key?.fingerprint || "Preparing restricted intelligence credential…"}</div><div className="mt-1 text-[11px] text-[#829087]">Scope: intelligence:run</div></div><SecondaryButton disabled={loading} onClick={() => bootstrap(true)}>{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}Create new key</SecondaryButton></div></Surface>
    <Surface className="p-6"><div className="text-[13px] font-semibold">Endpoint</div><code className="mt-3 block rounded-xl bg-[#F1F4EF] px-4 py-3 text-[12px] text-[#244634]">https://api.agroai-pilot.com/v1/intelligence</code><div className="mt-4 text-[11px] leading-5 text-[#748078]">Use <code>Authorization: Bearer $AGROAI_API_KEY</code> or <code>X-API-Key</code>. Every request also requires an <code>Idempotency-Key</code>.</div></Surface>
  </div>;
}

function PlaygroundPage({ wallet, pricing, onWalletChanged, onAddFunds }: { wallet: WalletState | null; pricing: PricingState | null; onWalletChanged: () => Promise<void>; onAddFunds: (cents: number) => void }) {
  const [task, setTask] = useState("field_diagnosis");
  const [question, setQuestion] = useState("What requires attention in this field today?");
  const [input, setInput] = useState('{\n  "crop": "almond",\n  "location": "Fresno, California",\n  "soil_moisture_pct": 24.8,\n  "temperature_c": 34.1\n}');
  const [result, setResult] = useState<JsonRecord | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const selectedPrice = pricing?.tasks.find((item) => item.id === task);
  const run = async () => {
    setLoading(true); setError(""); setResult(null);
    try {
      let parsed: JsonRecord = {};
      if (input.trim()) parsed = JSON.parse(input);
      const response = await apiClient.request<JsonRecord>("/v1/platform/developer/intelligence/run", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey("playground") }, body: JSON.stringify({ task, question, input: parsed }) });
      setResult(response); await onWalletChanged();
    } catch (cause: any) {
      const status = Number(cause?.status || 0);
      setError(status === 402 ? "Your intelligence balance is too low for this run. Add funds and retry." : cause instanceof Error ? cause.message : "The intelligence run failed.");
    } finally { setLoading(false); }
  };
  return <div className="space-y-7"><PageHeader eyebrow="Playground" title="Test real agricultural intelligence." body="The Playground uses the same paid intelligence engine as your API key. Completed runs debit your balance; degraded or failed runs are refunded." action={<div className="text-right"><div className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#78857D]">Balance</div><div className="text-[20px] font-semibold">{wallet?.balance || "$0.00"}</div></div>} />
    <ErrorBox error={error} />
    <div className="grid gap-6 lg:grid-cols-[0.92fr_1.08fr]"><Surface className="p-6"><label className="text-[11px] font-bold uppercase tracking-[0.12em] text-[#5A6C61]">Intelligence task</label><select value={task} onChange={(e) => setTask(e.target.value)} className={`${inputClass} mt-2`}>{(pricing?.tasks || []).map((item) => <option key={item.id} value={item.id}>{item.name} — {item.price}</option>)}</select><label className="mt-5 block text-[11px] font-bold uppercase tracking-[0.12em] text-[#5A6C61]">Question</label><textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} className={`${textAreaClass} mt-2`} /><label className="mt-5 block text-[11px] font-bold uppercase tracking-[0.12em] text-[#5A6C61]">Agricultural input JSON</label><textarea value={input} onChange={(e) => setInput(e.target.value)} rows={10} spellCheck={false} className={`${textAreaClass} mt-2 font-mono`} /><div className="mt-5 flex flex-wrap items-center justify-between gap-3"><div className="text-[11px] text-[#738078]">Cost on successful completion: <strong className="text-[#244634]">{selectedPrice?.price || "—"}</strong></div><PrimaryButton disabled={loading || !question.trim()} onClick={run}>{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}Run intelligence</PrimaryButton></div></Surface>
      <Surface className="min-h-[520px] overflow-hidden"><div className="border-b border-[#D8DED3] px-5 py-4 text-[12px] font-semibold">Response</div>{result ? <pre className="max-h-[640px] overflow-auto p-5 text-[11px] leading-6 text-[#294436]"><code>{JSON.stringify(result, null, 2)}</code></pre> : <div className="flex min-h-[450px] flex-col items-center justify-center px-6 text-center"><Sparkles className="h-7 w-7 text-[#7E9986]" /><div className="mt-4 text-[14px] font-semibold">Your intelligence result appears here.</div><div className="mt-2 max-w-sm text-[12px] leading-6 text-[#78857D]">Structured decision, evidence, confidence, risk flags, missing data and the exact charge.</div>{(wallet?.balance_cents || 0) < (selectedPrice?.price_cents || 0) ? <div className="mt-5"><SecondaryButton onClick={() => onAddFunds(1000)}>Add $10</SecondaryButton></div> : null}</div>}</Surface></div>
  </div>;
}

function UsagePage({ wallet, pricing }: { wallet: WalletState | null; pricing: PricingState | null }) {
  return <div className="space-y-7"><PageHeader eyebrow="Usage" title="Every dollar maps to intelligence." body="Usage is shown in money, not abstract tokens. Each completed intelligence task has a published price." /><div className="grid gap-4 md:grid-cols-3"><Stat label="Current balance" value={wallet?.balance || "$0.00"} /><Stat label="Lifetime funded" value={money(wallet?.lifetime_funded_cents)} /><Stat label="Lifetime intelligence spend" value={money(wallet?.lifetime_spent_cents)} /></div><Surface className="overflow-hidden"><div className="border-b border-[#D8DED3] px-5 py-4 text-[13px] font-semibold">Intelligence pricing</div><div className="divide-y divide-[#E2E6DE]">{(pricing?.tasks || []).map((item) => <div key={item.id} className="flex items-center justify-between px-5 py-3.5"><div><div className="text-[12px] font-semibold">{item.name}</div><div className="mt-1 font-mono text-[10px] text-[#849088]">{item.id}</div></div><div className="text-[13px] font-semibold text-[#244634]">{item.price}</div></div>)}</div></Surface></div>;
}

function BillingPage({ wallet, loading, onAddFunds, onRefresh }: { wallet: WalletState | null; loading: boolean; onAddFunds: (cents: number) => void; onRefresh: () => Promise<void> }) {
  useEffect(() => { if (new URLSearchParams(window.location.search).get("wallet") === "success") void onRefresh(); }, []);
  return <div className="space-y-7"><PageHeader eyebrow="Usage & Billing" title="Prepay. Call intelligence. Stay in control." body="Add funds with Stripe. Your balance is credited only after AGRO-AI independently verifies the paid Checkout Session amount, currency and organization metadata." /><Surface className="p-7"><div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between"><div><div className="text-[11px] font-bold uppercase tracking-[0.13em] text-[#6C7A71]">Available balance</div><div className="mt-2 text-[42px] font-semibold tracking-[-0.05em] text-[#10231B]">{wallet?.balance || "$0.00"}</div><div className="mt-2 text-[12px] text-[#78857D]">Minimum top-up: {money(wallet?.minimum_topup_cents || 500)}</div></div><WalletButtons loading={loading} onAdd={onAddFunds} /></div></Surface><Surface className="overflow-hidden"><div className="border-b border-[#D8DED3] px-5 py-4 text-[13px] font-semibold">Recent activity</div>{wallet?.recent_activity?.length ? <div className="divide-y divide-[#E2E6DE]">{wallet.recent_activity.map((item) => <div key={item.id} className="flex items-center justify-between px-5 py-4"><div><div className="text-[12px] font-semibold capitalize">{item.kind.replaceAll("_", " ")}</div><div className="mt-1 text-[10px] text-[#839087]">{item.status} · {item.created_at ? new Date(item.created_at).toLocaleString() : ""}</div></div><div className={`text-[13px] font-semibold ${item.amount_cents >= 0 ? "text-[#2E6943]" : "text-[#10231B]"}`}>{item.amount_cents >= 0 ? "+" : ""}{item.amount}</div></div>)}</div> : <div className="px-5 py-10 text-center text-[12px] text-[#7A867E]">No intelligence wallet activity yet.</div>}</Surface></div>;
}

function DocsPage({ pricing }: { pricing: PricingState | null }) {
  const curl = `curl https://api.agroai-pilot.com/v1/intelligence \\\n  -H "Authorization: Bearer $AGROAI_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -H "Idempotency-Key: diagnosis-001" \\\n  -d '{\n    "task": "field_diagnosis",\n    "question": "What requires attention today?",\n    "input": {\n      "crop": "almond",\n      "location": "Fresno, California",\n      "soil_moisture_pct": 24.8\n    }\n  }'`;
  const python = `import os, uuid, requests\n\nresponse = requests.post(\n    "https://api.agroai-pilot.com/v1/intelligence",\n    headers={\n        "Authorization": f"Bearer {os.environ['AGROAI_API_KEY']}",\n        "Idempotency-Key": str(uuid.uuid4()),\n    },\n    json={\n        "task": "field_diagnosis",\n        "question": "What requires attention today?",\n        "input": {"crop": "almond", "soil_moisture_pct": 24.8},\n    },\n    timeout=120,\n)\nresponse.raise_for_status()\nprint(response.json()["decision"])`;
  return <div className="space-y-7"><PageHeader eyebrow="Documentation" title="One endpoint for agricultural intelligence." body="The public contract is intentionally small. Send context and a task. Receive a structured agricultural intelligence object." /><Surface className="p-6"><div className="grid gap-5 md:grid-cols-3">{[["Endpoint","POST /v1/intelligence"],["Authentication","Bearer or X-API-Key"],["Model",pricing?.model || "agroai-intelligence-1"]].map(([label,value]) => <div key={label}><div className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#7A867E]">{label}</div><div className="mt-2 font-mono text-[12px] font-semibold text-[#244634]">{value}</div></div>)}</div></Surface><div><div className="mb-3 text-[13px] font-semibold">cURL</div><CodeBlock>{curl}</CodeBlock></div><div><div className="mb-3 text-[13px] font-semibold">Python</div><CodeBlock>{python}</CodeBlock></div><Surface className="p-6"><div className="text-[13px] font-semibold">Production contract</div><div className="mt-4 grid gap-3 sm:grid-cols-2"><div className="rounded-xl bg-[#F2F5F0] px-4 py-3 text-[12px] leading-6 text-[#607066]">Every request requires an idempotency key. Safe retries return the same result instead of charging twice.</div><div className="rounded-xl bg-[#F2F5F0] px-4 py-3 text-[12px] leading-6 text-[#607066]">Degraded or failed intelligence runs are automatically refunded.</div><div className="rounded-xl bg-[#F2F5F0] px-4 py-3 text-[12px] leading-6 text-[#607066]">Stateful calls can reference AGRO-AI field/workspace IDs; stateless calls can carry context directly.</div><div className="rounded-xl bg-[#F2F5F0] px-4 py-3 text-[12px] leading-6 text-[#607066]">Self-serve keys are advisory only. Physical execution requires separate authorization.</div></div></Surface></div>;
}
