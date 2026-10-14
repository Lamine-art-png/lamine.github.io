import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { AlertTriangle, ArrowRight, CalendarRange, Calculator, Info, Loader2, Lock, Plus, ShieldCheck, Trash2, Upload } from "lucide-react";
import { apiClient, type ApiError } from "../api/client";
import type { CropCopyKey } from "./cropIntelligenceCopy";
import {
  ACTION_KEYS, STAGE_KEYS, groupAnalogSeasons, invalidCount, invalidStratum, isShare, type CropText, observedWindow, optionalNumber, parseNumberList, parseWeatherCsv,
  reasonCopyKeys, storeMarketHandoff, type CropProfile, type Interval, type OverviewField, type WeatherDay,
} from "./cropIntelligenceModel";

export type { CropText } from "./cropIntelligenceModel";

type Result = Record<string, any>;

const INPUT = "min-h-[44px] w-full rounded-xl border border-[#D6DDD0] bg-white px-3 text-[14px] outline-none focus:ring-2 focus:ring-[#2D6A4F]/20";

function FieldLabel({ htmlFor, children, optional, text }: { htmlFor: string; children: ReactNode; optional?: boolean; text: CropText }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-2 text-[12px] font-semibold text-[#3F5247]">
      <span>{children}</span>
      <span className="text-[11px] font-normal text-[#7B877F]">{optional ? text.c("optional") : text.c("required")}</span>
    </label>
  );
}

function Panel({ children }: { children: ReactNode }) {
  return <section className="min-w-0 rounded-2xl border border-[#D6DDD0] bg-white p-4 shadow-[0_14px_40px_rgba(16,35,27,0.05)] sm:p-5">{children}</section>;
}

function SourceTag({ kind, text }: { kind: "inputs" | "calculated" | "unavailable"; text: CropText }) {
  const map = { inputs: ["legendInputs", "#6E7A1E", "#F6F9DC"], calculated: ["legendCalculated", "#24577F", "#E8F2FA"], unavailable: ["legendUnavailable", "#5E574B", "#F1EEE8"] } as const;
  const [key, color, background] = map[kind];
  return <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold" style={{ color, background }}><span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />{text.c(key)}</span>;
}

