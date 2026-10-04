import { useMemo } from "react";

// Customer-visible Commercial Intelligence vocabulary, keyed by the stable
// identifiers the API returns (pack_id, provider_id, canonical commodity,
// warning and fact codes). The API ships identifiers, not English prose, so
// every advertised locale renders these through the deterministic catalog.
// tests/unit/test_commercial_copy_contract.py keeps the keys in lockstep with
// the backend registries.

export const PACK_LABELS: Record<string, string> = {
  br_grains_oilseeds: "Brazil grains and oilseeds",
  br_coffee: "Brazil coffee",
  us_row_crops: "United States row crops",
  us_specialty_crops: "United States specialty crops",
  eu_cereals_oilseeds: "European Union cereals and oilseeds",
  au_grains: "Australia grains and oilseeds",
  in_mandi: "India agricultural mandi markets",
  ke_local_markets: "Kenya local physical markets",
  waemu_local_markets: "West African CFA franc local markets",
  global_livestock_dairy: "Livestock and dairy",
  global_physical: "Physical market in any country",
};

export const PROVIDER_LABELS: Record<string, string> = {
  fx_reference: "European Central Bank reference exchange rates",
  bcb_ptax: "Central Bank of Brazil PTAX exchange rate",
  eu_agrifood: "European Commission weekly agri-food prices",
  conab_precos: "Weekly state producer prices from CONAB",
  usda_mymarketnews: "USDA Market News prices",
  usda_nass: "State yield statistics from USDA NASS",
  india_agmarknet: "Daily mandi prices from AGMARKNET",
  cme_futures: "CME Group futures",
  b3_futures: "Brazilian B3 agricultural futures",
  euronext_futures: "Euronext commodity futures",
  asx_futures: "Australian Securities Exchange grain futures",
  ice_futures: "Intercontinental Exchange softs futures",
  cepea_indicators: "Price indicators from CEPEA",
  au_physical_grain: "Australian physical grain prices",
  kenya_kamis: "Kenya agricultural market information",
  kenya_cbk_fx: "Central Bank of Kenya exchange rates",
  local_market_manual: "Your verified local and contract prices",
};

// Why a source is not live, by access model (never a fabricated status).
export const ACCESS_HINTS: Record<string, string> = {
  free_key_required: "Requires a free API key from the publisher. An administrator adds it to enable this source.",
  commercial_license_required: "Requires a commercial market-data licence. Not connected.",
  no_machine_readable_source: "The publisher offers no machine-readable feed. Use verified prices you enter.",
  customer_input: "Prices your team records, labelled as customer-supplied with time and author.",
};

export const COMMODITY_LABELS: Record<string, string> = {
  soybean: "Soybeans",
  corn: "Corn (maize)",
  wheat: "Wheat",
  durum_wheat: "Durum wheat",
  barley: "Barley",
  sorghum: "Sorghum",
  oats: "Oats",
  rice: "Rice",
  rapeseed: "Rapeseed (canola)",
  sunflower: "Sunflower seed",
  cotton: "Cotton",
  coffee: "Coffee",
  cocoa: "Cocoa",
  sugar: "Sugar",
  beans: "Dry beans",
  almonds: "Almonds",
  walnuts: "Walnuts",
  pistachios: "Pistachios",
  groundnuts: "Groundnuts (peanuts)",
  onions: "Onions",
  tomatoes: "Tomatoes",
  mangoes: "Mangoes",
  milk: "Milk",
  cattle: "Cattle",
  hogs: "Hogs",
};

export const WARNING_LABELS: Record<string, string> = {
  cost_fx_missing: "Costs are in another currency and need an exchange rate before margin can be calculated.",
  over_contracted: "Contracted volume exceeds marketable supply.",
  contract_fx_missing: "A contract needs an exchange rate before revenue and margin can be reconciled.",
  market_fx_missing: "The market price needs an exchange rate to your reporting currency.",
  inventory_cost_missing: "Carry inventory needs a cost basis before margin can be calculated.",
  crop_not_recognised: "This crop has no governed market source yet. AGRO-AI will use prices you verify.",
  currency_not_inferred: "Choose the currency you normally sell in.",
  state_not_recognised: "Choose a Brazilian state to use CONAB producer prices.",
  calculation_error: "These inputs cannot be calculated. Review quantities and prices.",
};

