import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Database, Loader2, Plus, RefreshCw, Save, ShieldCheck, Sparkles, X } from "lucide-react";
import { apiClient, type ApiError } from "../api/client";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { MarketIntelligence } from "./MarketIntelligence";

type PositionSummary = {
  position_id: string;
  name: string;
  commodity: string;
  season: string;
  country_code: string;
  region?: string | null;
  reporting_currency: string;
  quantity_unit: string;
  current_realizable_price?: string | null;
};

type Overview = { position_count: number; positions: PositionSummary[] };
type Capabilities = { can_write?: boolean; role?: string; release_state?: string; cohort?: string };
type ProviderState = { status?: string; source_name?: string; configured?: boolean; coverage?: string; configuration_hint?: string; runtime?: { circuit?: string } };
type ProvidersResponse = { providers?: Record<string, ProviderState> };

const COPY = [
  "Market Intelligence workspace",
  "Configure and refresh the commercial facts behind your crop and market intelligence.",
  "Manage data",
  "Close data manager",
  "Refresh market data",
  "Refreshing…",
  "Add commercial position",
  "Add contract",
  "Update market price",
  "Market data providers",
  "Create position",
  "Create contract",
  "Save price",
  "Position name",
  "Commodity",
  "Season",
  "Country code",
  "Region / state",
  "Market structure",
  "Local currency",
  "Reporting currency",
  "Quantity unit",
  "Expected production",
  "Carry inventory",
  "Production cost per unit",
  "Inventory cost per unit",
  "Current realizable price",
  "Price currency",
  "Freight per unit",
  "Storage per unit",
  "USDA MyMarketNews report slug (optional)",
  "Position",
  "Contract code",
  "Buyer",
  "Quantity",
  "Price",
  "Currency",
  "Observed price",
  "Observed at",
  "No positions yet. Create the first commercial position to activate Market Intelligence.",
  "Reference FX refreshes automatically from the ECB. U.S. cash-market observations use USDA MyMarketNews when a USDA API key is configured.",
  "Government and reference sources are labelled with their actual freshness. AGRO-AI never presents manual or delayed data as live.",
  "Saved.",
] as const;

function decimalInput(value: string, fallback?: string) {
  const raw = value.trim() || fallback;
  if (!raw || !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw)) {
    throw new Error("Enter a valid non-negative decimal value.");
  }
  if (raw.startsWith(".")) return `0${raw}`;
  if (raw.endsWith(".")) return `${raw}0`;
  return raw;
}

function observedAtIso(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new Error("Enter a valid observation date and time.");
  return date.toISOString();
}

function errorMessage(cause: unknown) {
  const error = cause as ApiError;
  return error?.message || "Request failed. Retry.";
}

function localDatetimeInputValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function fieldClass() {
  return "w-full rounded-xl border bg-white px-3 py-2.5 text-sm outline-none transition focus:ring-2 focus:ring-[#2D6A4F]/15";
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-[11px] font-semibold uppercase tracking-[0.12em] text-[#65736A]">{children}</label>;
}

function ProviderBadge({ state }: { state: ProviderState }) {
  const status = String(state.status || "UNKNOWN").toUpperCase();
  const positive = ["LIVE", "DELAYED", "OK"].includes(status);
  const background = positive ? "#E7F4EC" : status === "NOT_CONFIGURED" ? "#FFF3D8" : "#FDECE7";
  const color = positive ? "#1F6A45" : status === "NOT_CONFIGURED" ? "#8A5A00" : "#A13F24";
  return <span className="rounded-full px-2.5 py-1 text-[10px] font-semibold tracking-wide" style={{ background, color }}>{status}</span>;
}

export function MarketIntelligenceV2() {
  const { tx } = usePortalCopy([], COPY as unknown as string[]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [providers, setProviders] = useState<Record<string, ProviderState>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [tab, setTab] = useState<"position" | "contract" | "price" | "providers">("position");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const autoRefreshAttempted = useRef(false);

  const [positionForm, setPositionForm] = useState({
    name: "",
    commodity: "corn",
    season: String(new Date().getFullYear()),
    country_code: "US",
    region: "",
    market_structure: "physical",
    local_currency: "USD",
    reporting_currency: "USD",
    quantity_unit: "bushel",
    expected_production: "",
    inventory_quantity: "0",
    production_cost_per_unit: "",
    inventory_cost_per_unit: "",
    current_realizable_price: "",
    price_currency: "USD",
    freight_per_unit: "0",
    storage_per_unit: "0",
    usda_mmn_slug: "",
  });
  const [contractForm, setContractForm] = useState({
    position_id: "",
    contract_code: "",
    buyer: "",
    quantity: "",
    quantity_unit: "bushel",
    price: "",
    currency: "USD",
  });
  const [priceForm, setPriceForm] = useState({ position_id: "", price: "", currency: "USD", observed_at: localDatetimeInputValue() });

  const canWrite = capabilities?.can_write !== false;
  const selectedForContract = useMemo(() => overview?.positions.find((item) => item.position_id === contractForm.position_id), [overview, contractForm.position_id]);
  const selectedForPrice = useMemo(() => overview?.positions.find((item) => item.position_id === priceForm.position_id), [overview, priceForm.position_id]);

  const loadControlPlane = async () => {
    const [overviewResult, capabilityResult, providerResult] = await Promise.all([
      apiClient.get<Overview>("/v1/market-intelligence/overview"),
      apiClient.get<Capabilities>("/v1/market-intelligence/capabilities"),
      apiClient.get<ProvidersResponse>("/v1/market-intelligence/providers"),
    ]);
    setOverview(overviewResult);
    setCapabilities(capabilityResult);
    setProviders(providerResult.providers || {});
    const first = overviewResult.positions[0];
    setContractForm((current) => current.position_id ? current : { ...current, position_id: first?.position_id || "", quantity_unit: first?.quantity_unit || current.quantity_unit, currency: first?.reporting_currency || current.currency });
    setPriceForm((current) => current.position_id ? current : { ...current, position_id: first?.position_id || "", currency: first?.reporting_currency || current.currency });
    if (!overviewResult.position_count) setManageOpen(true);
  };

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        await loadControlPlane();
      } catch (cause) {
        if (active) setError(errorMessage(cause));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (loading || autoRefreshAttempted.current || !overview?.position_count || !canWrite) return;
    autoRefreshAttempted.current = true;
    void refreshAll(false);
  }, [loading, overview?.position_count, canWrite]);

  const changed = async (message = tx("Saved.")) => {
    await loadControlPlane();
    setRevision((value) => value + 1);
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3500);
  };

  const refreshAll = async (showSpinner = true) => {
    if (!canWrite) return;
    if (showSpinner) setRefreshing(true);
    setError("");
    try {
      await apiClient.post("/v1/market-intelligence/refresh", {});
      await changed("Market data refreshed.");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      if (showSpinner) setRefreshing(false);
    }
  };

  const refreshPositionAfterWrite = async (positionId: string) => {
    try {
      await apiClient.post(`/v1/market-intelligence/positions/${encodeURIComponent(positionId)}/refresh`, {});
      return "";
    } catch (cause) {
      return errorMessage(cause);
    }
  };

  const createPosition = async () => {
    setError("");
    const inventory = decimalInput(positionForm.inventory_quantity, "0");
    const metadata: Record<string, unknown> = { production_cost_behavior: "fixed_total_at_baseline_yield" };
    if (positionForm.inventory_cost_per_unit.trim()) metadata.inventory_cost_per_unit = decimalInput(positionForm.inventory_cost_per_unit);
    if (positionForm.usda_mmn_slug.trim()) metadata.usda_mmn_slug = positionForm.usda_mmn_slug.trim();
    const slug = `${positionForm.commodity}-${positionForm.season}-${Date.now().toString(36)}`.toLowerCase().replace(/[^a-z0-9-]+/g, "-");
    try {
      const created = await apiClient.post<{ id: string }>("/v1/market-intelligence/positions", {
        position_key: slug,
        name: positionForm.name.trim(),
        commodity: positionForm.commodity.trim(),
        season: positionForm.season.trim(),
        country_code: positionForm.country_code.trim().toUpperCase(),
        region: positionForm.region.trim() || null,
        market_structure: positionForm.market_structure,
        local_currency: positionForm.local_currency.trim().toUpperCase(),
        reporting_currency: positionForm.reporting_currency.trim().toUpperCase(),
        quantity_unit: positionForm.quantity_unit,
        expected_production: decimalInput(positionForm.expected_production),
        inventory_quantity: inventory,
        production_cost_per_unit: positionForm.production_cost_per_unit.trim() ? decimalInput(positionForm.production_cost_per_unit) : null,
        current_realizable_price: positionForm.current_realizable_price.trim() ? decimalInput(positionForm.current_realizable_price) : null,
        price_currency: positionForm.price_currency.trim().toUpperCase(),
        freight_per_unit: decimalInput(positionForm.freight_per_unit, "0"),
        storage_per_unit: decimalInput(positionForm.storage_per_unit, "0"),
        metadata,
      });
      const refreshError = await refreshPositionAfterWrite(created.id);
      setManageOpen(false);
      await changed(refreshError
        ? "Commercial position created. Market-source refresh needs attention."
        : "Commercial position created and market sources refreshed.");
      if (refreshError) setError(`The position was saved, but market data refresh did not complete: ${refreshError}`);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  const createContract = async () => {
    if (!contractForm.position_id) return;
    setError("");
    try {
      await apiClient.post("/v1/market-intelligence/contracts", {
        position_id: contractForm.position_id,
        contract_code: contractForm.contract_code.trim(),
        buyer: contractForm.buyer.trim() || null,
        quantity: decimalInput(contractForm.quantity),
        quantity_unit: contractForm.quantity_unit,
        price: decimalInput(contractForm.price),
        currency: contractForm.currency.trim().toUpperCase(),
      });
      const refreshError = await refreshPositionAfterWrite(contractForm.position_id);
      setContractForm((current) => ({ ...current, contract_code: "", buyer: "", quantity: "", price: "" }));
      await changed(refreshError
        ? "Contract added. Market-source refresh needs attention."
        : "Contract added and FX reconciled.");
      if (refreshError) setError(`The contract was saved, but market data refresh did not complete: ${refreshError}`);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  const savePrice = async () => {
    if (!priceForm.position_id || !selectedForPrice) return;
    setError("");
    try {
      const value = decimalInput(priceForm.price);
      const currency = priceForm.currency.trim().toUpperCase();
      await apiClient.post(`/v1/market-intelligence/positions/${encodeURIComponent(priceForm.position_id)}/manual-price`, {
        value,
        currency,
        observed_at: observedAtIso(priceForm.observed_at),
        source_name: "Customer entered market price",
      });
      const refreshError = await refreshPositionAfterWrite(priceForm.position_id);
      setPriceForm((current) => ({ ...current, price: "" }));
      await changed(refreshError
        ? "Market price saved. FX refresh needs attention."
        : "Market price updated and FX refreshed.");
      if (refreshError) setError(`The market price was saved, but market data refresh did not complete: ${refreshError}`);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  if (loading) {
    return <div className="flex min-h-[60vh] items-center justify-center text-[#2D6A4F]"><Loader2 className="h-7 w-7 animate-spin" /></div>;
  }

  return (
    <div>
      <div className="mx-auto max-w-[1500px] px-4 pt-6 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-4 rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] px-5 py-4 shadow-[0_14px_40px_rgba(16,35,27,0.05)] sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#2D6A4F]"><Sparkles className="h-3.5 w-3.5" />{tx("Market Intelligence workspace")}</div>
            <p className="mt-1 text-sm text-[#65736A]">{tx("Configure and refresh the commercial facts behind your crop and market intelligence.")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {canWrite ? <button onClick={() => void refreshAll()} disabled={refreshing || !overview?.position_count} className="inline-flex items-center gap-2 rounded-xl border border-[#C7D2C9] bg-white px-3.5 py-2 text-xs font-semibold text-[#234224] disabled:opacity-50">{refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{refreshing ? tx("Refreshing…") : tx("Refresh market data")}</button> : null}
            {canWrite ? <button onClick={() => setManageOpen((value) => !value)} className="inline-flex items-center gap-2 rounded-xl bg-[#10231B] px-3.5 py-2 text-xs font-semibold text-white"><Database className="h-3.5 w-3.5" />{manageOpen ? tx("Close data manager") : tx("Manage data")}{manageOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}</button> : null}
          </div>
        </div>

        {error ? <div className="mt-3 rounded-xl border border-[#F0C6B8] bg-[#FFF5F1] px-4 py-3 text-sm text-[#8B321B]"><div className="flex items-start justify-between gap-3"><span>{error}</span><button aria-label="Dismiss" onClick={() => setError("")}><X className="h-4 w-4" /></button></div></div> : null}
        {notice ? <div className="mt-3 rounded-xl border border-[#C6DECC] bg-[#F2FAF4] px-4 py-3 text-sm text-[#1F6A45]">{notice}</div> : null}

        {manageOpen && canWrite ? (
          <section className="mt-4 overflow-hidden rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] shadow-[0_18px_60px_rgba(16,35,27,0.06)]">
            <div className="flex flex-wrap gap-1 border-b border-[#E2E7DE] bg-[#F7F5EF] p-2">
              {([
                ["position", tx("Add commercial position")],
                ["contract", tx("Add contract")],
                ["price", tx("Update market price")],
                ["providers", tx("Market data providers")],
              ] as const).map(([key, label]) => <button key={key} onClick={() => setTab(key)} className="rounded-lg px-3 py-2 text-xs font-semibold" style={{ background: tab === key ? "#10231B" : "transparent", color: tab === key ? "#FFFFFF" : "#526057" }}>{label}</button>)}
            </div>
            <div className="p-5 sm:p-6">
              {tab === "position" ? (
                <div>
                  <div className="mb-5"><h2 className="text-lg font-semibold text-[#10231B]">{tx("Add commercial position")}</h2><p className="mt-1 text-sm text-[#65736A]">Production, inventory, costs and price become the deterministic economic baseline.</p></div>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    <div className="xl:col-span-2"><Label>{tx("Position name")}</Label><input className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.name} onChange={(e) => setPositionForm({ ...positionForm, name: e.target.value })} placeholder="2026 Iowa corn" /></div>
                    <div><Label>{tx("Commodity")}</Label><input className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.commodity} onChange={(e) => setPositionForm({ ...positionForm, commodity: e.target.value })} /></div>
                    <div><Label>{tx("Season")}</Label><input className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.season} onChange={(e) => setPositionForm({ ...positionForm, season: e.target.value })} /></div>
                    <div><Label>{tx("Country code")}</Label><input maxLength={2} className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.country_code} onChange={(e) => setPositionForm({ ...positionForm, country_code: e.target.value.toUpperCase() })} /></div>
                    <div><Label>{tx("Region / state")}</Label><input className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.region} onChange={(e) => setPositionForm({ ...positionForm, region: e.target.value })} placeholder="Iowa" /></div>
                    <div><Label>{tx("Market structure")}</Label><select className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.market_structure} onChange={(e) => setPositionForm({ ...positionForm, market_structure: e.target.value })}><option value="physical">Physical</option><option value="hybrid">Physical + benchmark</option><option value="futures">Exchange-linked</option></select></div>
                    <div><Label>{tx("Quantity unit")}</Label><select className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.quantity_unit} onChange={(e) => setPositionForm({ ...positionForm, quantity_unit: e.target.value })}><option value="bushel">Bushel</option><option value="tonne">Metric tonne</option><option value="kg">Kilogram</option><option value="pound">Pound</option></select></div>
                    <div><Label>{tx("Local currency")}</Label><input maxLength={3} className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.local_currency} onChange={(e) => setPositionForm({ ...positionForm, local_currency: e.target.value.toUpperCase() })} /></div>
                    <div><Label>{tx("Reporting currency")}</Label><input maxLength={3} className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.reporting_currency} onChange={(e) => setPositionForm({ ...positionForm, reporting_currency: e.target.value.toUpperCase() })} /></div>
                    <div><Label>{tx("Expected production")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.expected_production} onChange={(e) => setPositionForm({ ...positionForm, expected_production: e.target.value })} placeholder="100000" /></div>
                    <div><Label>{tx("Carry inventory")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.inventory_quantity} onChange={(e) => setPositionForm({ ...positionForm, inventory_quantity: e.target.value })} /></div>
                    <div><Label>{tx("Production cost per unit")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.production_cost_per_unit} onChange={(e) => setPositionForm({ ...positionForm, production_cost_per_unit: e.target.value })} /></div>
                    <div><Label>{tx("Inventory cost per unit")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.inventory_cost_per_unit} onChange={(e) => setPositionForm({ ...positionForm, inventory_cost_per_unit: e.target.value })} /></div>
                    <div><Label>{tx("Current realizable price")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.current_realizable_price} onChange={(e) => setPositionForm({ ...positionForm, current_realizable_price: e.target.value })} /></div>
                    <div><Label>{tx("Price currency")}</Label><input maxLength={3} className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.price_currency} onChange={(e) => setPositionForm({ ...positionForm, price_currency: e.target.value.toUpperCase() })} /></div>
                    <div><Label>{tx("Freight per unit")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.freight_per_unit} onChange={(e) => setPositionForm({ ...positionForm, freight_per_unit: e.target.value })} /></div>
                    <div><Label>{tx("Storage per unit")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.storage_per_unit} onChange={(e) => setPositionForm({ ...positionForm, storage_per_unit: e.target.value })} /></div>
                    <div className="md:col-span-2"><Label>{tx("USDA MyMarketNews report slug (optional)")}</Label><input className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={positionForm.usda_mmn_slug} onChange={(e) => setPositionForm({ ...positionForm, usda_mmn_slug: e.target.value })} placeholder="e.g. 2850" /></div>
                  </div>
                  <button onClick={() => void createPosition()} disabled={!positionForm.name.trim() || !positionForm.expected_production.trim()} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-[#234224] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"><Plus className="h-4 w-4" />{tx("Create position")}</button>
                </div>
              ) : null}

              {tab === "contract" ? (
                <div>
                  <div className="mb-5"><h2 className="text-lg font-semibold text-[#10231B]">{tx("Add contract")}</h2><p className="mt-1 text-sm text-[#65736A]">Add committed commercial volume so locked and exposed revenue reconcile correctly.</p></div>
                  {!overview?.position_count ? <p className="text-sm text-[#65736A]">{tx("No positions yet. Create the first commercial position to activate Market Intelligence.")}</p> : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    <div className="md:col-span-2"><Label>{tx("Position")}</Label><select className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={contractForm.position_id} onChange={(e) => { const position = overview?.positions.find((item) => item.position_id === e.target.value); setContractForm({ ...contractForm, position_id: e.target.value, quantity_unit: position?.quantity_unit || contractForm.quantity_unit, currency: position?.reporting_currency || contractForm.currency }); }}><option value="">Select position</option>{overview?.positions.map((item) => <option key={item.position_id} value={item.position_id}>{item.name}</option>)}</select></div>
                    <div><Label>{tx("Contract code")}</Label><input className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={contractForm.contract_code} onChange={(e) => setContractForm({ ...contractForm, contract_code: e.target.value })} placeholder="PO-2026-001" /></div>
                    <div><Label>{tx("Buyer")}</Label><input className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={contractForm.buyer} onChange={(e) => setContractForm({ ...contractForm, buyer: e.target.value })} /></div>
                    <div><Label>{tx("Quantity")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={contractForm.quantity} onChange={(e) => setContractForm({ ...contractForm, quantity: e.target.value })} /></div>
                    <div><Label>{tx("Quantity unit")}</Label><input className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={contractForm.quantity_unit} onChange={(e) => setContractForm({ ...contractForm, quantity_unit: e.target.value })} /></div>
                    <div><Label>{tx("Price")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={contractForm.price} onChange={(e) => setContractForm({ ...contractForm, price: e.target.value })} /></div>
                    <div><Label>{tx("Currency")}</Label><input maxLength={3} className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={contractForm.currency} onChange={(e) => setContractForm({ ...contractForm, currency: e.target.value.toUpperCase() })} /></div>
                  </div>}
                  {overview?.position_count ? <button onClick={() => void createContract()} disabled={!contractForm.position_id || !contractForm.contract_code.trim() || !contractForm.quantity.trim() || !contractForm.price.trim()} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-[#234224] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"><Plus className="h-4 w-4" />{tx("Create contract")}</button> : null}
                  {selectedForContract ? <p className="mt-3 text-xs text-[#7B877F]">{selectedForContract.commodity} · {selectedForContract.season} · {selectedForContract.quantity_unit}</p> : null}
                </div>
              ) : null}

              {tab === "price" ? (
                <div>
                  <div className="mb-5"><h2 className="text-lg font-semibold text-[#10231B]">{tx("Update market price")}</h2><p className="mt-1 text-sm text-[#65736A]">Use a verified customer price when no configured upstream covers the exact physical market.</p></div>
                  {!overview?.position_count ? <p className="text-sm text-[#65736A]">{tx("No positions yet. Create the first commercial position to activate Market Intelligence.")}</p> : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    <div className="md:col-span-2"><Label>{tx("Position")}</Label><select className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={priceForm.position_id} onChange={(e) => { const position = overview?.positions.find((item) => item.position_id === e.target.value); setPriceForm({ ...priceForm, position_id: e.target.value, currency: position?.reporting_currency || priceForm.currency }); }}><option value="">Select position</option>{overview?.positions.map((item) => <option key={item.position_id} value={item.position_id}>{item.name}</option>)}</select></div>
                    <div><Label>{tx("Observed price")}</Label><input inputMode="decimal" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={priceForm.price} onChange={(e) => setPriceForm({ ...priceForm, price: e.target.value })} /></div>
                    <div><Label>{tx("Currency")}</Label><input maxLength={3} className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={priceForm.currency} onChange={(e) => setPriceForm({ ...priceForm, currency: e.target.value.toUpperCase() })} /></div>
                    <div><Label>{tx("Observed at")}</Label><input type="datetime-local" className={fieldClass()} style={{ borderColor: "#D6DDD0" }} value={priceForm.observed_at} onChange={(e) => setPriceForm({ ...priceForm, observed_at: e.target.value })} /></div>
                  </div>}
                  {overview?.position_count ? <button onClick={() => void savePrice()} disabled={!priceForm.position_id || !priceForm.price.trim()} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-[#234224] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"><Save className="h-4 w-4" />{tx("Save price")}</button> : null}
                  {selectedForPrice ? <p className="mt-3 text-xs text-[#7B877F]">Price applies per {selectedForPrice.quantity_unit}. Current: {selectedForPrice.current_realizable_price || "—"}.</p> : null}
                </div>
              ) : null}

              {tab === "providers" ? (
                <div>
                  <div className="mb-5"><h2 className="text-lg font-semibold text-[#10231B]">{tx("Market data providers")}</h2><p className="mt-1 text-sm text-[#65736A]">{tx("Reference FX refreshes automatically from the ECB. U.S. cash-market observations use USDA MyMarketNews when a USDA API key is configured.")}</p></div>
                  <div className="grid gap-3 md:grid-cols-2">
                    {Object.entries(providers).map(([key, state]) => <div key={key} className="rounded-2xl border border-[#D6DDD0] bg-white p-4"><div className="flex items-start justify-between gap-4"><div><div className="text-sm font-semibold text-[#10231B]">{state.source_name || key}</div><div className="mt-1 text-xs leading-5 text-[#7B877F]">{state.coverage || state.configuration_hint || "Governed provider"}</div></div><ProviderBadge state={state} /></div>{state.runtime?.circuit ? <div className="mt-3 text-[11px] text-[#65736A]">Circuit: {state.runtime.circuit}</div> : null}</div>)}
                  </div>
                  <div className="mt-4 flex items-start gap-3 rounded-2xl bg-[#F3F7F2] p-4 text-xs leading-6 text-[#526057]"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#2D6A4F]" /><span>{tx("Government and reference sources are labelled with their actual freshness. AGRO-AI never presents manual or delayed data as live.")}</span></div>
                </div>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>

      {overview?.position_count ? <MarketIntelligence key={revision} /> : !manageOpen ? (
        <div className="mx-auto max-w-4xl px-5 py-12 text-center"><p className="text-sm text-[#65736A]">{tx("No positions yet. Create the first commercial position to activate Market Intelligence.")}</p></div>
      ) : null}
    </div>
  );
}
