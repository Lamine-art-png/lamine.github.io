import type { CropCopyKey } from "./cropIntelligenceCopy";

export type CopyValues = Record<string, string | number | undefined>;

export type CropText = {
  c: (key: CropCopyKey) => string;
  cf: (key: CropCopyKey, values: CopyValues) => string;
  t: (key: string) => string;
  locale: string | undefined;
};

export function isShare(value: number): boolean {
  return value > 0 && value <= 1;
}

export function invalidCount(value: number): boolean {
  return !Number.isFinite(value) || value < 0;
}

export function invalidStratum(row: { stratum_id: string; population_units: number; sample_counts: { invalid: number } }): boolean {
  return Boolean(row.sample_counts.invalid) || !Number.isInteger(row.population_units) || row.population_units < 1 || !row.stratum_id;
}

export type Interval = [number, number];
export type Freshness = "fresh" | "aging" | "stale" | "unknown" | "future_dated";

export type CropProfile = {
  crop_id: string;
  display_name: string;
  maturity_scale: string | null;
  maturity_stages: string[];
  degree_day_method: { method: string; base_c: number; upper_cutoff_c: number | null; source: string } | null;
  validation_status: string;
  benchmark_only: boolean;
};

export type OverviewField = {
  field_id: string;
  field_name: string | null;
  crop: string | null;
  observations: number;
  blocks: number;
  open_reviews: number;
  pending_processing: number;
  failed_processing: number;
  future_dated_excluded: number;
  latest_record: { observation_id: string; observed_at: string | null; freshness: Freshness } | null;
  latest_assessment: {
    observation_id: string; observed_at: string | null; freshness: Freshness; severity: string; status: string;
    block_name: string | null; method: string; summary: string | null; crop_condition: string | null; review_required: boolean;
  } | null;
  crop_profile: { crop_id: string; display_name: string; validation_status: string; benchmark_only: boolean; has_maturity_stages: boolean; has_degree_day_method: boolean } | null;
  attention: string[];
};

export type CropOverview = {
  fields: OverviewField[];
  totals: { fields: number; fields_needing_attention: number; supported_crops: string[]; observations_considered: number; unassigned_observations: number };
  window_truncated: boolean;
};

export type ConditionChange = {
  kind: string; trend?: boolean; from?: string; to?: string; issues?: string[]; label?: string;
  previous_bounds?: Interval; latest_bounds?: Interval; previous?: string; latest?: string; count?: number;
};

export type CropCondition = {
  summary_status: string;
  observations_considered: number;
  total_observations: number;
  latest: null | {
    observation_id: string; observed_at: string | null; freshness: Freshness; block_name: string | null; method: string;
    event_type: string; severity: string; status: string; summary: string | null; review_required: boolean;
    visual: null | { analysis_state: string; crop_condition: string | null; confidence: number | null; media_analyzed: number | null };
    detections: { label: string; observed_lower_bound: number; sum_upper_bound: number }[];
  };
  comparison: { basis: string; reason?: string; gap_hours?: number | null; spatial_coverage?: string };
  changes: ConditionChange[];
  field_snapshot: { blocks: { block_key: string; block_name: string | null; observation_id: string; observed_at: string; severity: string; method: string; status: string }[] };
  timeline: { observation_id: string; observed_at: string; block_key: string; method: string; event_type: string; severity: string; status: string }[];
  open_reviews: number;
  pending_processing: number;
  records_without_evidence: number;
};

export type MarketYieldHandoff = {
  version: 1;
  created_at: string;
  estimate_id: string;
  yield_per_area: string;
  quantity_unit: string;
  area_unit: string;
  note: string;
  basis: "marketable" | "total";
  interval: Interval | null;
  design: string;
  sampled_units: number;
  object_label: string;
};

export const FRESHNESS_KEYS: Record<Freshness, CropCopyKey> = {
  fresh: "freshFresh", aging: "freshAging", stale: "freshStale", unknown: "freshUnknown", future_dated: "attentionFutureDated",
};

export const ATTENTION_KEYS: Record<string, CropCopyKey> = {
  high_severity: "attentionHighSeverity",
  needs_review: "attentionNeedsReview",
  processing_failed: "attentionProcessingFailed",
  no_crop_assessment: "attentionNoAssessment",
  stale_evidence: "attentionStale",
  future_dated_records: "attentionFutureDated",
  crop_not_supported: "attentionCropNotSupported",
  crop_not_recorded: "cropNotRecorded",
};

