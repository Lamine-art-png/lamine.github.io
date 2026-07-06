import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { ensureLocaleCatalog, hasCoreLocaleCatalog } from "../dynamicLocaleCatalog";
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

    async function hydrateSelectedLocale() {
      setCatalogError(null);
      if (effectiveLocale === "en") {
        setCatalogLoading(false);
        return;
      }

      setCatalogLoading(true);
      try {
        if (!hasCoreLocaleCatalog(selectedLocale)) {
          await ensureLocaleCatalog(selectedLocale, "core");
        }
        if (cancelled) return;
        notifyLocaleRuntime();
        setCatalogLoading(false);

        void ensureLocaleCatalog(selectedLocale, "full")
          .then(() => {
            if (!cancelled) notifyLocaleRuntime();
          })
          .catch((cause) => {
            if (!cancelled) setCatalogError(cause instanceof Error ? cause.message : "Full UI translation unavailable");
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
    const canonical = setStoredLocale(nextLocale);
    setSelectedLocaleState(canonical);
    notifyLocaleRuntime();
    return canonical;
  };

  const activateLocale = (nextLocale: string) => {
    const canonical = canonicalizeSelectedLocale(nextLocale);
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
