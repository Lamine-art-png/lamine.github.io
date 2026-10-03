import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Sprout, Trash2 } from "lucide-react";
import { apiClient, type ApiError } from "../api/client";
import { usePortalCopy } from "../hooks/usePortalCopy";

// Customer-language onboarding for Commercial Intelligence. Operators answer
// what they know (crop, place, season, volumes, costs, sales); AGRO-AI infers
// currency, units, market structure and sources. Provider identifiers never
// appear here.

type Inferred = {
  pack_id: string;
  pack_name: string;
  commodity: string;
  commodity_recognised: boolean;
  local_currency: string | null;
  reporting_currency: string;
  quantity_unit: string;
  market_structure: string;
  futures_role: string;
  evidence_plan: { role: string; provider_id: string; description: string; status: string }[];
  warnings: string[];
};
type Field = { id: string; name: string; crop?: string | null; area_hectares?: number | null; operational: boolean };
type ContractRow = { buyer: string; quantity: string; price: string };

const COUNTRIES = ["US", "BR", "AR", "CA", "MX", "FR", "DE", "ES", "IT", "PT", "NL", "BE", "PL", "RO", "HU", "GB", "UA", "AU", "NZ", "IN", "CN", "ID", "TH", "VN", "KE", "SN", "CI", "ML", "BF", "CM", "NG", "GH", "ET", "TZ", "UG", "ZA", "MA", "EG", "CO", "PE", "CL", "PY", "UY"];
const CURRENCIES = ["USD", "EUR", "BRL", "ARS", "CAD", "MXN", "GBP", "PLN", "RON", "HUF", "UAH", "AUD", "NZD", "INR", "CNY", "IDR", "THB", "VND", "KES", "XOF", "XAF", "NGN", "GHS", "ETB", "TZS", "UGX", "ZAR", "MAD", "EGP", "COP", "PEN", "CLP", "PYG", "UYU"];
const UNITS: [string, string][] = [
  ["tonne", "tonnes"], ["kg", "kilograms"], ["bushel", "bushels"], ["pound", "pounds"], ["quintal", "quintals (100 kg)"],
  ["saca_60kg", "60 kg sacks"], ["bag_90kg", "90 kg bags"], ["bag_50kg", "50 kg bags"], ["cwt", "hundredweight (cwt)"],
];

const COPY = [
  "Set up Commercial Intelligence",
  "Answer a few questions about your operation. AGRO-AI infers currency, units, market structure and data sources.",
  "What do you grow?",
  "Country",
  "Region, state or market",
  "Which season?",
  "AGRO-AI will use",
  "Expected production",
  "Unit",
  "Current inventory",
  "Approximate production cost per unit (optional)",
  "Reporting currency",
  "Current local market price (optional)",
  "Leave empty and AGRO-AI will use governed market sources where available.",
  "Exchange rate to reporting currency",
  "No governed exchange-rate source covers this currency. Enter the rate you use, in reporting currency per one unit of local currency.",
  "What have you already sold or committed?",
  "Buyer",
  "Quantity",
  "Price per unit",
  "Add a sale or contract",
  "Remove",
  "Link fields (optional)",
  "Linked field areas let yield updates recalculate your marketable production.",
  "demo or test field",
  "Create commercial position",
  "Creating…",
  "Data sources",
  "Available",
  "Not configured",
  "Customer-supplied",
  "No futures market is required for this crop.",
  "tonnes",
  "kilograms",
  "bushels",
  "pounds",
  "quintals (100 kg)",
  "60 kg sacks",
  "90 kg bags",
  "50 kg bags",
  "hundredweight (cwt)",
  "Request failed. Retry.",
] as const;

