import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  ensureLocaleCatalog,
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

function primeCriticalLocale(locale: string) {
  primeLocaleCatalogFromCache(locale, "critical");
}

function primeKnownLocale(locale: string) {
  primeCriticalLocale(locale);
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
      setCatalogLoading(!hasCriticalLocaleCatalog(selectedLocale));
      try {
        if (!hasCriticalLocaleCatalog(selectedLocale)) {
          await ensureLocaleCatalog(selectedLocale, "critical");
        }
        if (cancelled) return;
        notifyLocaleRuntime();
        setCatalogLoading(false);

        void (async () => {
          if (!hasCoreLocaleCatalog(selectedLocale)) {
            await ensureLocaleCatalog(selectedLocale, "core");
          }
          if (cancelled) return;
          notifyLocaleRuntime();
          await ensureLocaleCatalog(selectedLocale, "full");
          if (!cancelled) notifyLocaleRuntime();
        })().catch((cause) => {
          console.warn(FULL_UI_TRANSLATION_DIAGNOSTIC, {
            locale: selectedLocale,
            error: cause instanceof Error ? cause.message : String(cause),
          });
        });
      } catch (cause) {
        if (!cancelled) {
          setCatalogError(cause instanceof Error ? cause.message : "UI translation unavailable");
          setCatalogLoading(false);
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
    if (explicitLocaleActivated && canonical !== current) {
      primeCriticalLocale(current);
      setSelectedLocaleState(current);
      notifyLocaleRuntime();
      return current;
    }
    primeCriticalLocale(canonical);
    const activated = setStoredLocale(canonical);
    setSelectedLocaleState(activated);
    notifyLocaleRuntime();
    return activated;
  };

  const activateLocale = (nextLocale: string) => {
    explicitLocaleActivated = true;
    const canonical = canonicalizeSelectedLocale(nextLocale);
    primeCriticalLocale(canonical);
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
