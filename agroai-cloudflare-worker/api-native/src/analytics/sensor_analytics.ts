/**
 * Sensor Analytics — real intelligence on irrigation data.
 *
 * No LLM wrapper. Pure SQL + math:
 *   - Anomaly detection: flag readings >2σ from rolling mean
 *   - Trend analysis: linear regression on recent windows
 *   - Smart alerts: threshold violations + sustained conditions
 */

// ── Types ───────────────────────────────────────────────

export interface SensorAnomaly {
  sensor_uid: string;
  sensor_name: string | null;
  units: string | null;
  current_value: number;
  mean: number;
  stddev: number;
  z_score: number;
  direction: "high" | "low";
  observed_at: string;
  severity: "warning" | "critical";
}

export interface SensorTrend {
  sensor_uid: string;
  sensor_name: string | null;
  units: string | null;
  direction: "rising" | "falling" | "stable";
  slope_per_hour: number;
  current_value: number;
  value_24h_ago: number | null;
  change_pct: number | null;
  data_points: number;
  confidence: "high" | "medium" | "low";
}

export interface SensorAlert {
  sensor_uid: string;
  sensor_name: string | null;
  units: string | null;
  alert_type: string;
  message: string;
  current_value: number;
  threshold: number | null;
  severity: "info" | "warning" | "critical";
  observed_at: string;
}

// ── Anomaly Detection ───────────────────────────────────
// For each sensor, compute mean + stddev over a recent window.
// Flag any sensor whose LATEST reading is >2σ from the mean.

export async function detectAnomalies(
  db: D1Database,
  tenantId: string,
  windowHours: number = 168, // 7 days default
): Promise<SensorAnomaly[]> {
  const windowMs = windowHours * 3_600_000;
  const cutoffMs = Date.now() - windowMs;

  // Single query: compute stats per sensor + get latest value
  const rows = await db
    .prepare(
      `WITH sensor_stats AS (
         SELECT
           sl.sensor_uid,
           AVG(sl.value_num) AS mean_val,
           -- Manual stddev since D1/SQLite doesn't have STDDEV
           SQRT(AVG(sl.value_num * sl.value_num) - AVG(sl.value_num) * AVG(sl.value_num)) AS stddev_val,
           COUNT(*) AS data_points
         FROM talgil_sensor_log sl
         WHERE sl.tenant_id = ?
           AND sl.observed_at_ms >= ?
           AND sl.value_num IS NOT NULL
         GROUP BY sl.sensor_uid
         HAVING COUNT(*) >= 10 AND stddev_val > 0
       ),
       latest AS (
         SELECT
           sl.sensor_uid,
           sl.value_num AS current_value,
           sl.observed_at,
           ROW_NUMBER() OVER (PARTITION BY sl.sensor_uid ORDER BY sl.observed_at_ms DESC) AS rn
         FROM talgil_sensor_log sl
         WHERE sl.tenant_id = ?
           AND sl.value_num IS NOT NULL
       )
       SELECT
         s.sensor_uid,
         sc.sensor_name,
         sc.units,
         l.current_value,
         s.mean_val,
         s.stddev_val,
         (l.current_value - s.mean_val) / s.stddev_val AS z_score,
         l.observed_at
       FROM sensor_stats s
       JOIN latest l ON l.sensor_uid = s.sensor_uid AND l.rn = 1
       LEFT JOIN talgil_sensor_catalog sc
         ON sc.tenant_id = ? AND sc.sensor_uid = s.sensor_uid
       WHERE ABS((l.current_value - s.mean_val) / s.stddev_val) > 2
       ORDER BY ABS((l.current_value - s.mean_val) / s.stddev_val) DESC`,
    )
    .bind(tenantId, cutoffMs, tenantId, tenantId)
    .all<{
      sensor_uid: string;
      sensor_name: string | null;
      units: string | null;
      current_value: number;
      mean_val: number;
      stddev_val: number;
      z_score: number;
      observed_at: string;
    }>();

  return (rows.results ?? []).map((r) => {
    const absZ = Math.abs(r.z_score);
    return {
      sensor_uid: r.sensor_uid,
      sensor_name: r.sensor_name,
      units: r.units,
      current_value: round(r.current_value),
      mean: round(r.mean_val),
      stddev: round(r.stddev_val),
      z_score: round(r.z_score),
      direction: r.z_score > 0 ? "high" as const : "low" as const,
      observed_at: r.observed_at,
      severity: absZ > 3 ? "critical" as const : "warning" as const,
    };
  });
}