function Locked({ text }: { text: CropText }) {
  const label = text.t("commercialBoundary.upgradeTo").replace("{plan}", text.t("commercialBoundary.plan.professional"));
  return (
    <Panel>
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-start gap-2 text-[14px] text-[#10231B]"><Lock className="mt-0.5 h-4 w-4 flex-shrink-0 text-[#2D6A4F]" />{text.c("calculatorsLocked")}</p>
        <Link to="/pricing" className="inline-flex min-h-[44px] items-center rounded-xl bg-[#10231B] px-4 text-[13px] font-semibold text-white">{label}</Link>
      </div>
    </Panel>
  );
}

function Needs({ codes, text, extra = [] }: { codes: unknown; text: CropText; extra?: CropCopyKey[] }) {
  const keys = Array.from(new Set([...extra, ...reasonCopyKeys(codes)]));
  if (!keys.length) return null;
  return (
    <div className="rounded-xl border border-[#EAD8AF] bg-[#FFF9EA] p-3">
      <div className="flex items-center gap-2 text-[13px] font-semibold text-[#7A5A00]"><Info className="h-4 w-4" />{text.c("whatIsNeeded")}</div>
      <ul className="mt-2 list-disc space-y-1 ps-5 text-[13px] leading-6 text-[#5B4A1E]">{keys.map((key) => <li key={key}>{text.c(key)}</li>)}</ul>
    </div>
  );
}

function useNumberFormat(locale: string | undefined) {
  return useMemo(() => {
    const whole = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
    const fine = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
    return (value: unknown, precise = false) => {
      const number = typeof value === "string" ? Number(value) : value;
      return typeof number === "number" && Number.isFinite(number) ? (precise || Math.abs(number) < 100 ? fine : whole).format(number) : "—";
    };
  }, [locale]);
}

function Metric({ label, value, interval, text, format, unit }: { label: string; value: unknown; interval?: Interval; text: CropText; format: (value: unknown, precise?: boolean) => string; unit?: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-[#F3F7F2] p-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#526057]">{label}</div>
      <div className="mt-1 text-[22px] font-semibold text-[#10231B]">{format(value)}{unit ? <span className="ms-1 text-[13px] font-medium text-[#526057]">{unit}</span> : null}</div>
      {interval ? <div className="mt-0.5 text-[12px] text-[#526057]">{text.c("interval95")}: {format(interval[0])}–{format(interval[1])}</div> : null}
    </div>
  );
}

function useCalculator() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [locked, setLocked] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const run = async (request: () => Promise<unknown>, failed: string) => {
    setBusy(true);
    setError("");
    try {
      setResult((await request()) as Result);
    } catch (cause) {
      const apiError = cause as ApiError;
      if (apiError?.status === 402) setLocked(true);
      else setError(apiError?.message || failed);
      setResult(null);
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, locked, result, setResult, run };
}

function SubmitButton({ busy, label, text, disabled }: { busy: boolean; label: string; text: CropText; disabled?: boolean }) {
  return (
    <button type="submit" disabled={busy || disabled} className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl bg-[#10231B] px-4 text-[14px] font-semibold text-white disabled:opacity-50 sm:w-auto">
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Calculator className="h-4 w-4" />}{busy ? text.c("calculating") : label}
    </button>
  );
}

function ErrorLine({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-xl border border-[#F0C6B8] bg-[#FFF5F1] px-3 py-2 text-[13px] text-[#8B321B]">{message}</p> : null;
}

function stageLabel(text: CropText, stage: string) {
  return STAGE_KEYS[stage] ? text.c(STAGE_KEYS[stage]) : stage;
}

// ---------------------------------------------------------------------------
// Production
// ---------------------------------------------------------------------------

type EstimateInput = { value: string; se: string };
type StratumInput = { id: string; units: string; counts: string };
const DESIGNS: [string, CropCopyKey][] = [
  ["simple_random", "designSimple"], ["systematic_random_start", "designSystematic"],
  ["stratified_random", "designStratified"], ["convenience", "designConvenience"],
];

function estimatePayload(input: EstimateInput): { value: number; standard_error: number } | null | "invalid" {
  if (!input.value.trim() && !input.se.trim()) return null;
  const value = optionalNumber(input.value);
  const se = optionalNumber(input.se);
  if (value === null || se === null || Number.isNaN(value) || Number.isNaN(se)) return "invalid";
  return { value, standard_error: se };
}

export function ProductionPanel({ text, allowed, field }: { text: CropText; allowed: boolean; field: OverviewField | null }) {
  const { c } = text;
  const navigate = useNavigate();
  const format = useNumberFormat(text.locale);
  const calc = useCalculator();
  const [form, setForm] = useState({ object_label: "", unit: "", design: "simple_random", population: "", counts: "", area: "", proposal: true });
  const [strata, setStrata] = useState<StratumInput[]>([{ id: "1", units: "", counts: "" }, { id: "2", units: "", counts: "" }]);
  const [visible, setVisible] = useState<EstimateInput>({ value: "", se: "" });
  const [weight, setWeight] = useState<EstimateInput>({ value: "", se: "" });
  const [marketable, setMarketable] = useState<EstimateInput>({ value: "", se: "" });
  const [clientNeeds, setClientNeeds] = useState<CropCopyKey[]>([]);
  const stratified = form.design === "stratified_random";

  if (!allowed || calc.locked) return <Locked text={text} />;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const needs: CropCopyKey[] = [];
    const population = Number(form.population);
    if (!Number.isInteger(population) || population < 1) needs.push("reasonPopulation");
    const calibration = [estimatePayload(visible), estimatePayload(weight), estimatePayload(marketable)];
    if (calibration.includes("invalid")) needs.push("reasonCalibration");
    const area = optionalNumber(form.area);
    if (area !== null && !(area > 0)) needs.push("reasonArea");
    const counts = parseNumberList(form.counts);
    if (!stratified && counts.invalid) needs.push("reasonCounts");
    const strataPayload = strata.map((row) => ({ stratum_id: row.id.trim(), population_units: Number(row.units), sample_counts: parseNumberList(row.counts) }));
    if (stratified && strataPayload.some(invalidStratum)) needs.push("reasonStrata");
    setClientNeeds(needs);
    if (needs.length) {
      calc.setResult(null);
      return;
    }
    const [detection_rate, unit_weight_kg, marketable_fraction] = calibration as ({ value: number; standard_error: number } | null)[];
    const payload: Record<string, unknown> = {
      unit: form.unit.trim(), object_label: form.object_label.trim(), design: form.design, population_units: population,
      count_source: "manual_count", include_market_proposal: form.proposal,
      ...(stratified
        ? { strata: strataPayload.map((row) => ({ stratum_id: row.stratum_id, population_units: row.population_units, sample_counts: row.sample_counts.values })) }
        : { sample_counts: counts.values }),
      ...(detection_rate ? { detection_rate } : {}),
      ...(unit_weight_kg ? { unit_weight_kg } : {}),
      ...(marketable_fraction ? { marketable_fraction } : {}),
      ...(area !== null ? { area_hectares: String(area) } : {}),
    };
    void calc.run(() => apiClient.fieldIntelligence.productionEstimate(payload), c("failed"));
  };

  const result = calc.result;
  const proposal = result?.market_yield_proposal;
  const sendToMarket = () => {
    if (!proposal || !result) return;
    const marketableBasis = Boolean(result.expected_marketable_kg_per_hectare && result.expected_marketable_kg);
    storeMarketHandoff({
      version: 1, created_at: new Date().toISOString(), estimate_id: String(result.estimate_id || ""),
      yield_per_area: String(proposal.yield_per_area), quantity_unit: String(proposal.quantity_unit), area_unit: String(proposal.area_unit),
      note: String(proposal.note || ""), basis: marketableBasis ? "marketable" : "total",
      interval: (marketableBasis ? result.expected_marketable_kg?.interval_95 : result.expected_production_kg?.interval_95) || null,
      design: String(result.design), sampled_units: Number(result.sampled_units), object_label: String(result.object_label),
    });
    navigate("/market-intelligence?crop_proposal=1");
  };
  const statusKey: Record<string, CropCopyKey> = { estimated: "statusEstimated", density_only: "statusDensityOnly", count_only: "statusCountOnly", not_estimable: "statusNotEstimable" };
  const estimateInputs: [CropCopyKey, EstimateInput, (value: EstimateInput) => void][] = [
    ["visibleShare", visible, setVisible], ["unitWeight", weight, setWeight], ["marketableShare", marketable, setMarketable],
  ];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Panel>
        <div className="flex flex-wrap items-center gap-2"><SourceTag kind="inputs" text={text} /></div>
        <p className="mt-3 text-[13px] leading-6 text-[#526057]">{c("productionIntro")}</p>
        {field ? <p className="mt-2 text-[12px] text-[#65736A]">{text.t("fieldIntel.field")}: {field.field_name || field.field_id}</p> : null}
        <form className="mt-4 space-y-4" onSubmit={submit} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <div><FieldLabel htmlFor="prod-object" text={text}>{c("objectLabel")}</FieldLabel><input id="prod-object" required maxLength={60} className={INPUT} value={form.object_label} onChange={(e) => setForm({ ...form, object_label: e.target.value })} /></div>
            <div><FieldLabel htmlFor="prod-unit" text={text}>{c("unitLabel")}</FieldLabel><input id="prod-unit" required maxLength={40} className={INPUT} value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} /></div>
            <div><FieldLabel htmlFor="prod-design" text={text}>{c("design")}</FieldLabel>
              <select id="prod-design" className={INPUT} value={form.design} onChange={(e) => setForm({ ...form, design: e.target.value })}>{DESIGNS.map(([value, key]) => <option key={value} value={value}>{c(key)}</option>)}</select></div>
            <div><FieldLabel htmlFor="prod-population" text={text}>{c("populationUnits")}</FieldLabel><input id="prod-population" inputMode="numeric" className={INPUT} value={form.population} onChange={(e) => setForm({ ...form, population: e.target.value })} /></div>
          </div>
          {stratified ? (
            <fieldset className="space-y-2">
              <legend className="text-[12px] font-semibold text-[#3F5247]">{c("designStratified")}</legend>
              {strata.map((row, index) => (
                <div key={index} className="grid gap-2 rounded-xl border border-[#E2E7DE] p-2 sm:grid-cols-[110px_130px_minmax(0,1fr)_44px]">
                  <input aria-label={c("stratum")} className={INPUT} value={row.id} onChange={(e) => setStrata(strata.map((item, i) => i === index ? { ...item, id: e.target.value } : item))} />
                  <input aria-label={c("stratumUnits")} placeholder={c("stratumUnits")} inputMode="numeric" className={INPUT} value={row.units} onChange={(e) => setStrata(strata.map((item, i) => i === index ? { ...item, units: e.target.value } : item))} />
                  <input aria-label={c("sampleCounts")} placeholder={c("sampleCounts")} className={INPUT} value={row.counts} onChange={(e) => setStrata(strata.map((item, i) => i === index ? { ...item, counts: e.target.value } : item))} />
                  <button type="button" aria-label={c("remove")} disabled={strata.length <= 2} onClick={() => setStrata(strata.filter((_, i) => i !== index))} className="inline-flex min-h-[44px] items-center justify-center rounded-xl border border-[#D6DDD0] text-[#8B321B] disabled:opacity-40"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
              <button type="button" onClick={() => setStrata([...strata, { id: String(strata.length + 1), units: "", counts: "" }])} className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-[#C7D2C9] px-3 text-[12px] font-semibold text-[#234224]"><Plus className="h-4 w-4" />{c("addStratum")}</button>
            </fieldset>
          ) : (
            <div><FieldLabel htmlFor="prod-counts" text={text}>{c("sampleCounts")}</FieldLabel>
              <textarea id="prod-counts" rows={3} className={`${INPUT} py-2`} value={form.counts} onChange={(e) => setForm({ ...form, counts: e.target.value })} aria-describedby="prod-counts-hint" />
              <p id="prod-counts-hint" className="mt-1 text-[11px] text-[#7B877F]">{c("sampleCountsHint")}</p></div>
          )}
          <fieldset className="space-y-2 rounded-xl border border-[#E2E7DE] p-3">
            <legend className="px-1 text-[12px] font-semibold text-[#3F5247]">{c("calibration")} · {c("optional")}</legend>
            {estimateInputs.map(([key, value, set]) => (
              <div key={key} className="grid gap-2 sm:grid-cols-2">
                <div><label htmlFor={`prod-${key}`} className="mb-1 block text-[12px] text-[#3F5247]">{c(key)}</label><input id={`prod-${key}`} inputMode="decimal" className={INPUT} value={value.value} onChange={(e) => set({ ...value, value: e.target.value })} /></div>
                <div><label htmlFor={`prod-${key}-se`} className="mb-1 block text-[12px] text-[#3F5247]">{c("standardError")}</label><input id={`prod-${key}-se`} inputMode="decimal" className={INPUT} value={value.se} onChange={(e) => set({ ...value, se: e.target.value })} /></div>
              </div>
            ))}
            <div><FieldLabel htmlFor="prod-area" optional text={text}>{c("areaHectares")}</FieldLabel><input id="prod-area" inputMode="decimal" className={INPUT} value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} /></div>
          </fieldset>
          <div className="space-y-1 text-[12px] text-[#526057]">
            <p className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-[#2D6A4F]" />{c("manualCounts")}</p>
            <p className="flex items-start gap-2"><SourceTag kind="unavailable" text={text} /><span className="pt-0.5">{c("noDetector")}</span></p>
          </div>
          <label className="flex min-h-[44px] items-center gap-3 text-[13px] text-[#10231B]"><input type="checkbox" className="h-5 w-5" checked={form.proposal} onChange={(e) => setForm({ ...form, proposal: e.target.checked })} />{c("includeProposal")}</label>
          <SubmitButton busy={calc.busy} label={c("calculateEstimate")} text={text} disabled={!form.object_label.trim() || !form.unit.trim()} />
        </form>
      </Panel>

      <Panel>
        <div className="flex flex-wrap items-center gap-2"><SourceTag kind="calculated" text={text} /></div>
        <div className="mt-3 space-y-3" aria-live="polite">
          <ErrorLine message={calc.error} />
          <Needs codes={[]} extra={clientNeeds} text={text} />
          {!result && !calc.error && !clientNeeds.length ? <p className="text-[13px] text-[#65736A]">{c("productionIntro")}</p> : null}
          {result ? (
            <>
              <h3 className="text-[17px] font-semibold text-[#10231B]">{statusKey[result.status] ? c(statusKey[result.status]) : result.status}</h3>
              {result.status === "not_estimable" ? <Needs codes={result.reasons} text={text} /> : null}
              {result.expected_production_kg ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  <Metric label={c("expectedProduction")} value={result.expected_production_kg.value} interval={result.expected_production_kg.interval_95} text={text} format={format} unit="kg" />
                  {result.expected_marketable_kg ? <Metric label={c("marketableProduction")} value={result.expected_marketable_kg.value} interval={result.expected_marketable_kg.interval_95} text={text} format={format} unit="kg" /> : null}
                  {result.expected_production_kg_per_hectare ? <Metric label={c("perHectare")} value={result.expected_marketable_kg_per_hectare || result.expected_production_kg_per_hectare} text={text} format={format} unit="kg/ha" /> : null}
                </div>
              ) : null}
              {result.estimated_total_objects ? <Metric label={c("estimatedObjects")} value={result.estimated_total_objects.value} interval={result.estimated_total_objects.interval_95} text={text} format={format} /> : null}
              {result.visible_density_per_unit ? <Metric label={c("averagePerUnit")} value={result.visible_density_per_unit.value} interval={result.visible_density_per_unit.interval_95} text={text} format={(value) => format(value, true)} /> : null}
              {result.interval_reliability && result.interval_reliability !== "design_based" ? <p className="flex items-start gap-2 rounded-xl bg-[#FFF6D6] px-3 py-2 text-[12px] text-[#7A5A00]"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />{c("intervalUnreliable")}</p> : null}
              {result.status !== "not_estimable" ? (
                <ul className="space-y-1 text-[12px] text-[#526057]">
                  <li>{c("inputsUnverified")}</li>
                  <li>{c("notCalibrated")}</li>
                  <li>{c("agronomicEstimate")}</li>
                </ul>
              ) : null}
              {form.proposal && result.status !== "not_estimable" ? (
                proposal ? (
                  <div className="rounded-xl border border-[#C6DECC] bg-[#F2FAF4] p-3">
                    <p className="text-[12px] leading-5 text-[#1F6A45]">{c("proposalNote")}</p>
                    <button type="button" onClick={sendToMarket} className="mt-2 inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#234224] px-4 text-[13px] font-semibold text-white">{c("sendToMarket")}<ArrowRight className="h-4 w-4" /></button>
                  </div>
                ) : <p className="text-[12px] text-[#65736A]">{c("noProposal")}</p>
              ) : null}
            </>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Harvest window
// ---------------------------------------------------------------------------

const BIOFIX: [string, CropCopyKey][] = [
  ["planting", "biofixPlanting"], ["transplant", "biofixTransplant"], ["emergence", "biofixEmergence"],
  ["bud_break", "biofixBudBreak"], ["bloom", "biofixBloom"], ["other", "biofixOther"],
];
const SOURCE_TYPES: [string, CropCopyKey][] = [["supplier_published", "sourceSupplier"], ["grower_historical", "sourceGrower"], ["fitted_model", "sourceFitted"]];

function todayIso() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

function CsvInput({ id, label, value, onChange, summary, text }: { id: string; label: string; value: string; onChange: (value: string) => void; summary: ReactNode; text: CropText }) {
  return (
    <div>
      <FieldLabel htmlFor={id} text={text}>{label}</FieldLabel>
      <textarea id={id} rows={4} spellCheck={false} className={`${INPUT} py-2 font-mono text-[12px]`} value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={`${id}-hint`} />
      <div id={`${id}-hint`} className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#7B877F]">
        <span>{summary}</span>
        <label className="inline-flex min-h-[36px] cursor-pointer items-center gap-1.5 rounded-lg border border-[#C7D2C9] px-2.5 font-semibold text-[#234224]">
          <Upload className="h-3.5 w-3.5" />{text.c("uploadCsv")}
          <input type="file" accept=".csv,text/csv,text/plain" className="sr-only" onChange={(event) => {
            const file = event.target.files?.[0];
            if (file && file.size <= 2_000_000) void file.text().then(onChange);
            event.target.value = "";
          }} />
        </label>
      </div>
    </div>
  );
}

export function HarvestWindowPanel({ text, allowed, profiles, initialCrop }: { text: CropText; allowed: boolean; profiles: CropProfile[]; initialCrop: string }) {
  const { c, cf } = text;
  const format = useNumberFormat(text.locale);
  const calc = useCalculator();
  const [form, setForm] = useState({
    crop: initialCrop || "", biofix: "", biofix_type: "planting", as_of: todayIso(), method: "profile", base: "", upper: "",
    low: "", high: "", source: "", source_type: "supplier_published", variety: "", observed: "", analog: "", weather_source: "", analog_source: "",
  });
  useEffect(() => { if (initialCrop) setForm((current) => current.crop ? current : { ...current, crop: initialCrop }); }, [initialCrop]);
  const profile = profiles.find((item) => item.crop_id === form.crop) || null;
  const observed = useMemo(() => parseWeatherCsv(form.observed), [form.observed]);
  const analog = useMemo(() => parseWeatherCsv(form.analog), [form.analog]);
  const seasons = useMemo(() => (form.as_of ? groupAnalogSeasons(analog.days, form.as_of) : {}), [analog.days, form.as_of]);

  if (!allowed || calc.locked) return <Locked text={text} />;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const observedDays = form.biofix && form.as_of ? observedWindow(observed.days, form.biofix, form.as_of) : [];
    const recentSeasons = Object.keys(seasons).sort().slice(-30);
    const low = optionalNumber(form.low);
    const high = optionalNumber(form.high);
    const payload: Record<string, unknown> = {
      crop: form.crop || null, biofix: form.biofix, biofix_type: form.biofix_type, as_of: form.as_of,
      observed: observedDays.slice(-400) as WeatherDay[],
      analog_years: Object.fromEntries(recentSeasons.map((year) => [year, seasons[year].slice(0, 366)])),
      weather_source: form.weather_source.trim() || null, analog_weather_source: form.analog_source.trim() || null,
    };
    if (form.method !== "profile") {
      payload.degree_day_method = form.method;
      const base = optionalNumber(form.base);
      const upper = optionalNumber(form.upper);
      if (base !== null && !Number.isNaN(base)) payload.base_c = base;
      if (upper !== null && !Number.isNaN(upper)) payload.upper_cutoff_c = upper;
    }
    if (low && high && low > 0 && high > 0 && form.source.trim()) {
      payload.target = { low_gdd: low, high_gdd: high, source: form.source.trim(), source_type: form.source_type, variety: form.variety.trim() || null };
    }
    void calc.run(() => apiClient.fieldIntelligence.harvestWindow(payload), c("failed"));
  };

  const result = calc.result;
  const statusKey: Record<string, CropCopyKey> = { projected: "statusProjected", within_target_range: "statusWithin", past_target_range: "statusPast", insufficient_evidence: "statusInsufficient" };
  const date = (value: string | undefined) => value ? new Date(`${value}T00:00:00`).toLocaleDateString(text.locale, { month: "short", day: "numeric", year: "numeric" }) : "—";
  const progress = typeof result?.progress_to_target_low === "number" ? Math.min(100, Math.round(result.progress_to_target_low * 100)) : null;
  const ready = Boolean(form.biofix && form.as_of);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Panel>
        <SourceTag kind="inputs" text={text} />
        <p className="mt-3 text-[13px] leading-6 text-[#526057]">{c("harvestIntro")}</p>
        <form className="mt-4 space-y-4" onSubmit={submit} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <div><FieldLabel htmlFor="hw-crop" text={text}>{c("crop")}</FieldLabel>
              <select id="hw-crop" className={INPUT} value={form.crop} onChange={(e) => setForm({ ...form, crop: e.target.value })}>
                <option value="">—</option>{profiles.map((item) => <option key={item.crop_id} value={item.crop_id}>{item.display_name}</option>)}
              </select></div>
            <div><FieldLabel htmlFor="hw-variety" optional text={text}>{c("variety")}</FieldLabel><input id="hw-variety" maxLength={120} className={INPUT} value={form.variety} onChange={(e) => setForm({ ...form, variety: e.target.value })} /></div>
            <div><FieldLabel htmlFor="hw-biofix" text={text}>{c("biofix")}</FieldLabel><input id="hw-biofix" type="date" className={INPUT} value={form.biofix} onChange={(e) => setForm({ ...form, biofix: e.target.value })} /></div>
            <div><FieldLabel htmlFor="hw-biofix-type" text={text}>{c("biofixType")}</FieldLabel>
              <select id="hw-biofix-type" className={INPUT} value={form.biofix_type} onChange={(e) => setForm({ ...form, biofix_type: e.target.value })}>{BIOFIX.map(([value, key]) => <option key={value} value={value}>{c(key)}</option>)}</select></div>
            <div><FieldLabel htmlFor="hw-asof" text={text}>{c("asOf")}</FieldLabel><input id="hw-asof" type="date" className={INPUT} value={form.as_of} onChange={(e) => setForm({ ...form, as_of: e.target.value })} /></div>
            <div><FieldLabel htmlFor="hw-method" text={text}>{c("ddMethod")}</FieldLabel>
              <select id="hw-method" className={INPUT} value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
                <option value="profile" disabled={!profile?.degree_day_method}>{c("ddProfileDefault")}</option>
                <option value="simple_average">{c("ddSimple")}</option>
                <option value="modified_average_86_50">{c("ddModified")}</option>
              </select></div>
            {form.method !== "profile" ? (
              <>
                <div><FieldLabel htmlFor="hw-base" text={text}>{c("baseTemp")}</FieldLabel><input id="hw-base" inputMode="decimal" className={INPUT} value={form.base} onChange={(e) => setForm({ ...form, base: e.target.value })} /></div>
                <div><FieldLabel htmlFor="hw-upper" optional={form.method === "simple_average"} text={text}>{c("upperCutoff")}</FieldLabel><input id="hw-upper" inputMode="decimal" className={INPUT} value={form.upper} onChange={(e) => setForm({ ...form, upper: e.target.value })} /></div>
              </>
            ) : profile?.degree_day_method ? <p className="self-end text-[11px] leading-5 text-[#7B877F] sm:col-span-2">{profile.degree_day_method.source}</p> : null}
            <div><FieldLabel htmlFor="hw-low" text={text}>{c("targetLow")}</FieldLabel><input id="hw-low" inputMode="decimal" className={INPUT} value={form.low} onChange={(e) => setForm({ ...form, low: e.target.value })} /></div>
            <div><FieldLabel htmlFor="hw-high" text={text}>{c("targetHigh")}</FieldLabel><input id="hw-high" inputMode="decimal" className={INPUT} value={form.high} onChange={(e) => setForm({ ...form, high: e.target.value })} /></div>
            <div><FieldLabel htmlFor="hw-source" text={text}>{c("targetSource")}</FieldLabel><input id="hw-source" maxLength={500} className={INPUT} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></div>
            <div><FieldLabel htmlFor="hw-source-type" text={text}>{c("targetSourceType")}</FieldLabel>
              <select id="hw-source-type" className={INPUT} value={form.source_type} onChange={(e) => setForm({ ...form, source_type: e.target.value })}>{SOURCE_TYPES.map(([value, key]) => <option key={value} value={value}>{c(key)}</option>)}</select></div>
          </div>
          <p className="text-[11px] text-[#7B877F]">{c("weatherFormat")}</p>
          <CsvInput id="hw-observed" label={c("observedWeather")} value={form.observed} onChange={(value) => setForm((current) => ({ ...current, observed: value }))} text={text}
            summary={<>{cf("daysReadTemplate", { count: observed.days.length })}{observed.skipped ? ` · ${cf("linesSkippedTemplate", { count: observed.skipped })}` : ""}</>} />
          <div><FieldLabel htmlFor="hw-weather-source" text={text}>{c("weatherSource")}</FieldLabel><input id="hw-weather-source" maxLength={500} className={INPUT} value={form.weather_source} onChange={(e) => setForm({ ...form, weather_source: e.target.value })} /></div>
          <CsvInput id="hw-analog" label={c("analogWeather")} value={form.analog} onChange={(value) => setForm((current) => ({ ...current, analog: value }))} text={text}
            summary={<>{cf("seasonsReadTemplate", { count: Object.keys(seasons).length })}{analog.skipped ? ` · ${cf("linesSkippedTemplate", { count: analog.skipped })}` : ""}</>} />
          <div><FieldLabel htmlFor="hw-analog-source" text={text}>{c("analogSource")}</FieldLabel><input id="hw-analog-source" maxLength={500} className={INPUT} value={form.analog_source} onChange={(e) => setForm({ ...form, analog_source: e.target.value })} /></div>
          <SubmitButton busy={calc.busy} label={c("calculateWindow")} text={text} disabled={!ready} />
        </form>
      </Panel>

      <Panel>
        <SourceTag kind="calculated" text={text} />
        <div className="mt-3 space-y-3" aria-live="polite">
          <ErrorLine message={calc.error} />
          {!result && !calc.error ? <p className="flex items-start gap-2 text-[13px] text-[#65736A]"><CalendarRange className="mt-0.5 h-4 w-4 flex-shrink-0" />{c("harvestIntro")}</p> : null}
          {result ? (
            <>
              <h3 className="text-[17px] font-semibold text-[#10231B]">{statusKey[result.status] ? c(statusKey[result.status]) : result.status}</h3>
              {result.status === "insufficient_evidence" ? <Needs codes={result.reasons} text={text} /> : null}
              {result.window ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  <Metric label={c("earliest")} value={null} text={text} format={() => date(result.window.earliest)} />
                  <Metric label={c("latest")} value={null} text={text} format={() => date(result.window.latest)} />
                  <Metric label={c("likelyStart")} value={null} text={text} format={() => date(result.window.median_entry)} />
                  <Metric label={c("likelyEnd")} value={null} text={text} format={() => date(result.window.median_exit)} />
                </div>
              ) : null}
              {typeof result.accumulated_gdd === "number" ? (
                <div className="rounded-xl bg-[#F3F7F2] p-3">
                  <div className="flex items-baseline justify-between gap-2 text-[13px] text-[#10231B]"><span className="font-semibold">{c("gddSoFar")}</span><span>{format(result.accumulated_gdd)}</span></div>
                  {progress !== null ? (
                    <>
                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#DDE6DE]" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label={c("gddSoFar")}><div className="h-full rounded-full bg-[#2D6A4F]" style={{ width: `${progress}%` }} /></div>
                      <div className="mt-1 text-[12px] text-[#526057]">{cf("progressTemplate", { percent: progress })}</div>
                    </>
                  ) : null}
                </div>
              ) : null}
              {typeof result.analog_years_used === "number" ? <p className="text-[12px] text-[#526057]">{cf("seasonsUsedTemplate", { count: result.analog_years_used })}</p> : null}
              {Array.isArray(result.analog_years_rejected) && result.analog_years_rejected.length ? (
                <details className="rounded-xl border border-[#E2E7DE] p-3 text-[12px] text-[#526057]">
                  <summary className="cursor-pointer font-semibold">{c("seasonsRejected")} ({result.analog_years_rejected.length})</summary>
                  <ul className="mt-2 space-y-1">{result.analog_years_rejected.map((row: { year: number; reasons: string[] }) => <li key={row.year}>{row.year}: {reasonCopyKeys(row.reasons).map((key) => c(key)).join(" ")}</li>)}</ul>
                </details>
              ) : null}
              {Array.isArray(result.suggested_actions) && result.suggested_actions.length ? (
                <div className="rounded-xl border border-[#C6DECC] bg-[#F2FAF4] p-3">
                  <div className="text-[13px] font-semibold text-[#1F6A45]">{c("suggestions")}</div>
                  <ul className="mt-2 space-y-1 text-[13px] text-[#10231B]">{result.suggested_actions.map((action: { action_code: string; due_by: string }) => <li key={action.action_code}>{ACTION_KEYS[action.action_code] ? c(ACTION_KEYS[action.action_code]) : action.action_code} · {cf("byDateTemplate", { date: date(action.due_by) })}</li>)}</ul>
                </div>
              ) : null}
              <div className="rounded-xl border border-[#E2E7DE] p-3 text-[12px] leading-5 text-[#526057]">
                <div className="font-semibold text-[#10231B]">{c("limitations")}</div>
                <ul className="mt-1 list-disc space-y-1 ps-5"><li>{c("limitationWeather")}</li><li>{c("limitationAnalog")}</li><li>{c("notCalibrated")}</li><li>{c("inputsUnverified")}</li></ul>
              </div>
            </>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Maturity stages
// ---------------------------------------------------------------------------

type SampleRow = { id: string; counts: Record<string, string> };

function blankRows(count: number, start = 1): SampleRow[] {
  return Array.from({ length: count }, (_, index) => ({ id: String(start + index), counts: {} }));
}

export function MaturityPanel({ text, allowed, profiles, initialCrop }: { text: CropText; allowed: boolean; profiles: CropProfile[]; initialCrop: string }) {
  const { c } = text;
  const calc = useCalculator();
  const staged = profiles.filter((item) => item.maturity_stages.length);
  const [crop, setCrop] = useState(initialCrop && staged.some((item) => item.crop_id === initialCrop) ? initialCrop : "");
  const [design, setDesign] = useState("simple_random");
  const [population, setPopulation] = useState("");
  const [rows, setRows] = useState<SampleRow[]>(blankRows(5));
  const [readyStages, setReadyStages] = useState<string[]>([]);
  const [threshold, setThreshold] = useState("");
  const [thresholdSource, setThresholdSource] = useState("");
  const [clientNeeds, setClientNeeds] = useState<CropCopyKey[]>([]);
  useEffect(() => { if (!crop && staged.length) setCrop(staged.some((item) => item.crop_id === initialCrop) ? initialCrop : staged[0].crop_id); }, [crop, staged, initialCrop]);
  const profile = staged.find((item) => item.crop_id === crop) || null;
  const stages = profile?.maturity_stages || [];

  if (!allowed || calc.locked) return <Locked text={text} />;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const needs: CropCopyKey[] = [];
    const samples = rows.filter((row) => row.id.trim()).map((row) => ({
      unit_id: row.id.trim(),
      counts: Object.fromEntries(stages.map((stage) => [stage, Number(row.counts[stage] || 0)])),
    }));
    if (samples.some((sample) => Object.values(sample.counts).some(invalidCount))) needs.push("reasonCounts");
    const populationValue = optionalNumber(population);
    if (populationValue !== null && !(Number.isInteger(populationValue) && populationValue >= 1)) needs.push("reasonPopulation");
    let readiness: Record<string, unknown> | undefined;
    if (readyStages.length) {
      const share = Number(threshold) / 100;
      if (!isShare(share) || !thresholdSource.trim()) needs.push("reasonReadiness");
      else readiness = { ready_stages: readyStages, threshold_share: share, source: thresholdSource.trim() };
    }
    setClientNeeds(needs);
    if (needs.length || !samples.length) {
      calc.setResult(null);
      return;
    }
    void calc.run(() => apiClient.fieldIntelligence.maturityStages({
      crop, design, samples, count_source: "manual_count",
      ...(populationValue !== null ? { population_units: populationValue } : {}),
      ...(readiness ? { readiness } : {}),
    }), c("failed"));
  };

  const result = calc.result;
  const readiness = result?.readiness;
  const readinessKey: Record<string, CropCopyKey> = { ready: "readyYes", not_ready: "readyNo", uncertain: "readyUncertain" };
  const readinessTone: Record<string, string> = { ready: "#1F6A45", not_ready: "#9B2C14", uncertain: "#7A5A00" };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Panel>
        <SourceTag kind="inputs" text={text} />
        <p className="mt-3 text-[13px] leading-6 text-[#526057]">{c("maturityIntro")}</p>
        {!staged.length ? <p className="mt-3 text-[13px] text-[#65736A]">{c("noMaturityScale")}</p> : (
          <form className="mt-4 space-y-4" onSubmit={submit} noValidate>
            <div className="grid gap-3 sm:grid-cols-3">
              <div><FieldLabel htmlFor="mat-crop" text={text}>{c("crop")}</FieldLabel>
                <select id="mat-crop" className={INPUT} value={crop} onChange={(e) => { setCrop(e.target.value); setReadyStages([]); setRows(blankRows(5)); }}>
                  {staged.map((item) => <option key={item.crop_id} value={item.crop_id}>{item.display_name}</option>)}
                </select></div>
              <div><FieldLabel htmlFor="mat-design" text={text}>{c("design")}</FieldLabel>
                <select id="mat-design" className={INPUT} value={design} onChange={(e) => setDesign(e.target.value)}>{DESIGNS.map(([value, key]) => <option key={value} value={value}>{c(key)}</option>)}</select></div>
              <div><FieldLabel htmlFor="mat-population" optional text={text}>{c("populationUnits")}</FieldLabel><input id="mat-population" inputMode="numeric" className={INPUT} value={population} onChange={(e) => setPopulation(e.target.value)} /></div>
            </div>
            {profile?.maturity_scale ? <p className="text-[11px] text-[#7B877F]">{profile.maturity_scale}{profile.validation_status === "unvalidated" ? ` · ${c("unvalidatedProfile")}` : ""}</p> : null}
            <div className="overflow-x-auto rounded-xl border border-[#E2E7DE]">
              <table className="min-w-full text-[12px]">
                <thead className="bg-[#F7F5EF] text-[#3F5247]">
                  <tr>
                    <th scope="col" className="px-2 py-2 text-start font-semibold">{c("unitId")}</th>
                    {stages.map((stage) => <th key={stage} scope="col" className="px-2 py-2 text-start font-semibold">{stageLabel(text, stage)}</th>)}
                    <th scope="col" className="w-11 px-1 py-2"><span className="sr-only">{c("remove")}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={index} className="border-t border-[#EEF1EC]">
                      <td className="px-1 py-1"><input aria-label={c("unitId")} className="min-h-[40px] w-20 rounded-lg border border-[#D6DDD0] px-2" value={row.id} onChange={(e) => setRows(rows.map((item, i) => i === index ? { ...item, id: e.target.value } : item))} /></td>
                      {stages.map((stage) => (
                        <td key={stage} className="px-1 py-1"><input aria-label={`${row.id} ${stageLabel(text, stage)}`} inputMode="numeric" className="min-h-[40px] w-20 rounded-lg border border-[#D6DDD0] px-2" value={row.counts[stage] || ""} onChange={(e) => setRows(rows.map((item, i) => i === index ? { ...item, counts: { ...item.counts, [stage]: e.target.value } } : item))} /></td>
                      ))}
                      <td className="px-1 py-1"><button type="button" aria-label={c("remove")} disabled={rows.length <= 1} onClick={() => setRows(rows.filter((_, i) => i !== index))} className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-[#8B321B] disabled:opacity-40"><Trash2 className="h-4 w-4" /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" onClick={() => setRows([...rows, ...blankRows(1, rows.length + 1)])} className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-[#C7D2C9] px-3 text-[12px] font-semibold text-[#234224]"><Plus className="h-4 w-4" />{c("addUnit")}</button>
            <fieldset className="space-y-2 rounded-xl border border-[#E2E7DE] p-3">
              <legend className="px-1 text-[12px] font-semibold text-[#3F5247]">{c("readiness")} · {c("optional")}</legend>
              <div className="text-[12px] text-[#3F5247]">{c("readyStages")}</div>
              <div className="flex flex-wrap gap-2">
                {stages.map((stage) => (
                  <label key={stage} className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-[#D6DDD0] px-2.5 text-[12px]">
                    <input type="checkbox" checked={readyStages.includes(stage)} onChange={(e) => setReadyStages(e.target.checked ? [...readyStages, stage] : readyStages.filter((item) => item !== stage))} />{stageLabel(text, stage)}
                  </label>
                ))}
              </div>
              <div className="grid gap-2 sm:grid-cols-[140px_minmax(0,1fr)]">
                <div><label htmlFor="mat-threshold" className="mb-1 block text-[12px] text-[#3F5247]">{c("thresholdPercent")}</label><input id="mat-threshold" inputMode="decimal" className={INPUT} value={threshold} onChange={(e) => setThreshold(e.target.value)} /></div>
                <div><label htmlFor="mat-threshold-source" className="mb-1 block text-[12px] text-[#3F5247]">{c("thresholdSource")}</label><input id="mat-threshold-source" maxLength={500} className={INPUT} value={thresholdSource} onChange={(e) => setThresholdSource(e.target.value)} /></div>
              </div>
            </fieldset>
            <p className="flex items-center gap-2 text-[12px] text-[#526057]"><ShieldCheck className="h-4 w-4 text-[#2D6A4F]" />{c("manualCounts")}</p>
            <SubmitButton busy={calc.busy} label={c("calculateStages")} text={text} disabled={!crop} />
          </form>
        )}
      </Panel>

      <Panel>
        <SourceTag kind="calculated" text={text} />
        <div className="mt-3 space-y-3" aria-live="polite">
          <ErrorLine message={calc.error} />
          <Needs codes={[]} extra={clientNeeds} text={text} />
          {!result && !calc.error && !clientNeeds.length ? <p className="text-[13px] text-[#65736A]">{c("maturityIntro")}</p> : null}
          {result ? (
            <>
              {result.status === "not_estimable" ? <><h3 className="text-[17px] font-semibold text-[#10231B]">{c("statusNotEstimable")}</h3><Needs codes={result.reasons} text={text} /></> : null}
              {result.stage_shares ? (
                <>
                  <div className="flex flex-wrap gap-2 text-[12px] text-[#526057]">
                    <span className="rounded-full bg-[#F3F7F2] px-2.5 py-1">{c("unitsSampled")}: {result.sampled_units}</span>
                    <span className="rounded-full bg-[#F3F7F2] px-2.5 py-1">{c("objectsObserved")}: {result.objects_observed}</span>
                    <span className="rounded-full bg-[#F3F7F2] px-2.5 py-1">{result.scope === "block_estimate" ? c("scopeBlock") : c("scopeSampled")}</span>
                  </div>
                  <ul className="space-y-2.5">
                    {Object.entries(result.stage_shares as Record<string, { share: number; interval_95?: Interval }>).map(([stage, entry]) => {
                      const share = Math.round(entry.share * 1000) / 10;
                      return (
                        <li key={stage}>
                          <div className="flex items-baseline justify-between gap-2 text-[13px]"><span className="font-semibold text-[#10231B]">{stageLabel(text, stage)}</span><span className="text-[#10231B]">{share}%</span></div>
                          <div className="relative mt-1 h-3 overflow-hidden rounded-full bg-[#E7ECE6]" aria-hidden="true">
                            {entry.interval_95 ? <div className="absolute inset-y-0 rounded-full bg-[#B9D7C4]" style={{ left: `${entry.interval_95[0] * 100}%`, width: `${Math.max(0.5, (entry.interval_95[1] - entry.interval_95[0]) * 100)}%` }} /> : null}
                            <div className="absolute inset-y-0 w-1 rounded-full bg-[#1F5B3F]" style={{ left: `calc(${entry.share * 100}% - 2px)` }} />
                          </div>
                          {entry.interval_95 ? <div className="mt-0.5 text-[11px] text-[#65736A]">{c("interval95")}: {Math.round(entry.interval_95[0] * 1000) / 10}–{Math.round(entry.interval_95[1] * 1000) / 10}%</div> : null}
                        </li>
                      );
                    })}
                  </ul>
                </>
              ) : null}
              {readiness ? (
                <div className="rounded-xl border p-3 text-[13px]" style={{ borderColor: "#E2E7DE", color: readinessTone[readiness.status] || "#526057" }}>
                  <div className="font-semibold">{readinessKey[readiness.status] ? c(readinessKey[readiness.status]) : c("readyNotAssessed")}</div>
                  <div className="mt-1 text-[12px] text-[#526057]">{c("readiness")}: {Math.round(readiness.threshold_share * 1000) / 10}% · {readiness.threshold_source}</div>
                </div>
              ) : null}
              {result.status === "estimated" ? <ul className="space-y-1 text-[12px] text-[#526057]"><li>{c("inputsUnverified")}</li><li>{c("notCalibrated")}</li></ul> : null}
            </>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}
