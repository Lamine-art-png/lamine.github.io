import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Database,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { apiClient, type ApiError } from "../api/client";
import { usePortalCopy } from "../hooks/usePortalCopy";

const COPY = [
  "Market Intelligence",
  "Commercial decision intelligence for your operation",
  "AGRO-AI connects production, contracts, costs, market context and risk so your team can see what materially affects margin.",
  "Refresh",
  "Projected revenue",
  "Projected margin",
  "Revenue locked",
  "Revenue exposed",
  "What needs attention",
  "No material commercial exceptions are visible in the current structured position.",
  "Commercial positions",
  "Expected production",
  "Contracted",
  "Exposed",
  "Break-even",
  "Current realizable",
  "Margin",
  "Data health",
  "Sources",
  "Scenario lab",
  "Model the economics. AGRO-AI performs the arithmetic deterministically; the AI layer explains the result.",
  "Market price change",
  "Yield change",
  "FX change",
  "Production cost change",
  "Lock remaining volume now",
  "Run scenario",
  "Scenario result",
  "Revenue impact",
  "Margin impact",
  "Exposure impact",
  "Ask Market Intelligence",
  "Ask about this commercial position. Answers are grounded in the structured calculations shown here.",
  "Ask a question",
  "Analyze",
  "No commercial positions are configured yet.",
  "Connect customer-owned production, cost, inventory, contract and market data through the Market Intelligence API to activate this workspace.",
  "Commercial decision support only. AGRO-AI does not execute trades or provide personalized derivatives instructions.",
  "DEMO DATA",
  "LIVE",
  "DELAYED",
  "STALE",
  "MANUAL",
  "Source health",
  "Some calculations are intentionally suppressed until missing or conflicting inputs are resolved.",
  "Unable to load Market Intelligence.",
  "Retry",
] as const;

type Source = {
  evidence_id?: string;
  provider?: string;
  source_name?: string;
  status?: string;
  observed_at?: string | null;
};

type Position = {
  position_id: string;
  name: string;
  commodity: string;
  season: string;
  country_code: string;
  region?: string | null;
  market_structure: string;
  reporting_currency: string;
  quantity_unit: string;
  expected_production: string;
  contracted_quantity: string;
  uncontracted_quantity: string;
  contracted_percent?: string | null;
  exposed_percent?: string | null;
  current_realizable_price?: string | null;
  break_even_price?: string | null;
  locked_revenue?: string | null;
  exposed_revenue?: string | null;
  projected_revenue?: string | null;
  projected_margin?: string | null;
  projected_margin_percent?: string | null;
  over_contracted?: boolean;
  data_complete?: boolean;
  warnings?: string[];
  missing_inputs?: string[];
  data_health?: { status?: string; confidence?: string; sources?: Source[]; counts?: Record<string, number> };
};

type Overview = {
  module: string;
  generated_at: string;
  position_count: number;
  portfolio_by_reporting_currency: Array<{
    currency: string;
    projected_revenue: string;
    projected_margin: string;
    locked_revenue: string;
    exposed_revenue: string;
    complete_positions: number;
    total_positions: number;
    partial: boolean;
  }>;
  attention: Array<{ importance: string; position_id?: string; title: string; summary: string }>;
  positions: Position[];
  data_health?: { status?: string };
};

type ScenarioResponse = {
  result?: Position;
  delta?: { projected_revenue?: string | null; projected_margin?: string | null; exposed_revenue?: string | null };
  baseline?: Position;
  zero_change_invariant?: boolean;
};

type AskResponse = {
  intelligence?: {
    status?: string;
    summary?: string;
    confidence?: string;
    limitations?: string[];
    model_trace?: { provider?: string; model?: string; grounded?: boolean };
  };
};

function numberValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function money(value: string | null | undefined, currency: string, locale: string) {
  const number = numberValue(value);
  if (number === null) return "—";
  try {
    return new Intl.NumberFormat(locale || "en", {
      style: "currency",
      currency,
      notation: Math.abs(number) >= 1_000_000 ? "compact" : "standard",
      maximumFractionDigits: Math.abs(number) >= 1000 ? 0 : 2,
    }).format(number);
  } catch {
    return `${currency} ${number.toLocaleString()}`;
  }
}