// ── Trend Analysis ──────────────────────────────────────
// For each sensor, compute a simple linear regression over recent data.
// slope > threshold = rising, slope < -threshold = falling, else stable.

export async function analyzeTrends(
  db: D1Database,
  tenantId: string,
  windowHours: number = 24,
): Promise<SensorTrend[]> {
  const windowMs = windowHours * 3_600_000;
  const nowMs = Date.now();
  const cutoffMs = nowMs - windowMs;
  const cutoff24h = nowMs - 24 * 3_600_000;

  // Linear regression: slope = (n*Σ(xy) - Σx*Σy) / (n*Σ(x²) - (Σx)²)
  // where x = time in hours from cutoff, y = value
  const rows = await db
    .prepare(
      `WITH regression AS (
         SELECT
           sl.sensor_uid,
           COUNT(*) AS n,
           SUM((sl.observed_at_ms - ?) / 3600000.0) AS sum_x,
           SUM(sl.value_num) AS sum_y,
           SUM((sl.observed_at_ms - ?) / 3600000.0 * sl.value_num) AS sum_xy,
           SUM((sl.observed_at_ms - ?) / 3600000.0 * (sl.observed_at_ms - ?) / 3600000.0) AS sum_x2
         FROM talgil_sensor_log sl
         WHERE sl.tenant_id = ?
           AND sl.observed_at_ms >= ?
           AND sl.value_num IS NOT NULL
         GROUP BY sl.sensor_uid
         HAVING COUNT(*) >= 5
       ),
       latest AS (
         SELECT sensor_uid, value_num AS current_value,
                ROW_NUMBER() OVER (PARTITION BY sensor_uid ORDER BY observed_at_ms DESC) AS rn
         FROM talgil_sensor_log
         WHERE tenant_id = ? AND value_num IS NOT NULL
       ),
       oldest AS (
         SELECT sensor_uid, value_num AS old_value,
                ROW_NUMBER() OVER (PARTITION BY sensor_uid ORDER BY ABS(observed_at_ms - ?) ASC) AS rn
         FROM talgil_sensor_log
         WHERE tenant_id = ? AND value_num IS NOT NULL AND observed_at_ms >= ?
       )
       SELECT
         r.sensor_uid,
         sc.sensor_name,
         sc.units,
         r.n AS data_points,
         CASE WHEN (r.n * r.sum_x2 - r.sum_x * r.sum_x) != 0
           THEN (r.n * r.sum_xy - r.sum_x * r.sum_y) / (r.n * r.sum_x2 - r.sum_x * r.sum_x)
           ELSE 0
         END AS slope,
         l.current_value,
         o.old_value AS value_24h_ago
       FROM regression r
       JOIN latest l ON l.sensor_uid = r.sensor_uid AND l.rn = 1
       LEFT JOIN oldest o ON o.sensor_uid = r.sensor_uid AND o.rn = 1
       LEFT JOIN talgil_sensor_catalog sc
         ON sc.tenant_id = ? AND sc.sensor_uid = r.sensor_uid
       ORDER BY ABS(CASE WHEN (r.n * r.sum_x2 - r.sum_x * r.sum_x) != 0
           THEN (r.n * r.sum_xy - r.sum_x * r.sum_y) / (r.n * r.sum_x2 - r.sum_x * r.sum_x)
           ELSE 0 END) DESC`,
    )
    .bind(
      cutoffMs, cutoffMs, cutoffMs, cutoffMs, // sum_x, sum_xy, sum_x2 calculations
      tenantId, cutoffMs,                       // main query
      tenantId,                                  // latest subquery
      cutoff24h, tenantId, cutoff24h,           // oldest subquery
      tenantId,                                  // catalog join
    )
    .all<{
      sensor_uid: string;
      sensor_name: string | null;
      units: string | null;
      data_points: number;
      slope: number;
      current_value: number;
      value_24h_ago: number | null;
    }>();

  return (rows.results ?? []).map((r) => {
    // Determine threshold for "meaningful" trend based on value magnitude
    const magnitude = Math.max(Math.abs(r.current_value), 1);
    const slopeThreshold = magnitude * 0.01; // 1% per hour is significant

    let direction: "rising" | "falling" | "stable";
    if (r.slope > slopeThreshold) direction = "rising";
    else if (r.slope < -slopeThreshold) direction = "falling";
    else direction = "stable";

    const changePct = r.value_24h_ago != null && r.value_24h_ago !== 0
      ? round(((r.current_value - r.value_24h_ago) / Math.abs(r.value_24h_ago)) * 100)
      : null;

    return {
      sensor_uid: r.sensor_uid,
      sensor_name: r.sensor_name,
      units: r.units,
      direction,
      slope_per_hour: round(r.slope),
      current_value: round(r.current_value),
      value_24h_ago: r.value_24h_ago != null ? round(r.value_24h_ago) : null,
      change_pct: changePct,
      data_points: r.data_points,
      confidence: r.data_points >= 20 ? "high" as const
        : r.data_points >= 10 ? "medium" as const
        : "low" as const,
    };
  });
}

