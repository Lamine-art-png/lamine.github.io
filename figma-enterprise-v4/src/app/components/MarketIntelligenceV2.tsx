import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Database, Loader2, Plus, RefreshCw, Save, ShieldCheck, Sparkles, X } from "lucide-react";
import { apiClient, type ApiError } from "../api/client";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { MarketIntelligence } from "./MarketIntelligence";
import { CommercialIntelligenceHome } from "./CommercialIntelligenceHome";
import { CommercialOnboarding } from "./CommercialOnboarding";
import { ACCESS_HINTS, COMMERCIAL_COPY, providerLabel, stateLabel } from "./commercialCopy";

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
type ProviderState = { status?: string; access?: string; source_name?: string; configured?: boolean; newest_observation_at?: string | null };
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
  "Create contract",
  "Save price",
  "Position",
  "Contract code",
  "Buyer",
  "Quantity",
  "Price",
  "Currency",
  "Observed price",
  "Observed at",
  "No positions yet. Create the first commercial position to activate Market Intelligence.",
  "Government and reference sources are labelled with their actual freshness. AGRO-AI never presents manual or delayed data as live.",
  "Saved.",
  "Quantity unit",
  "Data sources",
  "Latest observation",
  "Governed sources refresh automatically on a schedule. Each source shows its real status: available, not configured, or customer-supplied.",
] as const;

function cleanNumber(value: string, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
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

function ProviderBadge({ state, label }: { state: ProviderState; label: string }) {
  const status = String(state.status || "UNKNOWN").toUpperCase();
  const positive = ["LIVE", "DELAYED", "OK"].includes(status);
  const background = positive ? "#E7F4EC" : status === "NOT_CONFIGURED" ? "#FFF3D8" : "#FDECE7";
  const color = positive ? "#1F6A45" : status === "NOT_CONFIGURED" ? "#8A5A00" : "#A13F24";
  return <span className="rounded-full px-2.5 py-1 text-[10px] font-semibold tracking-wide" style={{ background, color }}>{label}</span>;
}

export function MarketIntelligenceV2() {
  const { tx, locale } = usePortalCopy([], [...COPY, ...COMMERCIAL_COPY]);
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

  const createContract = async () => {
    if (!contractForm.position_id) return;
    setError("");
    try {
      await apiClient.post("/v1/market-intelligence/contracts", {
        position_id: contractForm.position_id,
        contract_code: contractForm.contract_code.trim(),
        buyer: contractForm.buyer.trim() || null,
        quantity: cleanNumber(contractForm.quantity),
        quantity_unit: contractForm.quantity_unit,
        price: cleanNumber(contractForm.price),
        currency: contractForm.currency.trim().toUpperCase(),
      });
      await apiClient.post(`/v1/market-intelligence/positions/${encodeURIComponent(contractForm.position_id)}/refresh`, {});
      setContractForm((current) => ({ ...current, contract_code: "", buyer: "", quantity: "", price: "" }));
      await changed("Contract added and FX reconciled.");
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  const savePrice = async () => {
    if (!priceForm.position_id || !selectedForPrice) return;
    setError("");
    try {
      const value = cleanNumber(priceForm.price);
      const currency = priceForm.currency.trim().toUpperCase();
      await apiClient.patch(`/v1/market-intelligence/positions/${encodeURIComponent(priceForm.position_id)}`, {
        current_realizable_price: value,
        price_currency: currency,
      });
      await apiClient.post("/v1/market-intelligence/observations", {
        position_id: priceForm.position_id,
        evidence_id: `manual-price-${priceForm.position_id}-${Date.now()}`,
        observation_type: "cash_price",
        provider: "customer",
        source_name: "Customer entered market price",
        source_status: "MANUAL",
        value,
        unit: `${currency}/${selectedForPrice.quantity_unit}`,
        currency,
        observed_at: new Date(priceForm.observed_at).toISOString(),
        quality: { grade: "customer_entered" },
        licensing: { display_allowed: true },
        metadata: { entry_surface: "enterprise_portal" },
      });
      await apiClient.post(`/v1/market-intelligence/positions/${encodeURIComponent(priceForm.position_id)}/refresh`, {});
      setPriceForm((current) => ({ ...current, price: "" }));
      await changed("Market price updated and FX refreshed.");
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
                ["providers", tx("Data sources")],
              ] as const).map(([key, label]) => <button key={key} onClick={() => setTab(key)} className="rounded-lg px-3 py-2 text-xs font-semibold" style={{ background: tab === key ? "#10231B" : "transparent", color: tab === key ? "#FFFFFF" : "#526057" }}>{label}</button>)}
            </div>
            <div className="p-5 sm:p-6">
              {tab === "position" ? <CommercialOnboarding onCreated={() => { setManageOpen(false); setNotice(tx("Saved.")); setRevision((value) => value + 1); void loadControlPlane(); }} /> : null}

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
                  <div className="mb-5"><h2 className="text-lg font-semibold text-[#10231B]">{tx("Data sources")}</h2><p className="mt-1 text-sm text-[#65736A]">{tx("Governed sources refresh automatically on a schedule. Each source shows its real status: available, not configured, or customer-supplied.")}</p></div>
                  <div className="grid gap-3 md:grid-cols-2">
                    {Object.entries(providers).map(([key, state]) => <div key={key} className="min-w-0 rounded-2xl border border-[#D6DDD0] bg-white p-4"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><div className="break-words text-sm font-semibold text-[#10231B]">{providerLabel(tx, key, state.source_name)}</div>{state.access && ACCESS_HINTS[state.access] && state.status !== "DELAYED" ? <div className="mt-1 break-words text-xs leading-5 text-[#7B877F]">{tx(ACCESS_HINTS[state.access])}</div> : null}{state.newest_observation_at ? <div className="mt-1 text-xs text-[#65736A]">{tx("Latest observation")}: {new Date(state.newest_observation_at).toLocaleDateString(locale && locale !== "auto" ? locale : undefined)}</div> : null}</div><ProviderBadge state={state} label={stateLabel(tx, state.status)} /></div></div>)}
                  </div>
                  <button onClick={() => void refreshAll()} disabled={refreshing || !overview?.position_count} className="mt-4 inline-flex items-center gap-2 rounded-xl border border-[#C7D2C9] bg-white px-3.5 py-2 text-xs font-semibold text-[#234224] disabled:opacity-50">{refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{refreshing ? tx("Refreshing…") : tx("Refresh market data")}</button>
                  <div className="mt-4 flex items-start gap-3 rounded-2xl bg-[#F3F7F2] p-4 text-xs leading-6 text-[#526057]"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#2D6A4F]" /><span>{tx("Government and reference sources are labelled with their actual freshness. AGRO-AI never presents manual or delayed data as live.")}</span></div>
                </div>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>

      {overview?.position_count ? (
        <>
          <div className="mx-auto mt-4 max-w-[1500px] px-4 sm:px-6 lg:px-8"><CommercialIntelligenceHome key={`home-${revision}`} canWrite={canWrite} /></div>
          <MarketIntelligence key={revision} />
        </>
      ) : !manageOpen ? (
        canWrite ? (
          <div className="mx-auto mt-4 max-w-4xl px-4 sm:px-6"><CommercialOnboarding onCreated={() => { setRevision((value) => value + 1); void loadControlPlane(); }} /></div>
        ) : <div className="mx-auto max-w-4xl px-5 py-12 text-center"><p className="text-sm text-[#65736A]">{tx("No positions yet. Create the first commercial position to activate Market Intelligence.")}</p></div>
      ) : null}
    </div>
  );
}