export const CHANGE_KEYS: Record<string, CropCopyKey> = {
  severity_increased: "changeSeverityUp",
  severity_decreased: "changeSeverityDown",
  severity_differs: "changeSeverityDiffers",
  new_visible_issue: "changeNewIssue",
  issue_not_seen_again: "changeIssueGone",
  issue_seen_only_in_latest: "changeIssueLatestOnly",
  issue_seen_only_in_previous: "changeIssuePreviousOnly",
  detection_count_changed: "changeCount",
  different_observation_count: "changeCountDiffers",
  conflicting_recent_assessments: "changeConflict",
  stale_evidence: "changeStale",
  future_dated_records_excluded: "changeFuture",
};

export const STAGE_KEYS: Record<string, CropCopyKey> = {
  hull_intact: "stageHullIntact", hull_split: "stageHullSplit", hull_open_dry: "stageHullOpenDry",
  pre_veraison: "stagePreVeraison", veraison: "stageVeraison", post_veraison: "stagePostVeraison",
  green: "stageGreen", yellow_green: "stageYellowGreen", ripe_cherry: "stageRipeCherry", overripe_raisin: "stageOverripe",
  dry: "stageDry", breakers: "stageBreakers", turning: "stageTurning", pink: "stagePink", light_red: "stageLightRed", red: "stageRed",
};

export const ACTION_KEYS: Record<string, CropCopyKey> = {
  verify_maturity_by_sampling: "actionVerify",
  confirm_harvest_labor_and_equipment: "actionLabour",
  confirm_storage_transport_and_buyer_commitments: "actionLogistics",
};

// Each backend reason code (some carry a ":detail" suffix) maps to one plain-language need.
const REASON_PREFIXES: [string, CropCopyKey][] = [
  ["sample_units_with_objects", "reasonUnitsWithObjects"],
  ["sample_units", "reasonSampleUnits"],
  ["sampled_units", "reasonNumericRange"],
  ["non_probability_sample", "reasonNonProbability"],
  ["population_units_must_equal_the_sum", "reasonStrata"],
  ["population_units", "reasonPopulation"],
  ["sample_counts_must", "reasonCounts"],
  ["stage_counts_must", "reasonCounts"],
  ["counts_must_be_manual", "reasonDetector"],
  ["validated_detector", "reasonDetector"],
  ["detector_evaluation", "reasonDetector"],
  ["detection_rate", "reasonCalibration"],
  ["unit_weight_kg", "reasonCalibration"],
  ["marketable_fraction", "reasonCalibration"],
  ["area_hectares", "reasonArea"],
  ["strat", "reasonStrata"],
  ["zero_sample_variance", "reasonStrata"],
  ["inputs_outside_numeric_range", "reasonNumericRange"],
  ["maturity_target", "reasonTarget"],
  ["degree_day", "reasonMethod"],
  ["as_of_before_biofix", "reasonDates"],
  ["season_dates_outside", "reasonDates"],
  ["observed_weather_source", "reasonWeatherSource"],
  ["analog_weather_source", "reasonWeatherSource"],
  ["analog_", "reasonAnalog"],
  ["weather_series_missing_days", "reasonWeather"],
  ["duplicate_weather_day", "reasonWeather"],
  ["non_finite_temperature", "reasonWeather"],
  ["implausible_temperature", "reasonWeather"],
  ["tmax_below_tmin", "reasonWeather"],
  ["crop_profile_has_no_maturity_scale", "noMaturityScale"],
  ["stages_not_in_", "reasonStages"],
  ["duplicate_unit_ids", "reasonDuplicateUnits"],
  ["readiness_", "reasonReadiness"],
];

export function reasonCopyKey(code: string): CropCopyKey {
  const found = REASON_PREFIXES.find(([prefix]) => code.startsWith(prefix));
  return found ? found[1] : "reasonOther";
}

/** Unique plain-language needs for a list of reason codes, in first-seen order. */
export function reasonCopyKeys(codes: unknown): CropCopyKey[] {
  if (!Array.isArray(codes)) return [];
  return Array.from(new Set(codes.filter((code): code is string => typeof code === "string").map(reasonCopyKey)));
}

