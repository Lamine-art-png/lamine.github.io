import { useEffect, useMemo, useState } from "react";
import { applyLocale, getStoredLocale, normalizeLocale, resolveLocaleDetailed, setStoredLocale, t } from "../i18n";

export function useLocale() {
  const [selectedLocale, setSelectedLocaleState] = useState(getStoredLocale());

  useEffect(() => {
    applyLocale(selectedLocale);
    const listener = ((event: CustomEvent) => {
      setSelectedLocaleState(event.detail?.selectedLocale || event.detail?.locale || getStoredLocale());
    }) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, [selectedLocale]);

  const effectiveLocale = useMemo(() => normalizeLocale(selectedLocale), [selectedLocale]);
  const resolution = useMemo(() => resolveLocaleDetailed(selectedLocale), [selectedLocale]);

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
    t: (key: string) => t(key, selectedLocale),
  };
}