function quantity(value: string | null | undefined, unit: string, locale: string) {
  const number = numberValue(value);
  if (number === null) return "—";
  return `${new Intl.NumberFormat(locale || "en", { maximumFractionDigits: 2, notation: Math.abs(number) >= 1_000_000 ? "compact" : "standard" }).format(number)} ${unit}`;
}

function pct(value: string | null | undefined) {
  const number = numberValue(value);
  return number === null ? "—" : `${number.toFixed(1)}%`;
}

function sourceBadge(status: string | undefined) {
  const state = String(status || "NOT_CONFIGURED").toUpperCase();
  const style = state === "LIVE"
    ? { background: "#E7F4EC", color: "#1F6A45" }
    : state === "DEMO"
      ? { background: "#FFF3D8", color: "#8A5A00" }
      : state === "STALE" || state === "UNAVAILABLE" || state === "NOT_CONFIGURED"
        ? { background: "#FDECE7", color: "#A13F24" }
        : { background: "#EEF1EC", color: "#526057" };
  return { state, style };
}

export function MarketIntelligence() {
  const { locale, tx } = usePortalCopy([], COPY as unknown as string[]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [scenarioBusy, setScenarioBusy] = useState(false);
  const [scenario, setScenario] = useState<ScenarioResponse | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [askBusy, setAskBusy] = useState(false);
  const [assumptions, setAssumptions] = useState({ price_pct: 0, yield_pct: 0, fx_pct: 0, production_cost_pct: 0, sell_pct_now: 0 });

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiClient.get<Overview>("/v1/market-intelligence/overview");
      setOverview(data);
      setSelectedId((current) => current && data.positions.some((item) => item.position_id === current) ? current : data.positions[0]?.position_id || "");
    } catch (cause) {
      const apiError = cause as ApiError;
      setError(apiError.message || tx("Unable to load Market Intelligence."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const selected = useMemo(
    () => overview?.positions.find((item) => item.position_id === selectedId) || overview?.positions[0] || null,
    [overview, selectedId],
  );
  const currency = selected?.reporting_currency || overview?.portfolio_by_reporting_currency[0]?.currency || "USD";
  const portfolio = overview?.portfolio_by_reporting_currency.find((item) => item.currency === currency) || overview?.portfolio_by_reporting_currency[0];
  const hasDemo = Boolean(selected?.data_health?.sources?.some((source) => String(source.status).toUpperCase() === "DEMO"));

  const runScenario = async () => {
    if (!selected) return;
    setScenarioBusy(true);
    setScenario(null);
    try {
      const response = await apiClient.post<any>("/v1/market-intelligence/scenarios", {
        position_id: selected.position_id,
        name: `Portal scenario ${new Date().toISOString()}`,
        ...assumptions,
        freight_per_unit_delta: 0,
        storage_per_unit_delta: 0,
      });
      setScenario({ result: response.result, delta: response.delta, baseline: response.baseline, zero_change_invariant: response.zero_change_invariant });
    } catch (cause) {
      setError((cause as ApiError).message || "Scenario failed");
    } finally {
      setScenarioBusy(false);
    }
  };

  const ask = async () => {
    if (!selected || !question.trim()) return;
    setAskBusy(true);
    setAnswer(null);
    try {
      setAnswer(await apiClient.post<AskResponse>("/v1/market-intelligence/ask", {
        position_id: selected.position_id,
        question: question.trim(),
        language: locale || "en",
      }));
    } catch (cause) {
      setError((cause as ApiError).message || "Intelligence request failed");
    } finally {
      setAskBusy(false);
    }
  };

  if (loading) {
    return <div className="flex min-h-[60vh] items-center justify-center" style={{ color: "#2D6A4F" }}><Loader2 className="h-7 w-7 animate-spin" aria-label={tx("Market Intelligence")} /></div>;
  }

  if (error && !overview) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-14">
        <div className="rounded-2xl border p-7" style={{ background: "#FFFDF8", borderColor: "#E5D8C8" }}>
          <AlertTriangle className="h-6 w-6" style={{ color: "#A13F24" }} />
          <h1 className="mt-4 text-2xl font-semibold" style={{ color: "#10231B" }}>{tx("Unable to load Market Intelligence.")}</h1>
          <p className="mt-2 text-sm leading-6" style={{ color: "#65736A" }}>{error}</p>
          <button className="mt-5 rounded-lg px-4 py-2 text-sm font-semibold text-white" style={{ background: "#10231B" }} onClick={() => void load()}>{tx("Retry")}</button>
        </div>
      </div>
    );
  }

  if (!overview?.position_count) {
    return (
      <div className="mx-auto max-w-5xl px-5 py-10 lg:px-8">
        <Header tx={tx} onRefresh={() => void load()} loading={loading} demo={false} />
        <div className="mt-8 rounded-3xl border p-10 text-center" style={{ background: "#FFFDF8", borderColor: "#D6DDD0" }}>
          <Database className="mx-auto h-8 w-8" style={{ color: "#2D6A4F" }} />
          <h2 className="mt-5 text-2xl font-semibold tracking-tight" style={{ color: "#10231B" }}>{tx("No commercial positions are configured yet.")}</h2>
          <p className="mx-auto mt-3 max-w-2xl text-sm leading-7" style={{ color: "#65736A" }}>{tx("Connect customer-owned production, cost, inventory, contract and market data through the Market Intelligence API to activate this workspace.")}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-16 pt-7 sm:px-6 lg:px-8">
      <Header tx={tx} onRefresh={() => void load()} loading={loading} demo={hasDemo} />

      {error ? <div className="mt-5 rounded-xl border px-4 py-3 text-sm" style={{ borderColor: "#F0C6B8", background: "#FFF5F1", color: "#8B321B" }}>{error}</div> : null}

      <div className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label={tx("Projected revenue")} value={money(portfolio?.projected_revenue, currency, locale)} detail={portfolio?.partial ? tx("Some calculations are intentionally suppressed until missing or conflicting inputs are resolved.") : undefined} />
        <Metric label={tx("Projected margin")} value={money(portfolio?.projected_margin, currency, locale)} valueAccent />
        <Metric label={tx("Revenue locked")} value={money(portfolio?.locked_revenue, currency, locale)} />
        <Metric label={tx("Revenue exposed")} value={money(portfolio?.exposed_revenue, currency, locale)} warning />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
        <section className="rounded-3xl border p-5 sm:p-6" style={{ background: "#FFFDF8", borderColor: "#D6DDD0" }}>
          <div className="flex items-center justify-between gap-4">
            <div><h2 className="text-lg font-semibold" style={{ color: "#10231B" }}>{tx("Commercial positions")}</h2><p className="mt-1 text-xs" style={{ color: "#7B877F" }}>{overview.generated_at}</p></div>
            <select value={selected?.position_id || ""} onChange={(event) => { setSelectedId(event.target.value); setScenario(null); setAnswer(null); }} className="max-w-[260px] rounded-xl border bg-white px-3 py-2 text-sm" style={{ borderColor: "#D6DDD0", color: "#10231B" }}>
              {overview.positions.map((item) => <option key={item.position_id} value={item.position_id}>{item.name}</option>)}
            </select>
          </div>

          {selected ? (
            <div className="mt-6">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full px-2.5 py-1 text-xs font-semibold" style={{ background: "#E7F4EC", color: "#1F6A45" }}>{selected.country_code}</span>
                <span className="text-sm font-semibold" style={{ color: "#10231B" }}>{selected.commodity} · {selected.season}</span>
                <span className="text-xs" style={{ color: "#7B877F" }}>{selected.region || ""}</span>
                <span className="ml-auto rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide" style={{ background: "#F1EFE8", color: "#59665E" }}>{selected.market_structure}</span>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <SmallMetric label={tx("Expected production")} value={quantity(selected.expected_production, selected.quantity_unit, locale)} />
                <SmallMetric label={tx("Contracted")} value={`${quantity(selected.contracted_quantity, selected.quantity_unit, locale)} · ${pct(selected.contracted_percent)}`} />
                <SmallMetric label={tx("Exposed")} value={`${quantity(selected.uncontracted_quantity, selected.quantity_unit, locale)} · ${pct(selected.exposed_percent)}`} warning={numberValue(selected.exposed_percent) !== null && Number(selected.exposed_percent) >= 60} />
                <SmallMetric label={tx("Break-even")} value={money(selected.break_even_price, selected.reporting_currency, locale)} />
                <SmallMetric label={tx("Current realizable")} value={money(selected.current_realizable_price, selected.reporting_currency, locale)} />
                <SmallMetric label={tx("Margin")} value={`${money(selected.projected_margin, selected.reporting_currency, locale)} · ${pct(selected.projected_margin_percent)}`} />
              </div>
              {selected.warnings?.length ? (
                <div className="mt-5 rounded-xl border px-4 py-3" style={{ background: "#FFF7E7", borderColor: "#F1D69B" }}>
                  {selected.warnings.map((warning) => <div key={warning} className="flex items-start gap-2 text-xs leading-5" style={{ color: "#77520E" }}><AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-none" />{warning}</div>)}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>

        <section className="rounded-3xl border p-5 sm:p-6" style={{ background: "#10231B", borderColor: "#19392C", color: "white" }}>
          <div className="flex items-center gap-2"><TrendingUp className="h-5 w-5" style={{ color: "#B6E85B" }} /><h2 className="text-lg font-semibold">{tx("What needs attention")}</h2></div>
          <div className="mt-5 space-y-3">
            {overview.attention.length ? overview.attention.slice(0, 3).map((item, index) => (
              <button key={`${item.title}-${index}`} onClick={() => item.position_id && setSelectedId(item.position_id)} className="w-full rounded-2xl border p-4 text-left transition hover:bg-white/[0.04]" style={{ borderColor: "rgba(255,255,255,0.12)" }}>
                <div className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: item.importance === "high" ? "#F5BC9F" : "#DDEB8F" }}>{item.importance}</div>
                <div className="mt-2 text-sm font-semibold">{item.title}</div>
                <div className="mt-1 text-xs leading-5" style={{ color: "rgba(255,255,255,0.64)" }}>{item.summary}</div>
              </button>
            )) : <p className="text-sm leading-6" style={{ color: "rgba(255,255,255,0.66)" }}>{tx("No material commercial exceptions are visible in the current structured position.")}</p>}
          </div>
        </section>
      </div>

      {selected ? (
        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <section className="rounded-3xl border p-5 sm:p-6" style={{ background: "#FFFDF8", borderColor: "#D6DDD0" }}>
            <div className="flex items-center gap-2"><BarChart3 className="h-5 w-5" style={{ color: "#2D6A4F" }} /><h2 className="text-lg font-semibold" style={{ color: "#10231B" }}>{tx("Scenario lab")}</h2></div>
            <p className="mt-2 text-sm leading-6" style={{ color: "#65736A" }}>{tx("Model the economics. AGRO-AI performs the arithmetic deterministically; the AI layer explains the result.")}</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <ScenarioField label={tx("Market price change")} value={assumptions.price_pct} onChange={(value) => setAssumptions((state) => ({ ...state, price_pct: value }))} suffix="%" />
              <ScenarioField label={tx("Yield change")} value={assumptions.yield_pct} onChange={(value) => setAssumptions((state) => ({ ...state, yield_pct: value }))} suffix="%" />
              <ScenarioField label={tx("FX change")} value={assumptions.fx_pct} onChange={(value) => setAssumptions((state) => ({ ...state, fx_pct: value }))} suffix="%" />
              <ScenarioField label={tx("Production cost change")} value={assumptions.production_cost_pct} onChange={(value) => setAssumptions((state) => ({ ...state, production_cost_pct: value }))} suffix="%" />
              <ScenarioField label={tx("Lock remaining volume now")} value={assumptions.sell_pct_now} onChange={(value) => setAssumptions((state) => ({ ...state, sell_pct_now: Math.max(0, Math.min(100, value)) }))} suffix="%" />
            </div>
            <button onClick={() => void runScenario()} disabled={scenarioBusy} className="mt-5 inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50" style={{ background: "#0D2B1E" }}>
              {scenarioBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}{tx("Run scenario")}
            </button>
            {scenario?.delta ? (
              <div className="mt-5 rounded-2xl border p-4" style={{ borderColor: "#D6DDD0", background: "#F6F4EE" }}>
                <div className="text-xs font-semibold uppercase tracking-[0.14em]" style={{ color: "#2D6A4F" }}>{tx("Scenario result")}</div>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  <SmallMetric label={tx("Revenue impact")} value={money(scenario.delta.projected_revenue, currency, locale)} />
                  <SmallMetric label={tx("Margin impact")} value={money(scenario.delta.projected_margin, currency, locale)} />
                  <SmallMetric label={tx("Exposure impact")} value={money(scenario.delta.exposed_revenue, currency, locale)} />
                </div>
              </div>
            ) : null}
          </section>

          <section className="rounded-3xl border p-5 sm:p-6" style={{ background: "#FFFDF8", borderColor: "#D6DDD0" }}>
            <div className="flex items-center gap-2"><Sparkles className="h-5 w-5" style={{ color: "#2D6A4F" }} /><h2 className="text-lg font-semibold" style={{ color: "#10231B" }}>{tx("Ask Market Intelligence")}</h2></div>
            <p className="mt-2 text-sm leading-6" style={{ color: "#65736A" }}>{tx("Ask about this commercial position. Answers are grounded in the structured calculations shown here.")}</p>
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={tx("Ask a question")} rows={4} className="mt-5 w-full resize-none rounded-2xl border bg-white p-4 text-sm outline-none focus:ring-2" style={{ borderColor: "#D6DDD0", color: "#10231B" }} />
            <button onClick={() => void ask()} disabled={askBusy || !question.trim()} className="mt-3 inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50" style={{ background: "#0D2B1E" }}>
              {askBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{tx("Analyze")}
            </button>
            {answer?.intelligence?.summary ? (
              <div className="mt-5 rounded-2xl border p-4" style={{ borderColor: "#CFE0D6", background: "#F2F8F4" }}>
                <p className="text-sm leading-7" style={{ color: "#183C2C" }}>{answer.intelligence.summary}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-medium uppercase tracking-wide" style={{ color: "#65736A" }}>
                  <span>{answer.intelligence.status}</span>
                  {answer.intelligence.confidence ? <span>· {answer.intelligence.confidence}</span> : null}
                  {answer.intelligence.model_trace?.grounded ? <span>· grounded</span> : null}
                </div>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {selected ? (
        <section className="mt-6 rounded-3xl border p-5 sm:p-6" style={{ background: "#FFFDF8", borderColor: "#D6DDD0" }}>
          <div className="flex items-center gap-2"><Database className="h-5 w-5" style={{ color: "#2D6A4F" }} /><h2 className="text-lg font-semibold" style={{ color: "#10231B" }}>{tx("Data health")}</h2></div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {(selected.data_health?.sources || []).map((source) => {
              const badge = sourceBadge(source.status);
              return <div key={source.evidence_id || `${source.provider}-${source.source_name}`} className="rounded-2xl border p-4" style={{ borderColor: "#E1E5DD", background: "#FCFBF6" }}>
                <div className="flex items-start justify-between gap-3"><div><div className="text-sm font-semibold" style={{ color: "#10231B" }}>{source.source_name || source.provider}</div><div className="mt-1 text-xs" style={{ color: "#7B877F" }}>{source.provider}</div></div><span className="rounded-full px-2 py-1 text-[10px] font-semibold" style={badge.style}>{badge.state}</span></div>
                {source.observed_at ? <div className="mt-3 text-[11px]" style={{ color: "#8B948E" }}>{new Date(source.observed_at).toLocaleString(locale || undefined)}</div> : null}
              </div>;
            })}
          </div>
        </section>
      ) : null}

      <div className="mt-6 flex items-start gap-2 rounded-2xl border px-4 py-3 text-xs leading-5" style={{ borderColor: "#D6DDD0", background: "#F6F4EE", color: "#65736A" }}><ShieldCheck className="mt-0.5 h-4 w-4 flex-none" style={{ color: "#2D6A4F" }} />{tx("Commercial decision support only. AGRO-AI does not execute trades or provide personalized derivatives instructions.")}</div>
    </div>
  );
}

function Header({ tx, onRefresh, loading, demo }: { tx: (value: string) => string; onRefresh: () => void; loading: boolean; demo: boolean }) {
  return <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><div className="flex items-center gap-2"><div className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "#2D6A4F" }}>AGRO-AI</div>{demo ? <span className="rounded-full px-2 py-0.5 text-[9px] font-bold tracking-wide" style={{ background: "#FFF3D8", color: "#8A5A00" }}>{tx("DEMO DATA")}</span> : null}</div><h1 className="mt-2 text-3xl font-semibold tracking-[-0.03em] sm:text-4xl" style={{ color: "#10231B" }}>{tx("Market Intelligence")}</h1><p className="mt-2 max-w-3xl text-sm leading-6" style={{ color: "#65736A" }}>{tx("AGRO-AI connects production, contracts, costs, market context and risk so your team can see what materially affects margin.")}</p></div><button onClick={onRefresh} disabled={loading} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold disabled:opacity-50" style={{ borderColor: "#CBD5CD", background: "#FFFDF8", color: "#10231B" }}><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{tx("Refresh")}</button></div>;
}

function Metric({ label, value, detail, valueAccent, warning }: { label: string; value: string; detail?: string; valueAccent?: boolean; warning?: boolean }) {
  return <div className="rounded-2xl border p-5" style={{ background: "#FFFDF8", borderColor: warning ? "#EBD3B3" : "#D6DDD0" }}><div className="text-xs font-medium" style={{ color: "#7B877F" }}>{label}</div><div className="mt-2 text-2xl font-semibold tracking-tight" style={{ color: warning ? "#8A5A00" : valueAccent ? "#1F6A45" : "#10231B" }}>{value}</div>{detail ? <p className="mt-2 text-[10px] leading-4" style={{ color: "#8B948E" }}>{detail}</p> : null}</div>;
}

function SmallMetric({ label, value, warning }: { label: string; value: string; warning?: boolean }) {
  return <div className="rounded-xl border px-4 py-3" style={{ borderColor: warning ? "#E8C79B" : "#E1E5DD", background: warning ? "#FFF8EA" : "#FCFBF6" }}><div className="text-[10px] font-medium uppercase tracking-[0.12em]" style={{ color: "#7B877F" }}>{label}</div><div className="mt-1.5 text-sm font-semibold" style={{ color: warning ? "#8A5A00" : "#10231B" }}>{value}</div></div>;
}

function ScenarioField({ label, value, onChange, suffix }: { label: string; value: number; onChange: (value: number) => void; suffix: string }) {
  return <label className="block"><span className="text-xs font-medium" style={{ color: "#65736A" }}>{label}</span><div className="mt-1.5 flex items-center rounded-xl border bg-white px-3" style={{ borderColor: "#D6DDD0" }}><input type="number" step="1" value={value} onChange={(event) => onChange(Number(event.target.value) || 0)} className="min-w-0 flex-1 bg-transparent py-2.5 text-sm outline-none" style={{ color: "#10231B" }} /><span className="text-xs" style={{ color: "#8B948E" }}>{suffix}</span></div></label>;
}