export function CommercialOnboarding({ onCreated }: { onCreated: () => void }) {
  const { tx, locale } = usePortalCopy([], COPY as unknown as string[]);
  const language = !locale || locale === "auto" ? undefined : locale;
  const regionNames = useMemo(() => { try { return new Intl.DisplayNames(language, { type: "region" }); } catch { return null; } }, [language]);
  const currencyNames = useMemo(() => { try { return new Intl.DisplayNames(language, { type: "currency" }); } catch { return null; } }, [language]);
  const countries = useMemo(() => COUNTRIES.map((code) => [code, regionNames?.of(code) || code] as const).sort((a, b) => a[1].localeCompare(b[1], language)), [regionNames, language]);

  const [form, setForm] = useState({ crop: "", country_code: "US", region: "", season: String(new Date().getFullYear()), expected_production: "", quantity_unit: "", inventory_quantity: "0", production_cost_per_unit: "", reporting_currency: "", local_price: "", fx_rate_to_reporting: "" });
  const [contracts, setContracts] = useState<ContractRow[]>([]);
  const [fields, setFields] = useState<Field[]>([]);
  const [fieldIds, setFieldIds] = useState<string[]>([]);
  const [inferred, setInferred] = useState<Inferred | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void apiClient.get<{ fields: Field[] }>("/v1/market-intelligence/fields").then((body) => setFields(body.fields || [])).catch(() => setFields([]));
  }, []);

  useEffect(() => {
    if (!form.crop.trim()) { setInferred(null); return; }
    const timer = window.setTimeout(() => {
      void apiClient.post<Inferred>("/v1/market-intelligence/onboarding/infer", {
        crop: form.crop.trim(), country_code: form.country_code, region: form.region.trim() || undefined,
        reporting_currency: form.reporting_currency || undefined,
      }).then((value) => {
        setInferred(value);
        setForm((current) => ({ ...current, quantity_unit: current.quantity_unit || value.quantity_unit, reporting_currency: current.reporting_currency || value.reporting_currency }));
      }).catch(() => setInferred(null));
    }, 350);
    return () => window.clearTimeout(timer);
  }, [form.crop, form.country_code, form.region, form.reporting_currency]);

  const localCurrency = inferred?.local_currency || form.reporting_currency;
  const fxSlots = inferred?.evidence_plan.filter((slot) => slot.role === "fx_rate") || [];
  const needsCustomerFx = Boolean(localCurrency && form.reporting_currency && localCurrency !== form.reporting_currency && !fxSlots.some((slot) => slot.status === "DELAYED"));

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      await apiClient.post("/v1/market-intelligence/onboarding", {
        crop: form.crop.trim(),
        country_code: form.country_code,
        region: form.region.trim() || undefined,
        season: form.season.trim(),
        expected_production: form.expected_production || "0",
        quantity_unit: form.quantity_unit || undefined,
        inventory_quantity: form.inventory_quantity || "0",
        production_cost_per_unit: form.production_cost_per_unit || undefined,
        reporting_currency: form.reporting_currency || undefined,
        local_price: form.local_price || undefined,
        local_price_currency: form.local_price ? localCurrency || undefined : undefined,
        fx_rate_to_reporting: needsCustomerFx && form.fx_rate_to_reporting ? form.fx_rate_to_reporting : undefined,
        contracts: contracts.filter((row) => row.quantity && row.price).map((row) => ({ buyer: row.buyer || undefined, quantity: row.quantity, price: row.price, currency: localCurrency || undefined })),
        field_ids: fieldIds,
      });
      onCreated();
    } catch (cause) {
      setError((cause as ApiError)?.message || tx("Request failed. Retry."));
    } finally {
      setSaving(false);
    }
  };

  const input = "mt-1 w-full rounded-xl border border-[#D6DDD0] bg-white px-3 py-2.5 text-sm text-[#10231B]";
  const label = "block text-xs font-semibold text-[#46574B]";
  const statusLabel = (status: string) => status === "DELAYED" ? tx("Available") : status === "MANUAL" ? tx("Customer-supplied") : tx("Not configured");

  return (
    <section data-testid="commercial-onboarding" className="rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-4 sm:p-6">
      <div className="flex items-center gap-2 text-[#2D6A4F]"><Sprout className="h-5 w-5" /><h2 className="text-lg font-semibold text-[#10231B]">{tx("Set up Commercial Intelligence")}</h2></div>
      <p className="mt-1 text-sm text-[#65736A]">{tx("Answer a few questions about your operation. AGRO-AI infers currency, units, market structure and data sources.")}</p>

      <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className={label}>{tx("What do you grow?")}<input className={input} value={form.crop} onChange={(e) => setForm({ ...form, crop: e.target.value })} /></label>
        <label className={label}>{tx("Country")}<select className={input} value={form.country_code} onChange={(e) => setForm({ ...form, country_code: e.target.value, reporting_currency: "", quantity_unit: "" })}>{countries.map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>
        <label className={label}>{tx("Region, state or market")}<input className={input} value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} /></label>
        <label className={label}>{tx("Which season?")}<input className={input} value={form.season} onChange={(e) => setForm({ ...form, season: e.target.value })} /></label>
      </div>

      {inferred ? (
        <div className="mt-4 rounded-xl border border-[#D9E6DC] bg-[#F4F9F5] p-3 text-sm text-[#1F4A33]" data-testid="onboarding-inference">
          <div className="font-semibold">{tx("AGRO-AI will use")}: {inferred.pack_name}</div>
          <div className="mt-1 text-xs">{currencyNames?.of(inferred.local_currency || inferred.reporting_currency) || inferred.local_currency} · {tx(UNITS.find(([key]) => key === inferred.quantity_unit)?.[1] || inferred.quantity_unit)}</div>
          {inferred.futures_role === "none" ? <div className="mt-1 text-xs">{tx("No futures market is required for this crop.")}</div> : null}
          <div className="mt-2 text-xs font-semibold">{tx("Data sources")}</div>
          <ul className="mt-1 space-y-1 text-xs">{inferred.evidence_plan.map((slot) => <li key={`${slot.role}-${slot.provider_id}`} className="flex flex-wrap justify-between gap-2"><span className="min-w-0 break-words">{slot.description}</span><span className="font-semibold">{statusLabel(slot.status)}</span></li>)}</ul>
        </div>
      ) : null}

      <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <label className={label}>{tx("Expected production")}<input inputMode="decimal" className={input} value={form.expected_production} onChange={(e) => setForm({ ...form, expected_production: e.target.value })} /></label>
        <label className={label}>{tx("Unit")}<select className={input} value={form.quantity_unit} onChange={(e) => setForm({ ...form, quantity_unit: e.target.value })}>{UNITS.map(([key, name]) => <option key={key} value={key}>{tx(name)}</option>)}</select></label>
        <label className={label}>{tx("Current inventory")}<input inputMode="decimal" className={input} value={form.inventory_quantity} onChange={(e) => setForm({ ...form, inventory_quantity: e.target.value })} /></label>
        <label className={label}>{tx("Approximate production cost per unit (optional)")}<input inputMode="decimal" className={input} value={form.production_cost_per_unit} onChange={(e) => setForm({ ...form, production_cost_per_unit: e.target.value })} /></label>
        <label className={label}>{tx("Reporting currency")}<select className={input} value={form.reporting_currency} onChange={(e) => setForm({ ...form, reporting_currency: e.target.value })}>{CURRENCIES.map((code) => <option key={code} value={code}>{currencyNames?.of(code) || code} ({code})</option>)}</select></label>
        <label className={label}>{tx("Current local market price (optional)")}<input inputMode="decimal" className={input} value={form.local_price} onChange={(e) => setForm({ ...form, local_price: e.target.value })} /><span className="mt-1 block font-normal text-[11px] text-[#7B877F]">{tx("Leave empty and AGRO-AI will use governed market sources where available.")}</span></label>
      </div>

      {needsCustomerFx ? (
        <label className={`${label} mt-4`}>{tx("Exchange rate to reporting currency")}<input inputMode="decimal" className={input} value={form.fx_rate_to_reporting} onChange={(e) => setForm({ ...form, fx_rate_to_reporting: e.target.value })} /><span className="mt-1 block font-normal text-[11px] text-[#7B877F]">{tx("No governed exchange-rate source covers this currency. Enter the rate you use, in reporting currency per one unit of local currency.")}</span></label>
      ) : null}

      <div className="mt-5">
        <div className="text-sm font-semibold text-[#10231B]">{tx("What have you already sold or committed?")}</div>
        {contracts.map((row, index) => (
          <div key={index} className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
            <input aria-label={tx("Buyer")} placeholder={tx("Buyer")} className={input} value={row.buyer} onChange={(e) => setContracts(contracts.map((item, i) => i === index ? { ...item, buyer: e.target.value } : item))} />
            <input aria-label={tx("Quantity")} placeholder={tx("Quantity")} inputMode="decimal" className={input} value={row.quantity} onChange={(e) => setContracts(contracts.map((item, i) => i === index ? { ...item, quantity: e.target.value } : item))} />
            <input aria-label={tx("Price per unit")} placeholder={tx("Price per unit")} inputMode="decimal" className={input} value={row.price} onChange={(e) => setContracts(contracts.map((item, i) => i === index ? { ...item, price: e.target.value } : item))} />
            <button onClick={() => setContracts(contracts.filter((_, i) => i !== index))} aria-label={tx("Remove")} className="mt-1 inline-flex items-center justify-center rounded-xl border border-[#E2E7DE] px-3 text-[#8B321B]"><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
        <button onClick={() => setContracts([...contracts, { buyer: "", quantity: "", price: "" }])} className="mt-2 inline-flex items-center gap-1.5 rounded-xl border border-[#C7D2C9] bg-white px-3 py-2 text-xs font-semibold text-[#234224]"><Plus className="h-3.5 w-3.5" />{tx("Add a sale or contract")}</button>
      </div>

      {fields.length ? (
        <div className="mt-5">
          <div className="text-sm font-semibold text-[#10231B]">{tx("Link fields (optional)")}</div>
          <p className="text-xs text-[#65736A]">{tx("Linked field areas let yield updates recalculate your marketable production.")}</p>
          <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
            {fields.map((field) => (
              <li key={field.id}><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={fieldIds.includes(field.id)} onChange={(e) => setFieldIds(e.target.checked ? [...fieldIds, field.id] : fieldIds.filter((id) => id !== field.id))} /><span className="min-w-0 break-words">{field.name}{field.area_hectares ? ` · ${field.area_hectares} ha` : ""}{field.operational ? "" : ` · ${tx("demo or test field")}`}</span></label></li>
            ))}
          </ul>
        </div>
      ) : null}

      {error ? <div className="mt-4 rounded-xl border border-[#F0C6B8] bg-[#FFF5F1] px-3 py-2 text-sm text-[#8B321B]">{error}</div> : null}
      <button onClick={() => void submit()} disabled={saving || !form.crop.trim() || !form.season.trim() || !form.expected_production} className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#10231B] px-4 py-3 text-sm font-semibold text-white disabled:opacity-50 sm:w-auto">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{saving ? tx("Creating…") : tx("Create commercial position")}</button>
    </section>
  );
}