export const MISSING_INPUT_LABELS: Record<string, string> = {
  current_realizable_price: "Realizable price",
  market_fx: "Market exchange rate",
  contract_fx: "Contract exchange rate",
  cost_fx: "Cost exchange rate",
  inventory_cost_per_unit: "Inventory cost basis",
};

export const EVIDENCE_LABELS: Record<string, string> = {
  price: "Price",
  fx: "Exchange rate",
  cost_fx: "Cost exchange rate",
};

export const LEVER_LABELS: Record<string, string> = {
  price_pct: "Price",
  basis_per_unit_delta: "Basis",
  yield_pct: "Yield",
  inventory_pct: "Inventory",
  fx_pct: "Exchange rate",
  production_cost_pct: "Costs",
  freight_per_unit_delta: "Freight",
  storage_per_unit_delta: "Storage",
  carry_months: "Carry months",
  carry_cost_per_unit_month: "Carry cost",
  contracted_volume_pct: "Contracted volume",
  sell_pct_now: "Commit more volume",
  sell_price_per_unit: "Sale price",
};

// Evidence freshness, materiality level and attribution driver codes. The API
// returns codes; customers always see these labels in their own language.
export const STATE_LABELS: Record<string, string> = {
  LIVE: "Live",
  DELAYED: "Delayed",
  STALE: "Stale",
  UNAVAILABLE: "Unavailable",
  MANUAL: "Customer-supplied",
  NOT_REQUIRED: "Not required",
  NOT_CONFIGURED: "Not configured",
  DEMO: "Demo data",
  OK: "Available",
  UNKNOWN: "Unknown",
};

export const LEVEL_LABELS: Record<string, string> = { LOW: "Low", MEDIUM: "Medium", HIGH: "High", CRITICAL: "Critical" };

export const DRIVER_LABELS: Record<string, string> = {
  production: "Production",
  price: "Price",
  fx: "Exchange rate",
  costs: "Costs",
  contracts: "Contracts",
  other: "Other",
};

export const ATTENTION_COPY: Record<string, { title: string; summary: string }> = {
  over_contracted: { title: "Contracted volume exceeds expected production", summary: "Projected margin is suppressed until production or contract volume is reconciled." },
  missing_inputs: { title: "Commercial position has missing inputs", summary: "Complete {inputs} before relying on margin calculations." },
  exposure: { title: "Most expected production remains commercially exposed", summary: "Uncontracted under the current position: {percent}%." },
  data_health: { title: "Market data health needs attention", summary: "One or more source observations are stale, unavailable, not configured or missing." },
};

export const IMPORTANCE_LABELS: Record<string, string> = { high: "High priority", medium: "Medium priority", low: "Low priority" };

const FACT_TEMPLATES = {
  exposed: "Commercially exposed: {percent}% of expected production.",
  margin: "Projected margin is {percent}% under the current inputs.",
  position_warnings: "Review these warnings before relying on projected margin: {warnings}",
  missing_data: "More market or cost data is needed for a complete margin view.",
  scenario: "Scenario {label}: projected margin {margin}, change versus today {delta}. Exposed revenue {exposed}.",
  scenario_no_margin: "Scenario {label}: exposed revenue {exposed}, change versus today {delta}. Margin needs complete inputs.",
  not_forecast: "Scenarios are deterministic what-ifs, not forecasts.",
  stale: "Evidence needing attention: {items}.",
  change: "Open material change: {level} on {position}.",
  source: "Current price source: {source}, {state}, observed {observed}.",
  contract_fx: "Contract {code} exchange rate",
  unsupported_language: "Free-text what-if questions are understood in English, Portuguese, Spanish and French. Use What-if to model any scenario in your language.",
} as const;

