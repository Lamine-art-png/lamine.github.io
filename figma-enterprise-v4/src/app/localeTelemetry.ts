import { API_BASE_URL } from "./api/client";
import { sourceFingerprint } from "../../../shared/localization/source.json";

export type LocaleEventName =
  | "locale_switch_requested"
  | "locale_switch_completed"
  | "locale_switch_failed"
  | "locale_catalog_missing"
  | "locale_catalog_version_mismatch"
  | "locale_fallback_triggered"
  | "locale_verification_opened"
  | "locale_recovery_opened";

const RELEASE_SHA = String(import.meta.env.VITE_BUILD_SHA || "").trim().slice(0, 64);
const CATALOG_VERSION = String(sourceFingerprint || "").slice(0, 16);
const REPORTED = new Set<string>();

/**
 * Fire-and-forget locale health event. Contains locale codes, release/catalog
 * identifiers, a surface name and timings only — never user identity or copy.
 */
export function reportLocaleEvent(
  event: LocaleEventName,
  detail: { selectedLocale: string; effectiveLocale: string; surface?: string; success?: boolean; latencyMs?: number; missingKeys?: number },
  { once = false }: { once?: boolean } = {},
) {
  const dedupe = `${event}:${detail.effectiveLocale}:${detail.surface || ""}`;
  if (once && REPORTED.has(dedupe)) return;
  REPORTED.add(dedupe);
  const body = JSON.stringify({
    event,
    selectedLocale: detail.selectedLocale,
    effectiveLocale: detail.effectiveLocale,
    catalogVersion: CATALOG_VERSION,
    releaseSha: RELEASE_SHA,
    surface: (detail.surface || (typeof window !== "undefined" ? window.location.pathname : "")).slice(0, 64),
    success: detail.success ?? true,
    latencyMs: detail.latencyMs === undefined ? undefined : Math.max(0, Math.round(detail.latencyMs)),
    missingKeys: detail.missingKeys,
  });
  const failure = detail.success === false || /missing|mismatch|fallback|failed/.test(event);
  if (failure) console.error("[agroai-locale]", event, detail);
  try {
    const url = `${API_BASE_URL.replace(/\/+$/, "")}/v1/i18n/events`;
    void fetch(url, { method: "POST", body, headers: { "content-type": "application/json" }, keepalive: true, credentials: "omit" }).catch(() => undefined);
  } catch {
    // Observability must never affect the customer experience.
  }
}
