import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, BookmarkPlus, Check, CircleDot, FileSearch, Loader2, Send, SlidersHorizontal, X } from "lucide-react";
import { apiClient, type ApiError } from "../api/client";
import { usePortalCopy } from "../hooks/usePortalCopy";

// Commercial Intelligence Home: answers "is anything materially affecting my
// business?" first. Every number shown here comes from the deterministic
// engine or governed evidence; nothing is computed in the browser except
// display formatting.

type Reason = Record<string, any> & { code: string };
type Change = {
  id: string;
  position_id: string;
  position_name?: string | null;
  kind: string;
  level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  reasons: Reason[];
  impact: { change?: string; currency?: string; direction?: string; impact_percent_of_revenue?: string | null; drivers?: { driver: string; contribution: string }[] };
  created_at?: string | null;
};
type PositionCard = {
  position_id: string;
  name: string;
  commodity: string;
  season: string;
  country_code: string;
  reporting_currency: string;
  quantity_unit: string;
  marketable_supply?: string | null;
  contracted_percent?: string | null;
  exposed_percent?: string | null;
  locked_revenue?: string | null;
  exposed_revenue?: string | null;
  projected_margin?: string | null;
  break_even_price?: string | null;
  current_realizable_price?: string | null;
  over_contracted?: boolean;
  data_complete?: boolean;
  missing_inputs?: string[];
  price_state?: string;
  fx_state?: string;
};
type Home = {
  status: "attention" | "review" | "steady";
  generated_at: string;
  material_changes: Change[];
  material_change_count: number;
  portfolio_by_reporting_currency: { currency: string; positions: number; locked_revenue: string; exposed_revenue: string; projected_margin: string | null; margin_partial: boolean }[];
  positions: PositionCard[];
  deadlines: { contract_id: string; position_name?: string | null; buyer?: string | null; quantity: string; quantity_unit: string; delivery_start?: string | null }[];
  data_health: { positions_with_stale_or_missing_evidence: { position_id: string; name: string; price_state?: string; fx_state?: string }[]; complete_positions: number; total_positions: number };
};
type Provenance = {
  numbers: Record<string, any>;
  sources: { evidence_id: string; observation_type: string; provider: string; source_name: string; state: string; value?: string | null; redacted?: boolean; unit?: string | null; currency?: string | null; observed_at?: string | null; retrieved_at?: string | null; market_name?: string | null; price_basis?: string | null; attribution?: string | null; automated?: boolean }[];
};
type ScenarioResult = { label: string; status: string; message?: string; result?: PositionCard; delta?: Record<string, string | null> };

const COPY = [
  "Commercial Intelligence",
  "Is anything materially affecting your business?",
  "Material changes need your attention",
  "Changes to review",
  "Nothing material changed",
  "No material changes since the last review.",
  "Revenue locked",
  "Revenue exposed",
  "Projected margin",
  "Margin incomplete",
  "Contracted",
  "Data health",
  "complete positions",
  "Your positions",
  "Marketable supply",
  "Exposed",
  "Break-even",
  "Realizable price",
  "Sources",
  "What if",
  "Save decision",
  "Acknowledge",
  "Acknowledged",
  "Next commercial deadlines",
  "No deliveries scheduled in the next 60 days.",
  "Ask AGRO-AI",
  "Ask about your commercial position, scenarios or sources.",
  "Ask",
  "Close",
  "Where these numbers come from",
  "Origin",
  "Observed",
  "Retrieved",
  "Governed shared evidence",
  "Customer-entered",
  "Deterministic calculation",
  "Missing",
  "Value hidden by data licence",
  "Market price",
  "Yield",
  "FX",
  "Commit more volume",
  "Run",
  "Scenarios are deterministic what-ifs, not forecasts.",
  "Decision",
  "Rationale (optional)",
  "Decision saved with the evidence available today.",
  "Over-contracted",
  "Incomplete inputs",
  "Price evidence",
  "FX evidence",
  "Commercial decision support only. AGRO-AI does not execute trades or provide personalized derivatives instructions.",
  "Unable to load Commercial Intelligence.",
  "Retry",
  "Projected margin changed by {change} {currency}. This equals {percent}% of projected revenue.",
  "Realizable price changed by {percent}%: from {previous} to {price} {currency}.",
  "{quantity} {unit} remains uncontracted ({percent}%), worth {value} {currency} at current prices.",
  "Projected margin turned negative: {value} {currency}.",
  "Realizable price {price} is below break-even {breakeven} {currency}.",
  "Contracted volume {contracted} exceeds marketable supply {supply} {unit}.",
  "Evidence became {state}: {evidence}.",
  "Inputs are incomplete: {inputs}.",
  "Driver",
  "production",
  "price",
  "fx",
  "costs",
  "contracts",
  "other",
  "LOW",
  "MEDIUM",
  "HIGH",
  "CRITICAL",
  "DELAYED",
  "STALE",
  "MANUAL",
  "UNAVAILABLE",
  "NOT_REQUIRED",
] as const;

