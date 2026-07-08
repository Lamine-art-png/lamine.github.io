import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  ensureLocaleCatalog,
  hasCompleteLocaleCatalog,
  hasCoreLocaleCatalog,
  hasCriticalLocaleCatalog,
  primeLocaleCatalogFromCache,
} from "../dynamicLocaleCatalog";
import {
  applyLocale,
  canonicalizeSelectedLocale,
  getStoredLocale,
  normalizeLocale,
  resolveLocaleDetailed,
  setStoredLocale,
  t,
} from "../i18n";
import { FULL_UI_TRANSLATION_DIAGNOSTIC, purgeLegacyDynamicCatalogCache } from "../i18nReleaseCompatibility";
import { getLocaleRuntimeSnapshot, notifyLocaleRuntime, subscribeLocaleRuntime } from "../localeRuntimeStore";

let explicitLocaleActivated = false;
const RECOVERY_DELAYS_MS = [0, 800, 1_600, 3_000, 5_000] as const;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function primeKnownLocale(locale: string) {
  primeLocaleCatalogFromCache(locale, "critical");
  primeLocaleCatalogFromCache(locale, "core");
  primeLocaleCatalogFromCache(locale, "full");
}

export function useLocale() {
  const [selectedLocale, setSelectedLocaleState] = useState(getStoredLocale());
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const runtimeRevision = useSyncExternalStore(
    subscribeLocaleRuntime,
    getLocaleRuntimeSnapshot,
    getLocaleRuntimeSnapshot,
  );
  const effectiveLocale = useMemo(() => normalizeLocale(selectedLocale), [selectedLocale]);
  const resolution = useMemo(() => resolveLocaleDetailed(selectedLocale), [selectedLocale]);

  useEffect(() => {
    const listener = ((event: CustomEvent) => {
      const nextLocale = event.detail?.selectedLocale || event.detail?.locale || getStoredLocale();
      setSelectedLocaleState(nextLocale);
    }) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, []);

  useEffect(() => {
    applyLocale(selectedLocale);
  }, [selectedLocale]);

  useEffect(() => {
    let cancelled = false;

    async function hydrateSelectedLocale() {
      setCatalogError(null);
      if (effectiveLocale === "en") {
        setCatalogLoading(false);
        return;
      }

      purgeLegacyDynamicCatalogCache(effectiveLocale);
      primeKnownLocale(selectedLocale);
      if (hasCompleteLocaleCatalog(selectedLocale)) {
        setCatalogLoading(false);
        notifyLocaleRuntime();
        return;
      }

      setCatalogLoading(!hasCriticalLocaleCatalog(selectedLocale));

      for (let round = 0; round < RECOVERY_DELAYS_MS.length && !cancelled; round += 1) {
        if (RECOVERY_DELAYS_MS[round] > 0) await delay(RECOVERY_DELAYS_MS[round]);
        if (cancelled) return;

        try {
          if (!hasCriticalLocaleCatalog(selectedLocale)) {
            await ensureLocaleCatalog(selectedLocale, "critical");
          }
          if (cancelled) return;

          // Release the portal as soon as the navigation/settings shell is
          // translated. Every successful critical chunk is already durable.
          if (hasCriticalLocaleCatalog(selectedLocale)) {
            setCatalogLoading(false);
            notifyLocaleRuntime();
          }

          // Expand to the remaining bundled core copy. Reusable critical chunks
          // are merged first, so this stage requests only missing core keys.
          if (!hasCoreLocaleCatalog(selectedLocale)) {
            await ensureLocaleCatalog(selectedLocale, "core");
          }
          if (cancelled) return;
          notifyLocaleRuntime();

          // Full literal convergence likewise requests only keys still missing
          // after the durable critical and core stages.
          if (!hasCompleteLocaleCatalog(selectedLocale)) {
            await ensureLocaleCatalog(selectedLocale, "full");
          }
          if (cancelled) return;

          if (hasCompleteLocaleCatalog(selectedLocale)) {
            setCatalogError(null);
            setCatalogLoading(false);
            notifyLocaleRuntime();
            return;
          }

          throw new Error(`Full UI translation incomplete for ${selectedLocale}`);
        } catch (cause) {
          if (cancelled) return;
          const message = cause instanceof Error ? cause.message : "UI translation unavailable";
          console.warn(FULL_UI_TRANSLATION_DIAGNOSTIC, { locale: selectedLocale, round: round + 1, error: message });
          setCatalogError(message);
          // Never roll an explicit customer choice back to English because one
          // provider attempt failed. Validated chunks are durable and the next
          // round asks only for missing source keys.
          setCatalogLoading(false);
          notifyLocaleRuntime();
        }
      }
    }

    void hydrateSelectedLocale();
    return () => {
      cancelled = true;
    };
  }, [selectedLocale, effectiveLocale]);

  const setLocale = (nextLocale: string) => {
    const canonical = canonicalizeSelectedLocale(nextLocale);
    const current = getStoredLocale();
    const localChoiceIsExplicit = current !== "auto";
    if ((explicitLocaleActivated || localChoiceIsExplicit) && canonical !== current) {
      primeKnownLocale(current);
      setSelectedLocaleState(current);
      notifyLocaleRuntime();
      return current;
    }
    primeKnownLocale(canonical);
    const activated = setStoredLocale(canonical);
    setSelectedLocaleState(activated);
    notifyLocaleRuntime();
    return activated;
  };

  const activateLocale = (nextLocale: string) => {
    explicitLocaleActivated = true;
    const canonical = canonicalizeSelectedLocale(nextLocale);
    primeKnownLocale(canonical);
    const activated = setStoredLocale(canonical);
    setSelectedLocaleState(activated);
    setCatalogError(null);
    notifyLocaleRuntime();
    return activated;
  };

  return {
    selectedLocale,
    effectiveLocale,
    locale: selectedLocale,
    normalizedLocale: effectiveLocale,
    resolution,
    setLocale,
    activateLocale,
    catalogLoading,
    catalogError,
    t: (key: string) => {
      void runtimeRevision;
      return t(key, selectedLocale);
    },
  };
}