export function parseNumberList(text: string): { values: number[]; invalid: number } {
  const parts = text.split(/[\s,;]+/).map((part) => part.trim()).filter(Boolean);
  const values: number[] = [];
  let invalid = 0;
  for (const part of parts) {
    const value = Number(part);
    if (Number.isFinite(value) && value >= 0) values.push(value);
    else invalid += 1;
  }
  return { values, invalid };
}

export function optionalNumber(text: string): number | null {
  if (!text.trim()) return null;
  const value = Number(text.replace(",", "."));
  return Number.isFinite(value) ? value : Number.NaN;
}

export type WeatherDay = { date: string; tmax_c: number; tmin_c: number };

/** Parse "date, max °C, min °C" lines; header and unreadable lines are counted, never guessed. */
export function parseWeatherCsv(text: string): { days: WeatherDay[]; skipped: number } {
  const days: WeatherDay[] = [];
  let skipped = 0;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const cells = line.split(/[,;\t]/).map((cell) => cell.trim());
    const [day, tmax, tmin] = cells;
    const max = Number(tmax);
    const min = Number(tmin);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day || "") || Number.isNaN(Date.parse(`${day}T00:00:00Z`)) || !Number.isFinite(max) || !Number.isFinite(min)) {
      skipped += 1;
      continue;
    }
    days.push({ date: day, tmax_c: max, tmin_c: min });
  }
  return { days, skipped };
}

const DAY_MS = 86_400_000;
const ANALOG_HORIZON_DAYS = 240;

function sameDayInYear(isoDate: string, year: number): number {
  const [, month, day] = isoDate.split("-").map(Number);
  const candidate = Date.UTC(year, month - 1, day);
  // 29 February in a non-leap year becomes 28 February, as on the server.
  return new Date(candidate).getUTCMonth() === month - 1 ? candidate : Date.UTC(year, month - 1, 28);
}

/** Group earlier-season days into the server's analog seasons: season Y runs from
 * the as-of month/day in year Y for the next 240 days (it may cross New Year). */
export function groupAnalogSeasons(days: WeatherDay[], asOf: string): Record<string, WeatherDay[]> {
  const asOfYear = Number(asOf.slice(0, 4));
  const seasons: Record<string, WeatherDay[]> = {};
  for (const item of days) {
    const time = Date.parse(`${item.date}T00:00:00Z`);
    const year = Number(item.date.slice(0, 4));
    for (const season of [year, year - 1]) {
      if (season >= asOfYear) continue;
      const start = sameDayInYear(asOf, season);
      if (time > start && time <= start + ANALOG_HORIZON_DAYS * DAY_MS) {
        (seasons[String(season)] ||= []).push(item);
        break;
      }
    }
  }
  return seasons;
}

export function observedWindow(days: WeatherDay[], biofix: string, asOf: string): WeatherDay[] {
  return days.filter((item) => item.date >= biofix && item.date <= asOf);
}

const HANDOFF_KEY = "agroai_crop_yield_proposal_v1";

export function storeMarketHandoff(handoff: MarketYieldHandoff) {
  try {
    sessionStorage.setItem(HANDOFF_KEY, JSON.stringify(handoff));
  } catch {
    // Without session storage the proposal simply is not carried over.
  }
}

export function readMarketHandoff(): MarketYieldHandoff | null {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(HANDOFF_KEY) || "null");
    if (!parsed || parsed.version !== 1 || typeof parsed.yield_per_area !== "string" || !(Number(parsed.yield_per_area) > 0)) return null;
    return parsed as MarketYieldHandoff;
  } catch {
    return null;
  }
}

export function clearMarketHandoff() {
  try {
    sessionStorage.removeItem(HANDOFF_KEY);
  } catch {
    // Nothing to clear.
  }
}

export function calculatorsAllowed(entitlements: Record<string, unknown>): boolean {
  const capabilities = entitlements?.capabilities;
  if (!capabilities || typeof capabilities !== "object") return true; // the server decides
  const value = (capabilities as Record<string, unknown>)["intelligence.deep_analysis"];
  return value === undefined || value === true || value === "enabled" || value === "preview";
}