const LEVEL_STYLE: Record<string, { bg: string; fg: string }> = {
  CRITICAL: { bg: "#FDE4DC", fg: "#8B2A12" },
  HIGH: { bg: "#FFEBD6", fg: "#8A4300" },
  MEDIUM: { bg: "#FFF6D6", fg: "#6E5600" },
  LOW: { bg: "#EEF2EC", fg: "#46574B" },
};
const STATE_STYLE: Record<string, { bg: string; fg: string }> = {
  DELAYED: { bg: "#E7F4EC", fg: "#1F6A45" },
  MANUAL: { bg: "#EAF0F8", fg: "#28466F" },
  STALE: { bg: "#FFF3D8", fg: "#8A5A00" },
  UNAVAILABLE: { bg: "#FDECE7", fg: "#A13F24" },
  NOT_REQUIRED: { bg: "#EEF2EC", fg: "#46574B" },
};

function useFormatters(locale: string) {
  return useMemo(() => {
    const language = !locale || locale === "auto" ? undefined : locale;
    const money = (value: string | null | undefined, currency: string) => {
      if (value === null || value === undefined || value === "") return "—";
      const number = Number(value);
      if (!Number.isFinite(number)) return "—";
      try {
        return new Intl.NumberFormat(language, { style: "currency", currency, maximumFractionDigits: Math.abs(number) >= 1000 ? 0 : 2 }).format(number);
      } catch {
        return `${number.toFixed(2)} ${currency}`;
      }
    };
    const number = (value: string | null | undefined, digits = 1) => {
      if (value === null || value === undefined || value === "") return "—";
      const parsed = Number(value);
      return Number.isFinite(parsed) ? new Intl.NumberFormat(language, { maximumFractionDigits: digits }).format(parsed) : "—";
    };
    const date = (value: string | null | undefined) => {
      if (!value) return "—";
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? "—" : new Intl.DateTimeFormat(language, { dateStyle: "medium" }).format(parsed);
    };
    return { money, number, date };
  }, [locale]);
}

function Badge({ label, style }: { label: string; style: { bg: string; fg: string } }) {
  return <span className="inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide" style={{ background: style.bg, color: style.fg }}>{label}</span>;
}

