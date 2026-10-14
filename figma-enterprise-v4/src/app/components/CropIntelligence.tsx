import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import {
  AlertTriangle, ArrowRight, CalendarRange, Eye, FileSearch, Gauge, Layers, Loader2, Radio, RefreshCw, Scale, Sprout, TrendingUp,
} from "lucide-react";
import { apiClient, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { CROP_COPY_VALUES, CROP_INTELLIGENCE_COPY, type CropCopyKey } from "../cropIntelligence/cropIntelligenceCopy";
import {
  ATTENTION_KEYS, CHANGE_KEYS, FRESHNESS_KEYS, calculatorsAllowed,
  type CopyValues, type CropCondition, type CropOverview, type CropProfile, type Freshness, type OverviewField,
} from "../cropIntelligence/cropIntelligenceModel";
import { HarvestWindowPanel, MaturityPanel, ProductionPanel, type CropText } from "../cropIntelligence/CropCalculators";

const TABS = ["overview", "health", "production", "harvest", "maturity"] as const;
type Tab = (typeof TABS)[number];
const TAB_KEYS: Record<Tab, CropCopyKey> = {
  overview: "tabOverview", health: "tabHealth", production: "tabProduction", harvest: "tabHarvest", maturity: "tabMaturity",
};
const TAB_ICONS: Record<Tab, typeof Sprout> = { overview: Layers, health: Eye, production: Scale, harvest: CalendarRange, maturity: Gauge };

const SEVERITY_TONE: Record<string, { background: string; color: string }> = {
  critical: { background: "#FDE7E1", color: "#9B2C14" },
  high: { background: "#FFEBD6", color: "#9A4A06" },
  medium: { background: "#FFF6D6", color: "#7A5A00" },
  low: { background: "#EAF4EC", color: "#1F6A45" },
  info: { background: "#EEF2EF", color: "#3F5247" },
};
const FRESHNESS_TONE: Record<Freshness, { background: string; color: string }> = {
  fresh: { background: "#E7F4EC", color: "#1F6A45" },
  aging: { background: "#FFF6D6", color: "#7A5A00" },
  stale: { background: "#FDECE7", color: "#A13F24" },
  unknown: { background: "#EEF2EF", color: "#526057" },
  future_dated: { background: "#FDECE7", color: "#A13F24" },
};

function Chip({ children, tone }: { children: ReactNode; tone?: { background: string; color: string } }) {
  const style = tone || { background: "#EEF2EF", color: "#3F5247" };
  return <span className="inline-flex max-w-full items-center gap-1 truncate rounded-full px-2.5 py-1 text-[11px] font-semibold" style={style}>{children}</span>;
}

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`min-w-0 rounded-2xl border border-[#D6DDD0] bg-white p-4 shadow-[0_14px_40px_rgba(16,35,27,0.05)] sm:p-5 ${className}`}>{children}</section>;
}

function formatDate(value: string | null | undefined, locale: string | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" });
}

function eventLabel(t: (key: string) => string, eventType: string) {
  const key = `fieldIntel.evt.${eventType || "observation"}`;
  const label = t(key);
  return label === key ? eventType.replace(/_/g, " ") : label;
}

