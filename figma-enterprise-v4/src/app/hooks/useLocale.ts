import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { ensureLocaleCatalog } from "../dynamicLocaleCatalog";
import {
  applyLocale,
  canonicalizeSelectedLocale,
  getStoredLocale,
  normalizeLocale,
  resolveLocaleDetailed,
  setStoredLocale,
  t,
} from "../i18n";
import { getLocaleRuntimeSnapshot, notifyLocaleRuntime, subscribeLocaleRuntime } from "../localeRuntimeStore";

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
    applyLocale(selectedLocale);
    const listener = ((event: CustomEvent) => {
      setSelectedLocaleState(event.detail?.selectedLocale || event.detail?.locale || getStoredLocale());
    }) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, [selectedLocale]);

  useEffect(() => {
    let cancelled = false;
    setCatalogError(null);
    setCatalogLoading(true);
    ensureLocaleCatalog(selectedLocale)
      .catch((cause) => {
        if (!cancelled) setCatalogError(cause instanceof Error ? cause.message : "UI translation unavailable");
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedLocale, effectiveLocale]);

  const setLocale = (nextLocale: string) => {
    const canonical = setStoredLocale(nextLocale);
    setSelectedLocaleState(canonical);
    notifyLocaleRuntime();
    return canonical;
  };

  const activateLocale = async (nextLocale: string) => {
    const canonical = canonicalizeSelectedLocale(nextLocale);
    setCatalogError(null);
    setCatalogLoading(true);
    try {
      await ensureLocaleCatalog(canonical);
      const activated = setStoredLocale(canonical);
      setSelectedLocaleState(activated);
      notifyLocaleRuntime();
      return activated;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "UI translation unavailable";
      setCatalogError(message);
      throw cause;
    } finally {
      setCatalogLoading(false);
    }
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