export function CommercialIntelligenceHome({ canWrite, onOpenOnboarding }: { canWrite: boolean; onOpenOnboarding?: () => void }) {
  const { tx, tf, locale } = usePortalCopy([], COPY as unknown as string[]);
  const fmt = useFormatters(locale);
  const [home, setHome] = useState<Home | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [provenance, setProvenance] = useState<{ position: PositionCard; data: Provenance } | null>(null);
  const [whatIf, setWhatIf] = useState<PositionCard | null>(null);
  const [decisionFor, setDecisionFor] = useState<{ position: PositionCard; change?: Change } | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ summary: string; scenarios?: ScenarioResult[] } | null>(null);
  const [asking, setAsking] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setHome(await apiClient.get<Home>("/v1/market-intelligence/home"));
    } catch (cause) {
      setError((cause as ApiError)?.message || tx("Unable to load Commercial Intelligence."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (home && !home.positions.length && onOpenOnboarding) onOpenOnboarding();
  }, [home, onOpenOnboarding]);

  const reasonText = (reason: Reason): string | null => {
    const ccy = reason.currency || "";
    switch (reason.code) {
      case "economic_change":
        return reason.impact_percent_of_revenue ? tf("Projected margin changed by {change} {currency}. This equals {percent}% of projected revenue.", { change: fmt.number(reason.change, 2), currency: ccy, percent: fmt.number(reason.impact_percent_of_revenue, 2) }) : null;
      case "price_change":
        return tf("Realizable price changed by {percent}%: from {previous} to {price} {currency}.", { percent: fmt.number(reason.percent, 2), previous: fmt.number(reason.from, 2), price: fmt.number(reason.to, 2), currency: ccy });
      case "exposure":
        return tf("{quantity} {unit} remains uncontracted ({percent}%), worth {value} {currency} at current prices.", { quantity: fmt.number(reason.uncontracted_quantity, 0), unit: reason.unit || "", percent: fmt.number(reason.exposed_percent, 1), value: fmt.number(reason.exposed_revenue, 0), currency: ccy });
      case "margin_turned_negative":
        return tf("Projected margin turned negative: {value} {currency}.", { value: fmt.number(reason.projected_margin, 0), currency: ccy });
      case "price_below_break_even":
        return tf("Realizable price {price} is below break-even {breakeven} {currency}.", { price: fmt.number(reason.current_realizable_price, 2), breakeven: fmt.number(reason.break_even_price, 2), currency: ccy });
      case "over_contracted":
        return tf("Contracted volume {contracted} exceeds marketable supply {supply} {unit}.", { contracted: fmt.number(reason.contracted_quantity, 0), supply: fmt.number(reason.marketable_supply, 0), unit: reason.unit || "" });
      case "evidence_degraded":
        return tf("Evidence became {state}: {evidence}.", { state: tx(String(reason.state || "")), evidence: tx(reason.evidence === "fx" ? "FX evidence" : "Price evidence") });
      case "missing_inputs":
        return tf("Inputs are incomplete: {inputs}.", { inputs: (reason.inputs || []).join(", ") });
      default:
        return null;
    }
  };

  const acknowledge = async (change: Change) => {
    await apiClient.post(`/v1/market-intelligence/alerts/${encodeURIComponent(change.id)}/acknowledge`, {});
    await load();
  };

  const openProvenance = async (position: PositionCard) => {
    const data = await apiClient.get<Provenance>(`/v1/market-intelligence/positions/${encodeURIComponent(position.position_id)}/provenance`);
    setProvenance({ position, data });
  };

  const ask = async () => {
    if (!question.trim()) return;
    setAsking(true);
    try {
      const response = await apiClient.post<any>("/v1/market-intelligence/ask", { question: question.trim(), language: locale && locale !== "auto" ? locale : "en" });
      setAnswer({ summary: response?.intelligence?.summary || "", scenarios: response?.scenarios });
    } catch (cause) {
      setAnswer({ summary: (cause as ApiError)?.message || tx("Unable to load Commercial Intelligence.") });
    } finally {
      setAsking(false);
    }
  };

  if (loading && !home) {
    return <div className="flex min-h-[30vh] items-center justify-center text-[#2D6A4F]"><Loader2 className="h-6 w-6 animate-spin" /></div>;
  }
  if (error && !home) {
    return <div className="rounded-2xl border border-[#F0C6B8] bg-[#FFF5F1] p-5 text-sm text-[#8B321B]">{error} <button className="ms-2 font-semibold underline" onClick={() => void load()}>{tx("Retry")}</button></div>;
  }
  if (!home || !home.positions.length) return null;

  const statusCopy = home.status === "attention" ? tx("Material changes need your attention") : home.status === "review" ? tx("Changes to review") : tx("Nothing material changed");
  const statusStyle = home.status === "attention" ? LEVEL_STYLE.HIGH : home.status === "review" ? LEVEL_STYLE.MEDIUM : { bg: "#E7F4EC", fg: "#1F6A45" };

  return (
    <section data-testid="commercial-home" className="space-y-4">
      <div className="rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-4 sm:p-5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#2D6A4F]">{tx("Commercial Intelligence")}</div>
        <h2 className="mt-1 text-lg font-semibold text-[#10231B] sm:text-xl">{tx("Is anything materially affecting your business?")}</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge label={statusCopy} style={statusStyle} />
          <span className="text-xs text-[#65736A]">{fmt.date(home.generated_at)}</span>
        </div>

        <div className="mt-4 space-y-3" data-testid="material-changes">
          {home.material_changes.length ? home.material_changes.map((change) => {
            const position = home.positions.find((item) => item.position_id === change.position_id);
            const lines = change.reasons.map((reason) => reasonText(reason)).filter(Boolean) as string[];
            return (
              <article key={change.id} className="rounded-xl border border-[#E2E7DE] bg-white p-3 sm:p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge label={tx(change.level)} style={LEVEL_STYLE[change.level] || LEVEL_STYLE.LOW} />
                  <span className="min-w-0 break-words text-sm font-semibold text-[#10231B]">{change.position_name}</span>
                </div>
                <ul className="mt-2 space-y-1 text-sm text-[#2F3E35]">
                  {lines.map((line) => <li key={line} className="flex gap-2"><CircleDot className="mt-1 h-3 w-3 shrink-0 text-[#8A9A8F]" /><span className="min-w-0 break-words">{line}</span></li>)}
                </ul>
                {change.impact?.drivers?.length ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {change.impact.drivers.map((driver) => <span key={driver.driver} className="rounded-lg bg-[#F3F1EA] px-2 py-1 text-[11px] text-[#46574B]">{tx(driver.driver)}: {fmt.money(driver.contribution, change.impact.currency || position?.reporting_currency || "USD")}</span>)}
                  </div>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-2">
                  {canWrite ? <button onClick={() => void acknowledge(change)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2C9] bg-white px-3 py-1.5 text-xs font-semibold text-[#234224]"><Check className="h-3.5 w-3.5" />{tx("Acknowledge")}</button> : null}
                  {canWrite && position ? <button onClick={() => setDecisionFor({ position, change })} className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2C9] bg-white px-3 py-1.5 text-xs font-semibold text-[#234224]"><BookmarkPlus className="h-3.5 w-3.5" />{tx("Save decision")}</button> : null}
                  {position ? <button onClick={() => setWhatIf(position)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2C9] bg-white px-3 py-1.5 text-xs font-semibold text-[#234224]"><SlidersHorizontal className="h-3.5 w-3.5" />{tx("What if")}</button> : null}
                </div>
              </article>
            );
          }) : <p className="text-sm text-[#65736A]">{tx("No material changes since the last review.")}</p>}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="portfolio-summary">
        {home.portfolio_by_reporting_currency.map((bucket) => (
          <div key={bucket.currency} className="contents">
            <div className="rounded-2xl border border-[#D6DDD0] bg-white p-4"><div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#65736A]">{tx("Revenue locked")}</div><div className="mt-1 text-xl font-semibold text-[#10231B]">{fmt.money(bucket.locked_revenue, bucket.currency)}</div></div>
            <div className="rounded-2xl border border-[#D6DDD0] bg-white p-4"><div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#65736A]">{tx("Revenue exposed")}</div><div className="mt-1 text-xl font-semibold text-[#10231B]">{fmt.money(bucket.exposed_revenue, bucket.currency)}</div></div>
            <div className="rounded-2xl border border-[#D6DDD0] bg-white p-4"><div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#65736A]">{tx("Projected margin")}</div><div className="mt-1 text-xl font-semibold text-[#10231B]">{bucket.projected_margin === null ? tx("Margin incomplete") : fmt.money(bucket.projected_margin, bucket.currency)}</div></div>
          </div>
        ))}
        <div className="rounded-2xl border border-[#D6DDD0] bg-white p-4"><div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#65736A]">{tx("Data health")}</div><div className="mt-1 text-xl font-semibold text-[#10231B]">{home.data_health.complete_positions}/{home.data_health.total_positions}</div><div className="text-xs text-[#65736A]">{tx("complete positions")}</div></div>
      </div>

      <div className="rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-4 sm:p-5">
        <h3 className="text-sm font-semibold text-[#10231B]">{tx("Your positions")}</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2" data-testid="position-cards">
          {home.positions.map((position) => (
            <article key={position.position_id} className="min-w-0 rounded-xl border border-[#E2E7DE] bg-white p-3 sm:p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0 break-words text-sm font-semibold text-[#10231B]">{position.name}</div>
                <div className="flex flex-wrap gap-1">
                  {position.over_contracted ? <Badge label={tx("Over-contracted")} style={LEVEL_STYLE.HIGH} /> : null}
                  {!position.data_complete ? <Badge label={tx("Incomplete inputs")} style={LEVEL_STYLE.MEDIUM} /> : null}
                  <Badge label={`${tx("Price evidence")}: ${tx(position.price_state || "UNAVAILABLE")}`} style={STATE_STYLE[position.price_state || "UNAVAILABLE"] || STATE_STYLE.UNAVAILABLE} />
                </div>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs sm:grid-cols-3">
                <div><dt className="text-[#65736A]">{tx("Marketable supply")}</dt><dd className="font-semibold text-[#10231B]">{fmt.number(position.marketable_supply, 0)} {position.quantity_unit}</dd></div>
                <div><dt className="text-[#65736A]">{tx("Contracted")}</dt><dd className="font-semibold text-[#10231B]">{fmt.number(position.contracted_percent, 1)}%</dd></div>
                <div><dt className="text-[#65736A]">{tx("Exposed")}</dt><dd className="font-semibold text-[#10231B]">{fmt.money(position.exposed_revenue, position.reporting_currency)}</dd></div>
                <div><dt className="text-[#65736A]">{tx("Projected margin")}</dt><dd className="font-semibold text-[#10231B]">{position.projected_margin ? fmt.money(position.projected_margin, position.reporting_currency) : tx("Margin incomplete")}</dd></div>
                <div><dt className="text-[#65736A]">{tx("Break-even")}</dt><dd className="font-semibold text-[#10231B]">{fmt.number(position.break_even_price, 2)}</dd></div>
                <div><dt className="text-[#65736A]">{tx("Realizable price")}</dt><dd className="font-semibold text-[#10231B]">{fmt.number(position.current_realizable_price, 2)}</dd></div>
              </dl>
              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={() => void openProvenance(position)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2C9] bg-white px-3 py-1.5 text-xs font-semibold text-[#234224]"><FileSearch className="h-3.5 w-3.5" />{tx("Sources")}</button>
                <button onClick={() => setWhatIf(position)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2C9] bg-white px-3 py-1.5 text-xs font-semibold text-[#234224]"><SlidersHorizontal className="h-3.5 w-3.5" />{tx("What if")}</button>
                {canWrite ? <button onClick={() => setDecisionFor({ position })} className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2C9] bg-white px-3 py-1.5 text-xs font-semibold text-[#234224]"><BookmarkPlus className="h-3.5 w-3.5" />{tx("Save decision")}</button> : null}
              </div>
            </article>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-4 sm:p-5">
          <h3 className="text-sm font-semibold text-[#10231B]">{tx("Next commercial deadlines")}</h3>
          {home.deadlines.length ? (
            <ul className="mt-3 space-y-2 text-sm">
              {home.deadlines.map((item) => <li key={item.contract_id} className="flex flex-wrap justify-between gap-2 border-b border-[#EEF1EB] pb-2"><span className="min-w-0 break-words">{item.position_name}{item.buyer ? ` · ${item.buyer}` : ""}</span><span className="text-[#65736A]">{fmt.number(item.quantity, 0)} {item.quantity_unit} · {fmt.date(item.delivery_start)}</span></li>)}
            </ul>
          ) : <p className="mt-2 text-sm text-[#65736A]">{tx("No deliveries scheduled in the next 60 days.")}</p>}
        </div>
        <div className="rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-4 sm:p-5" data-testid="commercial-ask">
          <h3 className="text-sm font-semibold text-[#10231B]">{tx("Ask AGRO-AI")}</h3>
          <p className="mt-1 text-xs text-[#65736A]">{tx("Ask about your commercial position, scenarios or sources.")}</p>
          <div className="mt-3 flex gap-2">
            <input value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void ask(); }} className="min-w-0 flex-1 rounded-xl border border-[#D6DDD0] bg-white px-3 py-2 text-sm" />
            <button onClick={() => void ask()} disabled={asking || !question.trim()} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-[#10231B] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{asking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}{tx("Ask")}</button>
          </div>
          {answer ? <p className="mt-3 whitespace-pre-line break-words text-sm text-[#2F3E35]" data-testid="commercial-answer">{answer.summary}</p> : null}
        </div>
      </div>

      <p className="text-[11px] text-[#7B877F]">{tx("Commercial decision support only. AGRO-AI does not execute trades or provide personalized derivatives instructions.")}</p>
      {notice ? <div className="rounded-xl border border-[#C6DECC] bg-[#F2FAF4] px-4 py-3 text-sm text-[#1F6A45]">{notice}</div> : null}

      {provenance ? <ProvenancePanel tx={tx} fmt={fmt} data={provenance.data} position={provenance.position} onClose={() => setProvenance(null)} /> : null}
      {whatIf ? <WhatIfPanel tx={tx} fmt={fmt} position={whatIf} onClose={() => setWhatIf(null)} /> : null}
      {decisionFor ? <DecisionPanel tx={tx} position={decisionFor.position} change={decisionFor.change} onClose={() => setDecisionFor(null)} onSaved={() => { setDecisionFor(null); setNotice(tx("Decision saved with the evidence available today.")); }} /> : null}
    </section>
  );
}

function Sheet({ title, onClose, children, tx }: { title: string; onClose: () => void; children: React.ReactNode; tx: (value: string) => string }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 sm:items-center" role="dialog" aria-modal="true" aria-label={title}>
      <div className="max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-[#FFFDF8] p-4 shadow-2xl sm:max-w-2xl sm:rounded-2xl sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <h3 className="min-w-0 break-words text-base font-semibold text-[#10231B]">{title}</h3>
          <button onClick={onClose} aria-label={tx("Close")} className="rounded-lg p-1 text-[#46574B]"><X className="h-5 w-5" /></button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}

type Fmt = ReturnType<typeof useFormatters>;

function ProvenancePanel({ tx, fmt, data, position, onClose }: { tx: (value: string) => string; fmt: Fmt; data: Provenance; position: PositionCard; onClose: () => void }) {
  const originLabel = (origin?: string) => origin === "governed_shared_evidence" ? tx("Governed shared evidence") : origin === "customer" ? tx("Customer-entered") : origin === "deterministic_calculation" ? tx("Deterministic calculation") : tx("Missing");
  return (
    <Sheet title={`${tx("Where these numbers come from")} · ${position.name}`} onClose={onClose} tx={tx}>
      <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        {[["Realizable price", data.numbers.current_realizable_price], ["FX", data.numbers.fx_rate_to_reporting]].map(([label, item]: any) => (
          <div key={label} className="rounded-xl border border-[#E2E7DE] bg-white p-3">
            <dt className="text-xs text-[#65736A]">{tx(label)}</dt>
            <dd className="font-semibold text-[#10231B]">{item?.value ? fmt.number(item.value, 4) : "—"}</dd>
            <dd className="text-xs text-[#65736A]">{tx("Origin")}: {originLabel(item?.origin)}{item?.state ? ` · ${tx(String(item.state))}` : ""}</dd>
          </div>
        ))}
      </dl>
      <ul className="mt-4 space-y-2" data-testid="provenance-sources">
        {data.sources.map((source) => (
          <li key={source.evidence_id} className="rounded-xl border border-[#E2E7DE] bg-white p-3 text-xs text-[#2F3E35]">
            <div className="flex flex-wrap items-center gap-2"><Badge label={tx(source.state)} style={STATE_STYLE[source.state] || STATE_STYLE.UNAVAILABLE} /><span className="min-w-0 break-words font-semibold">{source.source_name}</span></div>
            <div className="mt-1 break-words">{source.redacted ? tx("Value hidden by data licence") : `${source.value ?? "—"} ${source.currency ?? ""}${source.unit ? ` / ${source.unit}` : ""}`}{source.market_name ? ` · ${source.market_name}` : ""}</div>
            <div className="mt-1 text-[#65736A]">{tx("Observed")}: {fmt.date(source.observed_at)} · {tx("Retrieved")}: {fmt.date(source.retrieved_at)}</div>
            {source.attribution ? <div className="mt-1 text-[#7B877F]">{source.attribution}</div> : null}
          </li>
        ))}
      </ul>
    </Sheet>
  );
}

function WhatIfPanel({ tx, fmt, position, onClose }: { tx: (value: string) => string; fmt: Fmt; position: PositionCard; onClose: () => void }) {
  const [levers, setLevers] = useState({ price_pct: "-8", yield_pct: "0", fx_pct: "0", sell_pct_now: "0" });
  const [results, setResults] = useState<ScenarioResult[] | null>(null);
  const [running, setRunning] = useState(false);
  const run = async () => {
    setRunning(true);
    try {
      const body = await apiClient.post<{ scenarios: ScenarioResult[] }>("/v1/market-intelligence/scenarios/compare", {
        position_id: position.position_id,
        scenarios: [{ label: `${position.position_id}-what-if`, ...Object.fromEntries(Object.entries(levers).map(([k, v]) => [k, v || "0"])) }],
      });
      setResults(body.scenarios);
    } finally {
      setRunning(false);
    }
  };
  const fields: [keyof typeof levers, string][] = [["price_pct", "Market price"], ["yield_pct", "Yield"], ["fx_pct", "FX"], ["sell_pct_now", "Commit more volume"]];
  return (
    <Sheet title={`${tx("What if")} · ${position.name}`} onClose={onClose} tx={tx}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {fields.map(([key, label]) => (
          <label key={key} className="text-xs text-[#65736A]">{tx(label)} (%)
            <input inputMode="decimal" value={levers[key]} onChange={(event) => setLevers({ ...levers, [key]: event.target.value })} className="mt-1 w-full rounded-xl border border-[#D6DDD0] bg-white px-3 py-2 text-sm text-[#10231B]" />
          </label>
        ))}
      </div>
      <button onClick={() => void run()} disabled={running} className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-[#10231B] px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">{running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}{tx("Run")}</button>
      {(results || []).map((item) => <WhatIfResultView key={item.label} item={item} tx={tx} fmt={fmt} currency={position.reporting_currency} />)}
      <p className="mt-3 text-[11px] text-[#7B877F]">{tx("Scenarios are deterministic what-ifs, not forecasts.")}</p>
    </Sheet>
  );
}

function WhatIfResultView({ item, tx, fmt, currency }: { item: ScenarioResult; tx: (value: string) => string; fmt: Fmt; currency: string }) {
  if (!item.result) return item.message ? <p className="mt-3 text-sm text-[#8B321B]">{item.message}</p> : null;
  return (
    <dl className="mt-4 grid grid-cols-2 gap-2 text-sm" data-testid="what-if-result">
      <div className="rounded-xl border border-[#E2E7DE] bg-white p-3"><dt className="text-xs text-[#65736A]">{tx("Projected margin")}</dt><dd className="font-semibold">{item.result.projected_margin ? fmt.money(item.result.projected_margin, currency) : tx("Margin incomplete")}</dd><dd className="text-xs text-[#65736A]">{item.delta?.projected_margin ? fmt.money(item.delta.projected_margin, currency) : "—"}</dd></div>
      <div className="rounded-xl border border-[#E2E7DE] bg-white p-3"><dt className="text-xs text-[#65736A]">{tx("Revenue exposed")}</dt><dd className="font-semibold">{fmt.money(item.result.exposed_revenue, currency)}</dd><dd className="text-xs text-[#65736A]">{item.delta?.exposed_revenue ? fmt.money(item.delta.exposed_revenue, currency) : "—"}</dd></div>
    </dl>
  );
}

function DecisionPanel({ tx, position, change, onClose, onSaved }: { tx: (value: string) => string; position: PositionCard; change?: Change; onClose: () => void; onSaved: () => void }) {
  const [decision, setDecision] = useState("");
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!decision.trim()) return;
    setSaving(true);
    try {
      await apiClient.post("/v1/market-intelligence/decision-journal", {
        position_id: position.position_id,
        decision: decision.trim(),
        rationale: rationale.trim() || undefined,
        assumptions: change ? { material_change_id: change.id, level: change.level } : {},
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  };
  return (
    <Sheet title={`${tx("Save decision")} · ${position.name}`} onClose={onClose} tx={tx}>
      {change ? <div className="mb-3 flex items-center gap-2 text-xs text-[#8A4300]"><AlertTriangle className="h-3.5 w-3.5" />{tx(change.level)}</div> : null}
      <label className="block text-xs text-[#65736A]">{tx("Decision")}<textarea value={decision} onChange={(event) => setDecision(event.target.value)} rows={2} className="mt-1 w-full rounded-xl border border-[#D6DDD0] bg-white px-3 py-2 text-sm text-[#10231B]" /></label>
      <label className="mt-3 block text-xs text-[#65736A]">{tx("Rationale (optional)")}<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} rows={3} className="mt-1 w-full rounded-xl border border-[#D6DDD0] bg-white px-3 py-2 text-sm text-[#10231B]" /></label>
      <button onClick={() => void save()} disabled={saving || !decision.trim()} className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-[#10231B] px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookmarkPlus className="h-3.5 w-3.5" />}{tx("Save decision")}</button>
    </Sheet>
  );
}