export const COMMERCIAL_COPY: readonly string[] = [
  ...Object.values(PACK_LABELS),
  ...Object.values(PROVIDER_LABELS),
  ...Object.values(ACCESS_HINTS),
  ...Object.values(COMMODITY_LABELS),
  ...Object.values(WARNING_LABELS),
  ...Object.values(MISSING_INPUT_LABELS),
  ...Object.values(EVIDENCE_LABELS),
  ...Object.values(LEVER_LABELS),
  ...Object.values(FACT_TEMPLATES),
  ...Object.values(ATTENTION_COPY).flatMap((item) => [item.title, item.summary]),
  ...Object.values(IMPORTANCE_LABELS),
  ...Object.values(STATE_LABELS),
  ...Object.values(LEVEL_LABELS),
  ...Object.values(DRIVER_LABELS),
];

type Translate = (value: string) => string;
type Format = (template: string, values: Record<string, string | number | undefined>) => string;
type NumberFormat = (value: string | number | null | undefined, digits?: number) => string;
export type FactFormatters = { number: NumberFormat; money: (value: string | number | null | undefined, currency: string) => string };

export function stateLabel(tx: Translate, code?: string | null): string {
  const key = String(code || "UNKNOWN").toUpperCase();
  return tx(STATE_LABELS[key] || STATE_LABELS.UNKNOWN);
}

export function levelLabel(tx: Translate, code?: string | null): string {
  const key = String(code || "").toUpperCase();
  return LEVEL_LABELS[key] ? tx(LEVEL_LABELS[key]) : key;
}

export function driverLabel(tx: Translate, code: string): string {
  return DRIVER_LABELS[code] ? tx(DRIVER_LABELS[code]) : code;
}

export function packLabel(tx: Translate, packId?: string | null): string {
  return packId && PACK_LABELS[packId] ? tx(PACK_LABELS[packId]) : tx(PACK_LABELS.global_physical);
}

export function providerLabel(tx: Translate, providerId?: string | null, fallback?: string | null): string {
  if (providerId && PROVIDER_LABELS[providerId]) return tx(PROVIDER_LABELS[providerId]);
  // Customer-entered source names are user content, shown as written.
  return fallback || providerId || "";
}

export function warningLabel(tx: Translate, code: string): string {
  return WARNING_LABELS[code] ? tx(WARNING_LABELS[code]) : code;
}

export function missingInputLabel(tx: Translate, code: string): string {
  return MISSING_INPUT_LABELS[code] ? tx(MISSING_INPUT_LABELS[code]) : code;
}

export function evidenceLabel(tx: Translate, tf: Format, key: string): string {
  if (key.startsWith("contract_fx:")) return tf(FACT_TEMPLATES.contract_fx, { code: key.slice("contract_fx:".length) });
  return EVIDENCE_LABELS[key] ? tx(EVIDENCE_LABELS[key]) : key;
}

export function scenarioLabel(tx: Translate, number: NumberFormat, assumptions: Record<string, string>): string {
  const parts = Object.entries(assumptions || {})
    .filter(([lever, value]) => LEVER_LABELS[lever] && value !== "" && Number(value) !== 0)
    .map(([lever, value]) => {
      const amount = Number(value);
      const percent = lever.endsWith("_pct");
      const sign = lever !== "sell_pct_now" && amount > 0 ? "+" : "";
      return `${tx(LEVER_LABELS[lever])} ${sign}${number(amount, 2)}${percent ? "%" : ""}`;
    });
  return parts.join(", ") || "—";
}

export type DeterministicFact = { code: string; params: Record<string, any> };