// ── Smart Alerts ────────────────────────────────────────
// Check for threshold violations, sustained conditions, and data gaps.

export async function checkAlerts(
  db: D1Database,
  tenantId: string,
): Promise<SensorAlert[]> {
  const alerts: SensorAlert[] = [];
  const nowMs = Date.now();

  // 1. Threshold violations: sensors outside their configured min/max limits
  const thresholdRows = await db
    .prepare(
      `WITH latest AS (
         SELECT sensor_uid, value_num, observed_at, observed_at_ms,
                ROW_NUMBER() OVER (PARTITION BY sensor_uid ORDER BY observed_at_ms DESC) AS rn
         FROM talgil_sensor_log
         WHERE tenant_id = ? AND value_num IS NOT NULL
       )
       SELECT
         l.sensor_uid,
         sc.sensor_name,
         sc.units,
         l.value_num AS current_value,
         l.observed_at,
         sc.min_limit,
         sc.max_limit,
         sc.low_threshold,
         sc.high_threshold
       FROM latest l
       JOIN talgil_sensor_catalog sc
         ON sc.tenant_id = ? AND sc.sensor_uid = l.sensor_uid
       WHERE l.rn = 1
         AND (
           (sc.max_limit IS NOT NULL AND l.value_num > sc.max_limit)
           OR (sc.min_limit IS NOT NULL AND l.value_num < sc.min_limit)
           OR (sc.high_threshold IS NOT NULL AND l.value_num > sc.high_threshold)
           OR (sc.low_threshold IS NOT NULL AND l.value_num < sc.low_threshold)
         )`,
    )
    .bind(tenantId, tenantId)
    .all<{
      sensor_uid: string;
      sensor_name: string | null;
      units: string | null;
      current_value: number;
      observed_at: string;
      min_limit: number | null;
      max_limit: number | null;
      low_threshold: number | null;
      high_threshold: number | null;
    }>();

  for (const r of thresholdRows.results ?? []) {
    const unit = r.units ? ` ${r.units}` : "";
    if (r.max_limit != null && r.current_value > r.max_limit) {
      alerts.push({
        sensor_uid: r.sensor_uid,
        sensor_name: r.sensor_name,
        units: r.units,
        alert_type: "above_max_limit",
        message: `${r.sensor_name ?? r.sensor_uid} at ${r.current_value}${unit} — exceeds max limit of ${r.max_limit}${unit}`,
        current_value: r.current_value,
        threshold: r.max_limit,
        severity: "critical",
        observed_at: r.observed_at,
      });
    } else if (r.min_limit != null && r.current_value < r.min_limit) {
      alerts.push({
        sensor_uid: r.sensor_uid,
        sensor_name: r.sensor_name,
        units: r.units,
        alert_type: "below_min_limit",
        message: `${r.sensor_name ?? r.sensor_uid} at ${r.current_value}${unit} — below min limit of ${r.min_limit}${unit}`,
        current_value: r.current_value,
        threshold: r.min_limit,
        severity: "critical",
        observed_at: r.observed_at,
      });
    } else if (r.high_threshold != null && r.current_value > r.high_threshold) {
      alerts.push({
        sensor_uid: r.sensor_uid,
        sensor_name: r.sensor_name,
        units: r.units,
        alert_type: "above_high_threshold",
        message: `${r.sensor_name ?? r.sensor_uid} at ${r.current_value}${unit} — above high threshold of ${r.high_threshold}${unit}`,
        current_value: r.current_value,
        threshold: r.high_threshold,
        severity: "warning",
        observed_at: r.observed_at,
      });
    } else if (r.low_threshold != null && r.current_value < r.low_threshold) {
      alerts.push({
        sensor_uid: r.sensor_uid,
        sensor_name: r.sensor_name,
        units: r.units,
        alert_type: "below_low_threshold",
        message: `${r.sensor_name ?? r.sensor_uid} at ${r.current_value}${unit} — below low threshold of ${r.low_threshold}${unit}`,
        current_value: r.current_value,
        threshold: r.low_threshold,
        severity: "warning",
        observed_at: r.observed_at,
      });
    }
  }

  // 2. Data gap alerts: sensors that haven't reported in >2 hours
  const gapRows = await db
    .prepare(
      `SELECT
         sc.sensor_uid,
         sc.sensor_name,
         sc.units,
         MAX(sl.observed_at_ms) AS last_ms,
         MAX(sl.observed_at) AS last_at
       FROM talgil_sensor_catalog sc
       LEFT JOIN talgil_sensor_log sl
         ON sl.tenant_id = sc.tenant_id AND sl.sensor_uid = sc.sensor_uid
       WHERE sc.tenant_id = ?
       GROUP BY sc.sensor_uid
       HAVING last_ms IS NOT NULL AND last_ms < ?`,
    )
    .bind(tenantId, nowMs - 2 * 3_600_000)
    .all<{
      sensor_uid: string;
      sensor_name: string | null;
      units: string | null;
      last_ms: number;
      last_at: string;
    }>();

  for (const r of gapRows.results ?? []) {
    const hoursAgo = round((nowMs - r.last_ms) / 3_600_000);
    alerts.push({
      sensor_uid: r.sensor_uid,
      sensor_name: r.sensor_name,
      units: r.units,
      alert_type: "data_gap",
      message: `${r.sensor_name ?? r.sensor_uid} — no data for ${hoursAgo} hours (last: ${r.last_at})`,
      current_value: 0,
      threshold: null,
      severity: hoursAgo > 6 ? "critical" : "warning",
      observed_at: r.last_at,
    });
  }

  // Sort: critical first, then warning
  alerts.sort((a, b) => {
    const severityOrder = { critical: 0, warning: 1, info: 2 };
    return severityOrder[a.severity] - severityOrder[b.severity];
  });

  return alerts;
}

// ── Helper ──────────────────────────────────────────────

function round(n: number, decimals: number = 2): number {
  const factor = Math.pow(10, decimals);
  return Math.round(n * factor) / factor;
}
