import { useEffect, useMemo, useState } from "react";
import { ensureLocaleCatalog } from "../dynamicLocaleCatalog";
import { applyLocale, getStoredLocale, normalizeLocale, resolveLocaleDetailed, setStoredLocale, t } from "../i18n";

export function useLocale() {
  const [selectedLocale, setSelectedLocaleState] = useState(getStoredLocale());
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
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
      .then((changed) => {
        if (!cancelled && changed) setCatalogRevision((value) => value + 1);
      })
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
    return canonical;
  };

  return {
    selectedLocale,
    effectiveLocale,
    locale: selectedLocale,
    normalizedLocale: effectiveLocale,
    resolution,
    setLocale,
    catalogLoading,
    catalogError,
    t: (key: string) => {
      void catalogRevision;
      return t(key, selectedLocale);
    },
  };
}
