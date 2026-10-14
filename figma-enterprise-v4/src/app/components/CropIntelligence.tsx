import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BarChart3, CalendarDays, ChevronRight, ClipboardCheck, Leaf, Loader2, Plus, RefreshCcw, ShieldAlert, Sprout, TrendingUp } from "lucide-react";
import { Link } from "react-router";
import { apiClient, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalCopy } from "../hooks/usePortalCopy";

type Observation = {
  id: string;
  field_id?: string | null;
  field_name?: string | null;
  block_name?: string | null;
  crop?: string | null;
  summary?: string | null;
  status?: string | null;
  occurred_at?: string | null;
};
type CropProfile = {
  crop_id: string;
  display_name: string;
  maturity_stages: string[];
  maturity_scale?: string | null;
  validation_status?: string;
  degree_day_method?: { method: string; base_c: number; upper_cutoff_c?: number | null } | null;
  notes?: string[];
};
type CropSummary = {
  status?: string;
  summary_status?: string;
  observations_considered?: number;
  open_reviews?: number;
  pending_processing?: number;
  future_dated_excluded?: number;
  next_action?: string | null;
  latest?: {
    observation_id?: string;
    summary?: string;
    block_name?: string | null;
    observed_at?: string | null;
    freshness?: string;
    severity?: string;
    method?: string;
    review_required?: boolean;
    visual?: { analysis_state?: string; crop_condition?: string; confidence_kind?: string } | null;
  } | null;
  comparison?: { basis?: string; spatial_coverage?: string };
  changes?: Array<{ kind?: string; note?: string; trend?: boolean }>;
  timeline?: Array<{ observation_id: string; observed_at?: string; status?: string; event_type?: string }>;
  field_snapshot?: { blocks?: Array<{ block_key: string; block_name?: string | null; severity?: string; observation_id?: string }> };
};
type EstimateResult = Record<string, unknown> & {
  status?: string;
  reasons?: string[];
  interval_reliability?: string;
  extrapolated_visible_objects?: { value?: number; interval_95?: number[] };
  estimated_total_objects?: { value?: number; interval_95?: number[] };
  expected_production_kg?: { value?: number; interval_95?: number[] };
  expected_marketable_kg?: { value?: number; interval_95?: number[] };
  market_yield_proposal?: Record<string, unknown> | null;
};
type StageRow = { id: string; counts: Record<string, string> };
type Pane = "health" | "production" | "harvest" | "maturity";
const COPY = [
  "Crop Intelligence", "Crop and field evidence, production sampling, harvest windows and maturity.",
  "Select a field", "No field observations exist for this workspace yet.", "Create an observation in Field Intelligence to begin.",
  "Crop health", "Production estimate", "Harvest window", "Maturity assessment",
  "Latest assessment", "Observations", "Reviews needed", "Evidence status", "Field evidence",
  "No crop assessment is available for this field.", "No comparable prior assessment", "A difference between observations is not necessarily a trend.",
  "Open observation", "Open Field Intelligence", "View Market Intelligence", "Refresh evidence",
  "Manual sampling inputs are not independently verified.", "Source and sampling design determine whether a block estimate is defensible.",
  "Population units", "Sample counts (one sampled unit per line)", "What is counted?", "Sampling unit", "Count source",
  "Optional calibrated detection fraction", "Its standard error", "Average object weight (kg)", "Weight standard error",
  "Marketable fraction", "Fraction standard error", "Area (hectares)", "Calculate production", "Calculated result",
  "95% interval", "Insufficient evidence", "No automatic changes are made to Market Intelligence.",
  "Review-only Market Intelligence proposal", "Copy proposal", "Copied proposal", "No yield proposal can be made from these inputs.",
  "Crop profile", "Biofix date", "Biofix type", "As-of date", "Degree-day method", "Base temperature (°C)",
  "Upper cutoff (°C)", "Target lower GDD", "Target upper GDD", "Target source", "Target source type",
  "Observed weather source", "Observed weather rows: date, daily high °C, daily low °C",
  "Historical analog weather source", "Historical analog years JSON", "Calculate harvest window",
  "At least five complete, valid historical analog seasons are needed for a projected date window.",
  "Estimated dates are conditional on the supplied weather, biofix, target and historical analogs.",
  "Maturity scale", "Sampling design", "Stage counts by sampled unit", "Sample unit identifier",
  "Add sampled unit", "Remove", "Evaluate maturity", "Unvalidated crop profile",
  "A maturity percentage alone does not establish harvest readiness.", "Results require human review before operational decisions.",
  "Please choose a crop profile that supports maturity stages.", "Use authorized data only.",
  "Sign in and select an operation to see its field evidence.", "Loading crop evidence…",
  "Request failed. Check your inputs and retry.", "Permission or subscription required for this calculation.",
  "A Professional or higher plan is required for crop calculators.", "Upgrade plan",
  "All calculations stay in this session until explicitly reviewed; they never update a field, harvest schedule or contract.",
  "No weather series has been supplied.", "Review the field's observations before relying on the result.",
  "No estimate has been calculated yet.", "Information and limitations", "Open data entry",
  "Crop calculations are experimental until validated against real harvests.",
  "Not a verified crop diagnosis", "Observed", "Calculated", "User supplied", "Review required",
  "Select crop", "Sampled units", "Freshness", "No observations are eligible for comparison.",
  "Random sample", "Systematic sample with random start", "Manual count", "Not independently verified",
  "A minimum of five sampled units is normally required for the scientific estimator.",
  "Changes requiring attention", "Readiness", "Not assessed", "No maturity result yet.", "Simple average", "86/50 adjusted", "YYYY-MM-DD, 25, 10",
  "Results are scoped to the selected field and the signed-in organization.",
  "Weather data must be sourced, and a date window cannot be inferred from missing analog years.",
  "Crop evidence comes from the selected operation.", "Method and evidence provenance"
] as const;
const input = "w-full min-h-[44px] rounded-xl border border-[#CEDBD1] bg-white px-3 py-2 text-sm text-[#142E20] outline-none focus:border-[#2D6A4F] focus:ring-2 focus:ring-[#D8E9D9]";
const box = "rounded-2xl border border-[#DCE5D9] bg-white p-4 sm:p-5";
const num = (value: string) => value.trim() ? Number(value) : undefined;
const details = (value: unknown) => Array.isArray(value) ? value.map(String).join("; ") : String(value ?? "");
const metric = (item: unknown) => {
  if (!item || typeof item !== "object") return null;
  const data = item as { value?: unknown; interval_95?: unknown };
  return data.value === undefined ? null : { value: String(data.value), interval: Array.isArray(data.interval_95) ? data.interval_95.join("–") : null };
};
function ErrorNotice({ message }: { message: string }) {
  return <div role="alert" className="rounded-xl border border-[#E5BDAC] bg-[#FFF4ED] px-4 py-3 text-sm text-[#7C3D25]">{message}</div>;
}
function Label({ title, children }: { title: string; children: React.ReactNode }) {
  return <label className="block space-y-1.5 text-xs font-semibold text-[#53675A]"><span>{title}</span>{children}</label>;
}
function ResultPanel({ title, result, tx }: { title: string; result: Record<string, unknown> | null; tx: (value: string) => string }) {
  if (!result) return null;
  return <section aria-live="polite" className={box}>
    <h3 className="text-base font-semibold text-[#143725]">{title}</h3>
    <div className="mt-2 inline-flex rounded-full bg-[#EFF4E9] px-2.5 py-1 text-xs font-semibold text-[#235A42]">{details(result.status || "unknown").replaceAll("_", " ")}</div>
    {Array.isArray(result.reasons) && result.reasons.length > 0 && <p className="mt-3 text-sm text-[#825225]">{tx("Insufficient evidence")}: {details(result.reasons)}</p>}
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      {(["extrapolated_visible_objects", "estimated_total_objects", "expected_production_kg", "expected_marketable_kg"] as const).map((key) => {
        const data = metric(result[key]);
        return data && <div key={key} className="rounded-xl bg-[#F4F7F1] px-3 py-3"><div className="text-[11px] font-semibold text-[#5B7063]">{key.replaceAll("_", " ")}</div><div className="mt-1 text-xl font-semibold text-[#143725]">{data.value}</div>{data.interval && <div className="mt-1 text-xs text-[#657568]">{tx("95% interval")}: {data.interval}</div>}</div>;
      })}
    </div>
    {result.interval_reliability && <p className="mt-3 text-xs text-[#6A6753]">{tx("Method and evidence provenance")}: {details(result.interval_reliability).replaceAll("_", " ")}</p>}
  </section>;
}
export function CropIntelligence() {
  const { currentOrganization, currentWorkspace, workspaces } = useAuth();
  const { tx } = usePortalCopy([], COPY);
  const workspaceId = currentWorkspace?.id || "";
  const [observations, setObservations] = useState<Observation[]>([]);
  const [profiles, setProfiles] = useState<CropProfile[]>([]);
  const [fieldId, setFieldId] = useState("");
  const [condition, setCondition] = useState<CropSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingCondition, setLoadingCondition] = useState(false);
  const [error, setError] = useState("");
  const [pane, setPane] = useState<Pane>("health");
  const [cropId, setCropId] = useState("");
  const [busy, setBusy] = useState(false);
  const [calculatorError, setCalculatorError] = useState("");
  const [estimate, setEstimate] = useState<EstimateResult | null>(null);
  const [harvest, setHarvest] = useState<Record<string, unknown> | null>(null);
  const [maturity, setMaturity] = useState<Record<string, unknown> | null>(null);
  const [copied, setCopied] = useState(false);
  const [revision, setRevision] = useState(0);
  const [production, setProduction] = useState({
    unit: "tree", object: "fruit", design: "simple_random", population: "", counts: "", source: "manual_count",
    detection: "", detectionSe: "", weight: "", weightSe: "", marketable: "", marketableSe: "", area: ""
  });
  const [harvestForm, setHarvestForm] = useState({
    biofix: "", biofixType: "bloom", asOf: new Date().toISOString().slice(0, 10),
    method: "simple_average", base: "", upper: "", low: "", high: "", targetSource: "",
    targetType: "grower_historical", weatherSource: "", weather: "", analogSource: "", analogs: ""
  });
  const [stageRows, setStageRows] = useState<StageRow[]>(Array.from({ length: 5 }, (_, i) => ({ id: String(i + 1), counts: {} })));
  const fields = useMemo(() => {
    const found = new Map<string, { id: string; label: string; crop: string }>();
    observations.forEach((row) => {
      if (!row.field_id || found.has(row.field_id)) return;
      found.set(row.field_id, { id: row.field_id, label: row.field_name || row.field_id, crop: row.crop || "" });
    });
    return Array.from(found.values());
  }, [observations]);
  const profile = profiles.find((row) => row.crop_id === cropId);
  const selectedField = fields.find((row) => row.id === fieldId);
  const currentWorkspaceAllowed = Boolean(workspaceId && currentOrganization?.id &&
    workspaces.some((row) => row.id === workspaceId && (!row.organization_id || row.organization_id === currentOrganization.id)));

  useEffect(() => {
    let active = true;
    setObservations([]); setCondition(null); setFieldId(""); setError("");
    if (!currentWorkspaceAllowed) return () => { active = false; };
    setLoading(true);
    void Promise.all([
      apiClient.fieldIntelligence.observations("workspace_id=" + encodeURIComponent(workspaceId) + "&limit=500"),
      apiClient.fieldIntelligence.cropProfiles()
    ]).then(([rawObservations, rawProfiles]) => {
      if (!active) return;
      const data = rawObservations as { observations?: Observation[] };
      const cropData = rawProfiles as { profiles?: CropProfile[] };
      setObservations(Array.isArray(data.observations) ? data.observations.filter(row => row && typeof row.id === "string") : []);
      setProfiles(Array.isArray(cropData.profiles) ? cropData.profiles : []);
    }).catch((cause: ApiError) => { if (active) setError(cause.message || tx("Request failed. Check your inputs and retry.")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [workspaceId, currentOrganization?.id, currentWorkspaceAllowed, revision]);

  useEffect(() => {
    if (!fields.some(row => row.id === fieldId)) setFieldId(fields[0]?.id || "");
  }, [fields, fieldId]);

  useEffect(() => {
    if (!cropId && profiles.length) {
      const matched = profiles.find(row => row.display_name.toLowerCase().includes((selectedField?.crop || "").toLowerCase()) && selectedField?.crop);
      setCropId(matched?.crop_id || profiles[0].crop_id);
    }
  }, [cropId, profiles, selectedField?.crop]);

  useEffect(() => {
    let active = true;
    setCondition(null);
    if (!currentWorkspaceAllowed || !fieldId) return () => { active = false; };
    setLoadingCondition(true);
    void apiClient.fieldIntelligence.fieldCropCondition(fieldId, workspaceId).then((raw) => {
      if (active) setCondition(raw as CropSummary);
    }).catch((cause: ApiError) => { if (active) setError(cause.message || tx("Request failed. Check your inputs and retry.")); })
      .finally(() => { if (active) setLoadingCondition(false); });
    return () => { active = false; };
  }, [currentWorkspaceAllowed, fieldId, workspaceId, revision]);

  async function runCalculation(action: () => unknown, kind: Pane) {
    setBusy(true); setCalculatorError("");
    try {
      const value = await action() as Record<string, unknown>;
      if (kind === "production") setEstimate(value as EstimateResult);
      if (kind === "harvest") setHarvest(value);
      if (kind === "maturity") setMaturity(value);
    } catch (cause) {
      const apiError = cause as ApiError;
      setCalculatorError(apiError.status === 402
        ? tx("Permission or subscription required for this calculation.") + " " + tx("A Professional or higher plan is required for crop calculators.")
        : apiError.message || tx("Request failed. Check your inputs and retry."));
    } finally { setBusy(false); }
  }

  function calculateProduction() {
    const counts = production.counts.split(/[\s,;]+/).filter(Boolean).map(Number);
    if (!production.counts.trim() || counts.some(value => (!Number.isFinite(value) || value < 0)) ||
      !Number.isSafeInteger(Number(production.population)) || Number(production.population) < 1) {
      setCalculatorError(tx("Request failed. Check your inputs and retry.")); return;
    }
    const optional = (value: string, se: string) => value.trim() ? { value: num(value), standard_error: Number(se || 0) } : undefined;
    void runCalculation(() => apiClient.fieldIntelligence.productionEstimate({
      unit: production.unit, object_label: production.object, design: production.design,
      population_units: Number(production.population), sample_counts: counts, count_source: production.source,
      detection_rate: optional(production.detection, production.detectionSe),
      unit_weight_kg: optional(production.weight, production.weightSe),
      marketable_fraction: optional(production.marketable, production.marketableSe),
      area_hectares: num(production.area), include_market_proposal: Boolean(production.area && production.weight && production.detection)
    }), "production");
  }

  function calculateHarvest() {
    try {
      const observed = harvestForm.weather.split("\n").map(v => v.trim()).filter(Boolean).map(line => {
        const values = line.split(",").map(v => v.trim());
        if (values.length !== 3 || !values[0] || !Number.isFinite(Number(values[1])) || !Number.isFinite(Number(values[2]))) throw new Error("Invalid weather CSV row");
        return { date: values[0], tmax_c: Number(values[1]), tmin_c: Number(values[2]) };
      });
      const analog_years = harvestForm.analogs.trim() ? JSON.parse(harvestForm.analogs) : {};
      if (!analog_years || typeof analog_years !== "object" || Array.isArray(analog_years)) throw new Error("Invalid analog years");
      void runCalculation(() => apiClient.fieldIntelligence.harvestWindow({
        crop: cropId || undefined, biofix: harvestForm.biofix, biofix_type: harvestForm.biofixType, as_of: harvestForm.asOf,
        degree_day_method: harvestForm.method, base_c: num(harvestForm.base), upper_cutoff_c: num(harvestForm.upper),
        target: harvestForm.low && harvestForm.high && harvestForm.targetSource
          ? { low_gdd: Number(harvestForm.low), high_gdd: Number(harvestForm.high), source: harvestForm.targetSource, source_type: harvestForm.targetType } : undefined,
        observed, analog_years, weather_source: harvestForm.weatherSource || undefined,
        analog_weather_source: harvestForm.analogSource || undefined
      }), "harvest");
    } catch { setCalculatorError(tx("Request failed. Check your inputs and retry.")); }
  }

  function calculateMaturity() {
    if (!profile?.maturity_stages.length) { setCalculatorError(tx("Please choose a crop profile that supports maturity stages.")); return; }
    const samples = stageRows.filter(row => row.id.trim()).map(row => ({
      unit_id: row.id.trim(), counts: Object.fromEntries(profile.maturity_stages.map(stage => [stage, Number(row.counts[stage] || 0)]))
    }));
    if (samples.some(row => Object.values(row.counts).some(value => (!Number.isFinite(value) || value < 0)))) {
      setCalculatorError(tx("Request failed. Check your inputs and retry.")); return;
    }
    void runCalculation(() => apiClient.fieldIntelligence.maturityStages({
      crop: cropId, design: "simple_random", count_source: "manual_count", samples
    }), "maturity");
  }
  const panes: Array<{ id: Pane; title: string; icon: typeof Leaf }> = [
    { id: "health", title: tx("Crop health"), icon: Leaf },
    { id: "production", title: tx("Production estimate"), icon: BarChart3 },
    { id: "harvest", title: tx("Harvest window"), icon: CalendarDays },
    { id: "maturity", title: tx("Maturity assessment"), icon: Sprout }
  ];

  return <div className="min-h-full bg-[#F6F4EE] px-4 py-6 text-[#142E20] sm:px-7 sm:py-8">
    <div className="mx-auto max-w-7xl space-y-5">
      <header className="rounded-[24px] bg-[#102C20] px-5 py-6 text-white sm:px-8 sm:py-8">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[.18em] text-[#A8CFAF]"><Leaf className="h-4 w-4" /> {"AGRO-AI · "} {tx("Crop Intelligence")}</div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">{tx("Crop Intelligence")}</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#D5E3D7]">{tx("Crop and field evidence, production sampling, harvest windows and maturity.")}</p>
          </div>
          <Link to="/field-intelligence" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/25 px-4 text-sm font-semibold text-white hover:bg-white/10">{tx("Open Field Intelligence")} <ArrowRight className="h-4 w-4" /></Link>
        </div>
        <p className="mt-4 text-xs leading-5 text-[#C6D7C9]">{tx("Crop calculations are experimental until validated against real harvests.")}</p>
      </header>

      {!currentWorkspaceAllowed ? <section className={box}><p className="text-sm">{tx("Sign in and select an operation to see its field evidence.")}</p></section> :
        <>
          <section className={box}>
            <div className="flex flex-wrap items-end gap-4">
              <div className="min-w-[220px] flex-1">
                <Label title={tx("Select a field")}>
                  <select className={input} aria-label={tx("Select a field")} value={fieldId} onChange={event => { setFieldId(event.target.value); setError(""); }}>
                    {!fields.length && <option value="">{tx("No field observations exist for this workspace yet.")}</option>}
                    {fields.map(field => <option key={field.id} value={field.id}>{field.label}{field.crop ? " · " + field.crop : ""}</option>)}
                  </select>
                </Label>
              </div>
              <div className="text-sm text-[#647569]">{currentWorkspace?.name || ""}</div>
              <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#CEDBD1] bg-white px-3 text-xs font-semibold text-[#28573B] disabled:opacity-50"><RefreshCcw className="h-4 w-4" />{tx("Refresh evidence")}</button>
            </div>
            {loading && <div role="status" className="mt-4 flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />{tx("Loading crop evidence…")}</div>}
            {!loading && !fields.length && <p className="mt-3 text-sm text-[#647569]">{tx("Create an observation in Field Intelligence to begin.")}</p>}
          </section>
          {error && <ErrorNotice message={error} />}
          <div className="flex flex-wrap gap-2" role="tablist" aria-label={tx("Crop Intelligence")}>
            {panes.map(item => { const Icon = item.icon; return <button type="button" key={item.id} role="tab" aria-selected={pane === item.id} onClick={() => { setPane(item.id); setCalculatorError(""); }} className="inline-flex min-h-[44px] items-center gap-2 rounded-xl px-4 text-sm font-semibold shadow-sm" style={{ background: pane === item.id ? "#173D29" : "#FFFFFF", color: pane === item.id ? "#FFFFFF" : "#315A44" }}><Icon className="h-4 w-4" />{item.title}</button>; })}
          </div>
          {pane === "health" && <div role="tabpanel" className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              {[[tx("Observations"), condition?.observations_considered ?? "—"], [tx("Reviews needed"), condition?.open_reviews ?? "—"], [tx("Evidence status"), condition?.latest?.freshness?.replaceAll("_", " ") || "—"]].map(([name, value]) => <div key={String(name)} className={box}><div className="text-xs font-medium text-[#617465]">{name}</div><div className="mt-2 text-2xl font-semibold text-[#173D29]">{value}</div></div>)}
            </div>
            {loadingCondition ? <p role="status" className="text-sm">{tx("Loading crop evidence…")}</p> :
              !condition?.latest || condition.summary_status === "no_observations" ? <div className={box}>{tx("No crop assessment is available for this field.")}</div> :
                <section className={box}>
                  <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-base font-semibold">{tx("Latest assessment")}</h2><span className="rounded-full bg-[#F1F4E9] px-3 py-1 text-xs font-semibold">{condition.latest?.severity || "unknown"} · {condition.latest?.freshness || "unknown"}</span></div>
                  <p className="mt-3 text-sm leading-6 text-[#425B4D]">{condition.latest?.summary || tx("No crop assessment is available for this field.")}</p>
                  {condition.latest?.visual && <p className="mt-2 text-xs text-[#846431]">{tx("Not a verified crop diagnosis")}: {condition.latest.visual.analysis_state || "unverified"}</p>}
                  {condition.latest?.review_required && <div className="mt-3 flex items-center gap-2 text-xs font-semibold text-[#865D2F]"><ShieldAlert className="h-4 w-4" />{tx("Review required")}</div>}
                  {condition.next_action && <p className="mt-3 rounded-xl bg-[#F6F8F3] px-4 py-3 text-sm">{condition.next_action}</p>}
                  {condition.latest?.observation_id && <Link to="/field-intelligence" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-[#246347]">{tx("Open Field Intelligence")} <ChevronRight className="h-4 w-4" /></Link>}
                </section>}
            {condition?.field_snapshot?.blocks && condition.field_snapshot.blocks.length > 0 && <section className={box}><h2 className="font-semibold">{tx("Field evidence")}</h2><p className="mt-1 text-xs text-[#687A6B]">{tx("A difference between observations is not necessarily a trend.")}</p><div className="mt-3 grid gap-2 sm:grid-cols-2">{condition.field_snapshot.blocks.map((row) => <div key={row.block_key} className="rounded-xl bg-[#F5F8F2] p-3"><div className="font-medium">{row.block_name || row.block_key}</div><div className="text-xs text-[#607667]">{row.severity || "unknown"}</div></div>)}</div></section>}
            {condition?.changes && condition.changes.length > 0 && <section className={box}><h2 className="font-semibold">{tx("Changes requiring attention")}</h2><div className="mt-3 space-y-2">{condition.changes.map((change, index) => <p key={index} className="rounded-lg bg-[#F5F7F2] p-3 text-sm">{change.note || change.kind?.replaceAll("_", " ") || tx("Review required")}{change.trend === false && <span className="ms-2 text-xs text-[#836433]">{tx("A difference between observations is not necessarily a trend.")}</span>}</p>)}</div></section>}
            <p className="text-xs text-[#697C6D]">{tx("Results are scoped to the selected field and the signed-in organization.")}</p>
          </div>}
          {pane !== "health" && <div role="tabpanel" className="space-y-4">
            <section className={box}>
              <div className="grid gap-4">
                <Label title={tx("Crop profile")}>
                  <select className={input} value={cropId} onChange={event => { setCropId(event.target.value); setMaturity(null); setHarvest(null); }} aria-label={tx("Select crop")}>
                    {profiles.map(row => <option key={row.crop_id} value={row.crop_id}>{row.display_name}</option>)}
                  </select>
                </Label>
                {profile && <p className="text-xs text-[#746545]">{tx("Unvalidated crop profile")}: {profile.validation_status || "unvalidated"}{profile.notes?.length ? " · " + profile.notes.join(" ") : ""}</p>}
              </div>
              {pane === "production" && <div className="mt-5 space-y-4">
                <p className="text-sm text-[#607468]">{tx("Source and sampling design determine whether a block estimate is defensible.")}</p>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Label title={tx("Sampling unit")}><input className={input} value={production.unit} onChange={e => setProduction({ ...production, unit: e.target.value })} /></Label>
                  <Label title={tx("What is counted?")}><input className={input} value={production.object} onChange={e => setProduction({ ...production, object: e.target.value })} /></Label>
                  <Label title={tx("Population units")}><input className={input} inputMode="numeric" value={production.population} onChange={e => setProduction({ ...production, population: e.target.value })} /></Label>
                  <Label title={tx("Sampling design")}><select className={input} value={production.design} onChange={e => setProduction({ ...production, design: e.target.value })}><option value="simple_random">{tx("Random sample")}</option><option value="systematic_random_start">{tx("Systematic sample with random start")}</option></select></Label>
                </div>
                <Label title={tx("Sample counts (one sampled unit per line)")}><textarea rows={5} className={input} value={production.counts} onChange={e => setProduction({ ...production, counts: e.target.value })} /></Label>
                <p className="text-xs text-[#637768]">{tx("A minimum of five sampled units is normally required for the scientific estimator.")}</p>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {([["detection", "Optional calibrated detection fraction"], ["detectionSe", "Its standard error"], ["weight", "Average object weight (kg)"], ["weightSe", "Weight standard error"], ["marketable", "Marketable fraction"], ["marketableSe", "Fraction standard error"], ["area", "Area (hectares)"]] as const).map(([key, label]) =>
                    <Label key={key} title={tx(label)}><input className={input} type="number" step="any" min="0" value={production[key]} onChange={e => setProduction({ ...production, [key]: e.target.value })} /></Label>)}
                </div>
                <p className="text-xs text-[#80653C]">{tx("Manual sampling inputs are not independently verified.")}</p>
                <button type="button" disabled={busy || !currentWorkspaceAllowed} onClick={calculateProduction} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#173D29] px-5 text-sm font-semibold text-white disabled:opacity-50">{busy && <Loader2 className="h-4 w-4 animate-spin" />}{tx("Calculate production")}</button>
              </div>}
              {pane === "harvest" && <div className="mt-5 space-y-4">
                <p className="text-sm text-[#607468]">{tx("Estimated dates are conditional on the supplied weather, biofix, target and historical analogs.")}</p>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {([["biofix", "Biofix date"], ["asOf", "As-of date"]] as const).map(([key, label]) => <Label key={key} title={tx(label)}><input type="date" className={input} value={harvestForm[key]} onChange={e => setHarvestForm({ ...harvestForm, [key]: e.target.value })} /></Label>)}
                  <Label title={tx("Biofix type")}><select className={input} value={harvestForm.biofixType} onChange={e => setHarvestForm({ ...harvestForm, biofixType: e.target.value })}>{["planting", "transplant", "emergence", "bud_break", "bloom", "other"].map(x => <option key={x} value={x}>{x.replaceAll("_", " ")}</option>)}</select></Label>
                  <Label title={tx("Degree-day method")}><select className={input} value={harvestForm.method} onChange={e => setHarvestForm({ ...harvestForm, method: e.target.value })}><option value="simple_average">{tx("Simple average")}</option><option value="modified_average_86_50">{tx("86/50 adjusted")}</option></select></Label>
                  {([["base", "Base temperature (°C)"], ["upper", "Upper cutoff (°C)"], ["low", "Target lower GDD"], ["high", "Target upper GDD"]] as const).map(([key, label]) => <Label key={key} title={tx(label)}><input className={input} inputMode="decimal" type="number" step="any" value={harvestForm[key]} onChange={e => setHarvestForm({ ...harvestForm, [key]: e.target.value })} /></Label>)}
                  <Label title={tx("Target source")}><input className={input} value={harvestForm.targetSource} onChange={e => setHarvestForm({ ...harvestForm, targetSource: e.target.value })} /></Label>
                  <Label title={tx("Target source type")}><select className={input} value={harvestForm.targetType} onChange={e => setHarvestForm({ ...harvestForm, targetType: e.target.value })}>{["grower_historical", "supplier_published", "fitted_model"].map(x => <option key={x} value={x}>{x.replaceAll("_", " ")}</option>)}</select></Label>
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-3"><Label title={tx("Observed weather source")}><input className={input} value={harvestForm.weatherSource} onChange={e => setHarvestForm({ ...harvestForm, weatherSource: e.target.value })} /></Label><Label title={tx("Observed weather rows: date, daily high °C, daily low °C")}><textarea rows={6} className={input} placeholder={tx("YYYY-MM-DD, 25, 10")} value={harvestForm.weather} onChange={e => setHarvestForm({ ...harvestForm, weather: e.target.value })} /></Label></div>
                  <div className="space-y-3"><Label title={tx("Historical analog weather source")}><input className={input} value={harvestForm.analogSource} onChange={e => setHarvestForm({ ...harvestForm, analogSource: e.target.value })} /></Label><Label title={tx("Historical analog years JSON")}><textarea rows={6} className={input} placeholder='{"2020":[{"date":"2020-10-01","tmax_c":25,"tmin_c":10}]}' value={harvestForm.analogs} onChange={e => setHarvestForm({ ...harvestForm, analogs: e.target.value })} /></Label></div>
                </div>
                <p className="text-xs text-[#80653C]">{tx("At least five complete, valid historical analog seasons are needed for a projected date window.")}</p>
                <button type="button" disabled={busy || !currentWorkspaceAllowed} onClick={calculateHarvest} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#173D29] px-5 text-sm font-semibold text-white disabled:opacity-50">{tx("Calculate harvest window")}</button>
              </div>}
              {pane === "maturity" && <div className="mt-5 space-y-4">
                <p className="text-sm text-[#607468]">{tx("A maturity percentage alone does not establish harvest readiness.")}</p>
                <p className="text-xs text-[#667C6C]">{tx("Maturity scale")}: {profile?.maturity_scale || tx("Not assessed")}</p>
                {profile?.maturity_stages?.length ? <>
                  <div className="overflow-x-auto rounded-xl border border-[#DCE5D9]"><table className="w-full min-w-[520px] border-collapse text-left text-xs"><thead><tr className="bg-[#F3F7F1]"><th className="p-2">{tx("Sample unit identifier")}</th>{profile.maturity_stages.map(stage => <th className="p-2" key={stage}>{stage.replaceAll("_", " ")}</th>)}<th className="p-2">{tx("Remove")}</th></tr></thead><tbody>{stageRows.map((row, index) => <tr key={index} className="border-t border-[#E3EAE2]"><td className="p-2"><input aria-label={tx("Sample unit identifier") + " " + (index + 1)} className={input} value={row.id} onChange={e => setStageRows(rows => rows.map((item, j) => j === index ? { ...item, id: e.target.value } : item))} /></td>{profile.maturity_stages.map(stage => <td key={stage} className="p-2"><input aria-label={stage + " " + (index + 1)} className={input} type="number" step="1" min="0" value={row.counts[stage] || ""} onChange={e => setStageRows(rows => rows.map((item, j) => j === index ? { ...item, counts: { ...item.counts, [stage]: e.target.value } } : item))} /></td>)}<td className="p-2"><button type="button" className="min-h-11 px-2 text-xs text-[#91523F]" aria-label={tx("Remove")} onClick={() => setStageRows(rows => rows.filter((_, j) => j !== index))}>{tx("Remove")}</button></td></tr>)}</tbody></table></div>
                  <button type="button" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-[#285E40]" onClick={() => setStageRows(rows => [...rows, { id: String(rows.length + 1), counts: {} }])}><Plus className="h-4 w-4" />{tx("Add sampled unit")}</button>
                  <div><button type="button" disabled={busy || !currentWorkspaceAllowed} className="min-h-11 rounded-xl bg-[#173D29] px-5 text-sm font-semibold text-white disabled:opacity-50" onClick={calculateMaturity}>{tx("Evaluate maturity")}</button></div>
                </> : <p className="text-sm text-[#876431]">{tx("Please choose a crop profile that supports maturity stages.")}</p>}
              </div>}
            </section>
            {calculatorError && <ErrorNotice message={calculatorError} />}
            {pane === "production" && <ResultPanel title={tx("Calculated result")} result={estimate} tx={tx} />}
            {pane === "production" && estimate && <section className={box}>
              <h3 className="font-semibold">{tx("Review-only Market Intelligence proposal")}</h3>
              {estimate.market_yield_proposal ? <><pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-[#F4F7F1] p-4 text-xs">{JSON.stringify(estimate.market_yield_proposal, null, 2)}</pre>
                <div className="mt-3 flex flex-wrap items-center gap-3"><button type="button" className="min-h-11 rounded-xl bg-[#173D29] px-4 text-sm font-semibold text-white" onClick={() => { void navigator.clipboard.writeText(JSON.stringify(estimate.market_yield_proposal, null, 2)).then(() => setCopied(true)).catch(() => setCopied(false)); }}>{tx(copied ? "Copied proposal" : "Copy proposal")}</button><Link className="inline-flex items-center gap-1 text-sm font-semibold text-[#286046]" to="/market-intelligence">{tx("View Market Intelligence")}<ArrowRight className="h-4 w-4" /></Link></div></>
                : <p className="mt-3 text-sm text-[#6E735C]">{tx("No yield proposal can be made from these inputs.")}</p>}
              <p className="mt-3 text-xs text-[#786648]">{tx("No automatic changes are made to Market Intelligence.")}</p>
            </section>}
            {pane === "harvest" && harvest && <section aria-live="polite" className={box}><h3 className="font-semibold">{tx("Calculated result")}</h3><p className="mt-3 text-sm">{String(harvest.status || "unknown").replaceAll("_", " ")}</p>{harvest.window && <pre className="mt-3 overflow-x-auto rounded-xl bg-[#F4F7F1] p-4 text-xs">{JSON.stringify(harvest.window, null, 2)}</pre>}{Array.isArray(harvest.reasons) && <p className="mt-3 text-xs">{tx("Insufficient evidence")}: {details(harvest.reasons)}</p>}</section>}
            {pane === "maturity" && maturity && <section aria-live="polite" className={box}><h3 className="font-semibold">{tx("Calculated result")}</h3><p className="mt-3 text-sm">{String(maturity.status || "unknown").replaceAll("_", " ")}</p>{maturity.stage_shares && <div className="mt-4 grid gap-2 sm:grid-cols-3">{Object.entries(maturity.stage_shares as Record<string, { share?: number; interval_95?: number[] }>).map(([stage, data]) => <div key={stage} className="rounded-xl bg-[#F4F7F1] p-3"><div className="text-xs">{stage.replaceAll("_", " ")}</div><div className="mt-1 text-lg font-semibold">{data.share === undefined ? "—" : (data.share * 100).toFixed(1) + "%"}</div>{data.interval_95 && <div className="text-xs">{tx("95% interval")}: {(data.interval_95[0] * 100).toFixed(1)}–{(data.interval_95[1] * 100).toFixed(1)}%</div>}</div>)}</div>}{Array.isArray(maturity.reasons) && <p className="mt-3 text-xs">{tx("Insufficient evidence")}: {details(maturity.reasons)}</p>}</section>}
            <p className="text-xs text-[#617565]">{tx("All calculations stay in this session until explicitly reviewed; they never update a field, harvest schedule or contract.")}</p>
          </div>}
          <div className="flex flex-wrap items-center gap-3 border-t border-[#DCE5D9] pt-4 text-xs text-[#587362]"><ClipboardCheck className="h-4 w-4" />{tx("Results require human review before operational decisions.")}<Link to="/market-intelligence" className="ms-auto inline-flex items-center gap-1 font-semibold text-[#246247]">{tx("View Market Intelligence")}<TrendingUp className="h-4 w-4" /></Link></div>
        </>
      }
    </div>
  </div>;
}