// Renders the deterministic Ask answer in the viewer's locale from the API's
// language-neutral facts (numbers come from the deterministic engine).
export function renderFacts(tx: Translate, tf: Format, fmt: FactFormatters, facts: DeterministicFact[]): string[] {
  const { number } = fmt;
  const money = (value: unknown, currency: string) => (value == null || value === "" ? "—" : fmt.money(value as string, currency));
  const lines: string[] = [];
  for (const fact of facts || []) {
    const p = fact.params || {};
    switch (fact.code) {
      case "exposed":
      case "margin":
        lines.push(tf(FACT_TEMPLATES[fact.code], { percent: number(p.percent, 2) }));
        break;
      case "position_warnings":
        lines.push(tf(FACT_TEMPLATES.position_warnings, { warnings: (p.codes || []).map((code: string) => warningLabel(tx, code)).join(" ") }));
        break;
      case "missing_data":
      case "not_forecast":
        lines.push(tx(FACT_TEMPLATES[fact.code]));
        break;
      case "scenario":
        lines.push(tf(FACT_TEMPLATES.scenario, { label: scenarioLabel(tx, number, p.assumptions), margin: money(p.projected_margin, p.currency), delta: money(p.delta, p.currency), exposed: money(p.exposed_revenue, p.currency) }));
        break;
      case "scenario_no_margin":
        lines.push(tf(FACT_TEMPLATES.scenario_no_margin, { label: scenarioLabel(tx, number, p.assumptions), delta: money(p.delta, p.currency), exposed: money(p.exposed_revenue, p.currency) }));
        break;
      case "stale":
        lines.push(tf(FACT_TEMPLATES.stale, { items: (p.items || []).map((item: { evidence: string; state: string }) => `${evidenceLabel(tx, tf, item.evidence)}: ${stateLabel(tx, item.state)}`).join(", ") }));
        break;
      case "change":
        lines.push(tf(FACT_TEMPLATES.change, { level: levelLabel(tx, p.level), position: p.position }));
        break;
      case "source":
        lines.push(tf(FACT_TEMPLATES.source, { source: providerLabel(tx, p.provider, p.source_name), state: stateLabel(tx, p.state), observed: p.observed }));
        break;
      default:
        break;
    }
  }
  return lines;
}

export function attentionText(tx: Translate, tf: Format, number: NumberFormat, item: { code?: string; params?: Record<string, any>; title: string; summary: string }): { title: string; summary: string } {
  const copy = item.code ? ATTENTION_COPY[item.code] : undefined;
  if (!copy) return { title: item.title, summary: item.summary };
  const params = item.params || {};
  return {
    title: tx(copy.title),
    summary: tf(copy.summary, {
      inputs: (params.inputs || []).map((code: string) => missingInputLabel(tx, code)).join(", "),
      percent: number(params.percent, 1),
    }),
  };
}

export function unsupportedScenarioLanguage(tx: Translate): string {
  return tx(FACT_TEMPLATES.unsupported_language);
}

// Picks what to show for an Ask answer: model answers are already in the
// requested language; deterministic answers are rendered here from facts so
// no advertised locale silently receives English.
export function answerText(tx: Translate, tf: Format, fmt: FactFormatters, intelligence: Record<string, any> | null | undefined): string {
  if (!intelligence) return "";
  if (intelligence.status === "deterministic" && Array.isArray(intelligence.facts)) {
    return renderFacts(tx, tf, fmt, intelligence.facts).join(" ");
  }
  return String(intelligence.summary || "");
}

// Locale-aware number, money and date formatting shared by Commercial
// Intelligence views (Intl only; values come from the API unchanged).
export function useCommercialFormatters(locale: string) {
  return useMemo(() => {
    const language = !locale || locale === "auto" ? undefined : locale;
    const money = (value: string | number | null | undefined, currency: string) => {
      if (value === null || value === undefined || value === "") return "—";
      const amount = Number(value);
      if (!Number.isFinite(amount)) return "—";
      try {
        return new Intl.NumberFormat(language, { style: "currency", currency, maximumFractionDigits: Math.abs(amount) >= 1000 ? 0 : 2 }).format(amount);
      } catch {
        return `${amount.toFixed(2)} ${currency}`;
      }
    };
    const number = (value: string | number | null | undefined, digits = 1) => {
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