export function CropIntelligence() {
  const { tx, tf, locale } = usePortalCopy([], CROP_COPY_VALUES);
  const { t } = useLocale();
  const { currentWorkspace, workspaces, entitlements } = useAuth();
  const workspaceId = currentWorkspace?.id || workspaces?.[0]?.id;
  const formatLocale = locale && locale !== "auto" ? locale : undefined;
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: Tab = (TABS as readonly string[]).includes(searchParams.get("tab") || "") ? (searchParams.get("tab") as Tab) : "overview";
  const fieldId = searchParams.get("field") || "";

  const text: CropText = useMemo(() => ({
    c: (key: CropCopyKey) => tx(CROP_INTELLIGENCE_COPY[key]),
    cf: (key: CropCopyKey, values: CopyValues) => tf(CROP_INTELLIGENCE_COPY[key], values),
    t,
    locale: formatLocale,
  }), [tx, tf, t, formatLocale]);
  const { c } = text;

  const [overview, setOverview] = useState<CropOverview | null>(null);
  const [profiles, setProfiles] = useState<CropProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const select = useCallback((next: { tab?: Tab; field?: string }) => {
    const params = new URLSearchParams(searchParams);
    if (next.tab) params.set("tab", next.tab);
    if (next.field !== undefined) {
      if (next.field) params.set("field", next.field); else params.delete("field");
    }
    setSearchParams(params, { replace: false });
  }, [searchParams, setSearchParams]);

  const loadOverview = useCallback(async () => {
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [overviewResult, profileResult] = await Promise.all([
        apiClient.fieldIntelligence.cropOverview(workspaceId) as Promise<CropOverview>,
        profiles.length ? Promise.resolve({ profiles }) : (apiClient.fieldIntelligence.cropProfiles() as Promise<{ profiles: CropProfile[] }>),
      ]);
      setOverview(overviewResult);
      setProfiles(profileResult.profiles || []);
    } catch (cause) {
      setError((cause as ApiError)?.message || c("failed"));
    } finally {
      setLoading(false);
    }
    // Profiles are static per release; they are fetched once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  useEffect(() => { void loadOverview(); }, [loadOverview]);

  const fields = overview?.fields || [];
  const selectedField = fields.find((item) => item.field_id === fieldId) || null;
  const allowed = calculatorsAllowed(entitlements);
  const fieldCrop = selectedField?.crop_profile?.crop_id || "";

  return (
    <div className="min-h-full bg-[#F6F4EE] px-3 py-4 sm:px-4 sm:py-5 md:px-6 md:py-6" data-crop-intelligence>
      <header className="rounded-2xl border border-[#D6DDD0] bg-[#10231B] p-4 text-white shadow-[0_20px_60px_rgba(16,35,27,0.16)] sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#92C7A9]"><Sprout className="h-4 w-4" />{currentWorkspace?.name || ""}</div>
            <h1 className="mt-1 text-[24px] font-semibold tracking-tight sm:text-[28px]">{c("navLabel")}</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-6 text-[#D8E4DD]">{c("subtitle")}</p>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            <Link to="/field-intelligence" className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-xl bg-white/10 px-3 text-[13px] font-semibold sm:flex-none"><Radio className="h-4 w-4" />{c("openField")}</Link>
            <Link to="/market-intelligence" className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-xl bg-white px-3 text-[13px] font-semibold text-[#10231B] sm:flex-none"><TrendingUp className="h-4 w-4" />{c("openMarket")}</Link>
          </div>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
          {([
            ["legendEvidence", "legendEvidenceHint", "#92C7A9"],
            ["legendInputs", "legendInputsHint", "#DDEB8F"],
            ["legendCalculated", "legendCalculatedHint", "#9CC6E8"],
            ["legendUnavailable", "legendUnavailableHint", "#C9C2B5"],
          ] as const).map(([title, hint, color]) => (
            <div key={title} className="min-w-0 rounded-xl bg-white/[0.06] px-3 py-2">
              <dt className="flex items-center gap-2 text-[12px] font-semibold"><span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ background: color }} />{c(title)}</dt>
              <dd className="mt-0.5 text-[11px] leading-5 text-[#C5D3CB]">{c(hint)}</dd>
            </div>
          ))}
        </dl>
      </header>

      <nav role="tablist" aria-label={c("navLabel")} className="mt-4 flex gap-1 overflow-x-auto rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-1.5">
        {TABS.map((key) => {
          const Icon = TAB_ICONS[key];
          const active = key === tab;
          return (
            <button key={key} type="button" role="tab" aria-selected={active} onClick={() => select({ tab: key })}
              className="inline-flex min-h-[44px] flex-shrink-0 items-center gap-2 rounded-xl px-3.5 text-[13px] font-semibold transition-colors"
              style={{ background: active ? "#10231B" : "transparent", color: active ? "#FFFFFF" : "#526057" }}>
              <Icon className="h-4 w-4" />{c(TAB_KEYS[key])}
            </button>
          );
        })}
      </nav>

      {error ? (
        <div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#F0C6B8] bg-[#FFF5F1] px-4 py-3 text-[13px] text-[#8B321B]">
          <span className="min-w-0 break-words">{error}</span>
          <button type="button" onClick={() => void loadOverview()} className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-[#E5B9A9] bg-white px-3 font-semibold"><RefreshCw className="h-4 w-4" />{t("fieldIntel.retry")}</button>
        </div>
      ) : null}

      <div className="mt-4" role="tabpanel">
        {!workspaceId ? <Card><p className="text-[14px] text-[#65736A]">{c("workspaceMissing")}</p></Card> : null}
        {workspaceId && loading && !overview ? (
          <div className="flex min-h-[30vh] items-center justify-center gap-2 text-[13px] text-[#2D6A4F]"><Loader2 className="h-5 w-5 animate-spin" />{c("loading")}</div>
        ) : null}

        {workspaceId && overview && tab === "overview" ? (
          <OverviewPanel text={text} overview={overview} onOpen={(id) => select({ tab: "health", field: id })} />
        ) : null}
        {workspaceId && overview && tab === "health" ? (
          <HealthPanel text={text} fields={fields} fieldId={fieldId} workspaceId={workspaceId} onSelectField={(id) => select({ field: id })} />
        ) : null}
        {workspaceId && tab === "production" ? (
          <ProductionPanel text={text} allowed={allowed} field={selectedField} />
        ) : null}
        {workspaceId && tab === "harvest" ? (
          <HarvestWindowPanel text={text} allowed={allowed} profiles={profiles} initialCrop={fieldCrop} />
        ) : null}
        {workspaceId && tab === "maturity" ? (
          <MaturityPanel text={text} allowed={allowed} profiles={profiles} initialCrop={fieldCrop} />
        ) : null}
      </div>
    </div>
  );
}

function OverviewPanel({ text, overview, onOpen }: { text: CropText; overview: CropOverview; onOpen: (fieldId: string) => void }) {
  const { c } = text;
  const totals = overview.totals;
  if (!overview.fields.length) {
    return (
      <Card className="text-center">
        <Sprout className="mx-auto h-9 w-9 text-[#2D6A4F]" />
        <h2 className="mt-3 text-[18px] font-semibold text-[#10231B]">{c("emptyTitle")}</h2>
        <p className="mx-auto mt-2 max-w-xl text-[13px] leading-6 text-[#65736A]">{c("emptyBody")}</p>
        <Link to="/field-intelligence" className="mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#10231B] px-4 text-[13px] font-semibold text-white"><Radio className="h-4 w-4" />{c("openField")}</Link>
        {totals.unassigned_observations ? <p className="mt-4 text-[12px] text-[#7B877F]">{c("kpiUnassigned")}: {totals.unassigned_observations}</p> : null}
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {([
          ["kpiFields", totals.fields],
          ["kpiAttention", totals.fields_needing_attention],
          ["kpiCrops", totals.supported_crops.length],
          ["kpiUnassigned", totals.unassigned_observations],
        ] as const).map(([key, value]) => (
          <div key={key} className="min-w-0 rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#65736A]">{c(key)}</div>
            <div className="mt-2 text-[26px] font-semibold text-[#10231B]" style={key === "kpiAttention" && value ? { color: "#9A4A06" } : undefined}>{value}</div>
          </div>
        ))}
      </div>
      <p className="text-[12px] text-[#65736A]">{c("overviewNote")}{overview.window_truncated ? ` ${c("windowTruncated")}` : ""}</p>
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {overview.fields.map((field) => <FieldCard key={field.field_id} text={text} field={field} onOpen={() => onOpen(field.field_id)} />)}
      </div>
    </div>
  );
}

function FieldCard({ text, field, onOpen }: { text: CropText; field: OverviewField; onOpen: () => void }) {
  const { c, cf, t, locale } = text;
  const latest = field.latest_assessment;
  const severity = latest?.severity || "";
  const visibleAttention = field.attention.filter((code) => ATTENTION_KEYS[code]);
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-[16px] font-semibold text-[#10231B]">{field.field_name || t("fieldIntel.unassignedField")}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-[#65736A]">
            <Sprout className="h-3.5 w-3.5 text-[#2D6A4F]" />
            <span className="truncate">{field.crop_profile?.display_name || field.crop || c("cropNotRecorded")}</span>
            {field.crop_profile?.benchmark_only ? <Chip>{c("benchmarkOnly")}</Chip> : null}
            {field.crop && !field.crop_profile ? <Chip>{c("cropNotSupported")}</Chip> : null}
          </div>
          {field.crop_profile?.validation_status === "unvalidated" ? <p className="mt-1 text-[11px] text-[#7B877F]">{c("unvalidatedProfile")}</p> : null}
        </div>
        {latest ? <Chip tone={FRESHNESS_TONE[latest.freshness]}>{c(FRESHNESS_KEYS[latest.freshness] || "freshUnknown")}</Chip> : null}
      </div>
      <div className="mt-4 rounded-xl bg-[#F7F5EF] p-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#65736A]">{c("latestAssessment")}</div>
        {latest ? (
          <div className="mt-2 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              {SEVERITY_TONE[severity] ? <Chip tone={SEVERITY_TONE[severity]}>{t(`fieldIntel.sev.${severity}`)}</Chip> : null}
              <span className="text-[12px] text-[#526057]">{formatDate(latest.observed_at, locale)}</span>
              {latest.block_name ? <span className="text-[12px] text-[#526057]">· {t("fieldIntel.block")} {latest.block_name}</span> : null}
            </div>
            {latest.summary ? <p className="line-clamp-3 text-[13px] leading-6 text-[#10231B]">{latest.summary}</p> : null}
          </div>
        ) : <p className="mt-2 text-[13px] text-[#65736A]">{c("noAssessment")}</p>}
      </div>
      {visibleAttention.length ? (
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label={c("kpiAttention")}>
          {visibleAttention.map((code) => (
            <li key={code}><Chip tone={code === "crop_not_recorded" ? undefined : { background: "#FFF1E3", color: "#8A4307" }}><AlertTriangle className="h-3 w-3" />{c(ATTENTION_KEYS[code])}</Chip></li>
          ))}
        </ul>
      ) : null}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-[12px] text-[#65736A]">
        <span>{cf("recordsTemplate", { count: field.observations })}{field.blocks ? ` · ${cf("blocksTemplate", { count: field.blocks })}` : ""}</span>
        <button type="button" onClick={onOpen} className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-[#10231B] px-3 text-[12px] font-semibold text-white">{c("viewHealth")}<ArrowRight className="h-3.5 w-3.5" /></button>
      </div>
    </Card>
  );
}

function HealthPanel({ text, fields, fieldId, workspaceId, onSelectField }: {
  text: CropText; fields: OverviewField[]; fieldId: string; workspaceId: string; onSelectField: (fieldId: string) => void;
}) {
  const { c, cf, t, locale } = text;
  const [condition, setCondition] = useState<CropCondition | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const activeField = fieldId || fields[0]?.field_id || "";

  useEffect(() => {
    if (!activeField) return;
    let active = true;
    setLoading(true);
    setError("");
    (apiClient.fieldIntelligence.fieldCropCondition(activeField, workspaceId) as Promise<CropCondition>)
      .then((result) => { if (active) setCondition(result); })
      .catch((cause) => { if (active) setError((cause as ApiError)?.message || c("failed")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // c is stable for a locale; re-fetch only when the field or workspace changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeField, workspaceId]);

  if (!fields.length) return <Card><p className="text-[13px] text-[#65736A]">{c("emptyBody")}</p></Card>;
  const latest = condition?.latest;
  const comparison = condition?.comparison;
  const comparisonText = !comparison ? "" : comparison.basis === "same_block_same_method"
    ? cf("comparedSame", { hours: comparison.gap_hours ?? "—" })
    : comparison.reason === "observation_has_no_block" ? c("comparedNoBlock")
      : comparison.reason === "visual_evidence_not_analysed" ? c("comparedUnanalysed")
        : comparison.reason === "no_completed_crop_assessment" || comparison.reason === "no_observations" ? c("comparedNoAssessment")
          : c("comparedNone");

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0 space-y-4">
        <Card>
          <label className="block text-[11px] font-semibold uppercase tracking-[0.12em] text-[#65736A]" htmlFor="crop-health-field">{t("fieldIntel.field")}</label>
          <select id="crop-health-field" value={activeField} onChange={(event) => onSelectField(event.target.value)}
            className="mt-1.5 min-h-[44px] w-full rounded-xl border border-[#D6DDD0] bg-white px-3 text-[14px]">
            {fields.map((field) => <option key={field.field_id} value={field.field_id}>{field.field_name || field.field_id}{field.crop ? ` · ${field.crop}` : ""}</option>)}
          </select>
        </Card>

        {loading ? <div className="flex items-center gap-2 text-[13px] text-[#2D6A4F]"><Loader2 className="h-4 w-4 animate-spin" />{c("loading")}</div> : null}
        {error ? <div role="alert" className="rounded-xl border border-[#F0C6B8] bg-[#FFF5F1] px-4 py-3 text-[13px] text-[#8B321B]">{error}</div> : null}

        {condition && !loading ? (
          <>
            <Card>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#2D6A4F]"><span className="h-2 w-2 rounded-full bg-[#92C7A9]" />{c("legendEvidence")}</div>
                  <h2 className="mt-1 text-[18px] font-semibold text-[#10231B]">{c("latestAssessment")}</h2>
                </div>
                {latest ? <Chip tone={FRESHNESS_TONE[latest.freshness]}>{c(FRESHNESS_KEYS[latest.freshness] || "freshUnknown")}</Chip> : null}
              </div>
              {!latest ? <p className="mt-3 text-[13px] text-[#65736A]">{c("noAssessment")}</p> : (
                <div className="mt-3 space-y-3">
                  <div className="flex flex-wrap items-center gap-2 text-[12px] text-[#526057]">
                    {SEVERITY_TONE[latest.severity] ? <Chip tone={SEVERITY_TONE[latest.severity]}>{t(`fieldIntel.sev.${latest.severity}`)}</Chip> : null}
                    <span>{formatDate(latest.observed_at, locale)}</span>
                    {latest.block_name ? <span>· {t("fieldIntel.block")} {latest.block_name}</span> : null}
                    <span>· {eventLabel(t, latest.event_type)}</span>
                  </div>
                  {latest.summary ? <p className="text-[14px] leading-7 text-[#10231B]">{latest.summary}</p> : null}
                  {latest.visual ? (
                    <div className="rounded-xl border border-[#E2E7DE] bg-[#F7F5EF] p-3 text-[13px] text-[#10231B]">
                      <div className="font-semibold">{c("visualAnalysis")}</div>
                      {latest.visual.crop_condition ? <div className="mt-1">{t("fieldIntel.cropCondition")}: {latest.visual.crop_condition}</div> : null}
                      {typeof latest.visual.confidence === "number" && Number.isFinite(latest.visual.confidence) && latest.visual.confidence >= 0 && latest.visual.confidence <= 1
                        ? <div className="mt-1">{t("fieldIntel.confidence")}: {Math.round(latest.visual.confidence * 100)}%</div> : null}
                      <p className="mt-1 text-[12px] text-[#65736A]">{c("confidenceUncalibrated")}</p>
                    </div>
                  ) : null}
                  {latest.detections?.length ? (
                    <div className="text-[13px] text-[#10231B]">
                      <div className="font-semibold">{c("countedObjects")}</div>
                      <ul className="mt-1 space-y-0.5">{latest.detections.map((row) => <li key={row.label}>{row.label}: {row.observed_lower_bound}–{row.sum_upper_bound}</li>)}</ul>
                    </div>
                  ) : null}
                  {latest.review_required ? <p className="flex items-start gap-2 rounded-xl bg-[#FFF6D6] px-3 py-2 text-[12px] text-[#7A5A00]"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />{c("reviewRequired")}</p> : null}
                  <Link to={`/field-intelligence?observation=${encodeURIComponent(latest.observation_id)}`} className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-[#C7D2C9] bg-white px-3 text-[13px] font-semibold text-[#234224]"><FileSearch className="h-4 w-4" />{c("openInField")}</Link>
                </div>
              )}
            </Card>

            <Card>
              <h2 className="text-[16px] font-semibold text-[#10231B]">{c("whatChanged")}</h2>
              <p className="mt-1 text-[12px] leading-5 text-[#65736A]">{comparisonText}</p>
              {condition.changes.length ? (
                <ul className="mt-3 space-y-2">
                  {condition.changes.map((change, index) => (
                    <li key={`${change.kind}-${index}`} className="rounded-xl border border-[#E2E7DE] p-3 text-[13px]">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-semibold text-[#10231B]">{CHANGE_KEYS[change.kind] ? c(CHANGE_KEYS[change.kind]) : change.kind}</span>
                        {change.trend === true ? <Chip tone={{ background: "#E7F4EC", color: "#1F6A45" }}>{c("trend")}</Chip> : null}
                      </div>
                      {change.from && change.to ? <div className="mt-1 text-[#526057]">{t(`fieldIntel.sev.${change.from}`)} → {t(`fieldIntel.sev.${change.to}`)}</div> : null}
                      {change.issues?.length ? <div className="mt-1 text-[#526057]">{change.issues.join(" · ")}</div> : null}
                      {change.label && change.previous_bounds && change.latest_bounds ? <div className="mt-1 text-[#526057]">{change.label}: {change.previous_bounds.join("–")} → {change.latest_bounds.join("–")}</div> : null}
                      {change.trend === false ? <div className="mt-1 text-[12px] text-[#7A5A00]">{c("notTrend")}</div> : null}
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-3 text-[13px] text-[#65736A]">{c("noChanges")}</p>}
            </Card>
          </>
        ) : null}
      </div>

      {condition && !loading ? (
        <aside className="min-w-0 space-y-4">
          <Card>
            <h2 className="text-[15px] font-semibold text-[#10231B]">{c("blocksTitle")}</h2>
            <p className="mt-1 text-[12px] text-[#65736A]">{c("blocksNote")}</p>
            <ul className="mt-3 space-y-2">
              {condition.field_snapshot.blocks.map((block) => (
                <li key={block.block_key} className="flex items-center justify-between gap-2 text-[13px]">
                  <span className="min-w-0 truncate text-[#10231B]">{block.block_name || t("fieldIntel.field")}</span>
                  {SEVERITY_TONE[block.severity] ? <Chip tone={SEVERITY_TONE[block.severity]}>{t(`fieldIntel.sev.${block.severity}`)}</Chip> : null}
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <h2 className="text-[15px] font-semibold text-[#10231B]">{c("recentRecords")}</h2>
            <dl className="mt-2 grid grid-cols-3 gap-2 text-center text-[11px] text-[#65736A]">
              <div className="rounded-lg bg-[#F7F5EF] p-2"><dt>{c("waitingReview")}</dt><dd className="mt-1 text-[16px] font-semibold text-[#10231B]">{condition.open_reviews}</dd></div>
              <div className="rounded-lg bg-[#F7F5EF] p-2"><dt>{t("fieldIntel.state.processing")}</dt><dd className="mt-1 text-[16px] font-semibold text-[#10231B]">{condition.pending_processing}</dd></div>
              <div className="rounded-lg bg-[#F7F5EF] p-2"><dt>{c("withoutEvidence")}</dt><dd className="mt-1 text-[16px] font-semibold text-[#10231B]">{condition.records_without_evidence}</dd></div>
            </dl>
            <ol className="mt-3 space-y-1.5">
              {condition.timeline.slice(0, 12).map((row) => (
                <li key={row.observation_id}>
                  <Link to={`/field-intelligence?observation=${encodeURIComponent(row.observation_id)}`} className="flex min-h-[40px] items-center justify-between gap-2 rounded-lg px-2 text-[12px] hover:bg-[#F7F5EF]">
                    <span className="min-w-0 truncate text-[#10231B]">{formatDate(row.observed_at, locale)} · {eventLabel(t, row.event_type)}</span>
                    {SEVERITY_TONE[row.severity] ? <Chip tone={SEVERITY_TONE[row.severity]}>{t(`fieldIntel.sev.${row.severity}`)}</Chip> : null}
                  </Link>
                </li>
              ))}
            </ol>
          </Card>
        </aside>
      ) : null}
    </div>
  );
}
