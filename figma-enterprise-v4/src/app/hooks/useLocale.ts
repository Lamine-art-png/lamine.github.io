import { useEffect, useState } from "react";
import { applyLocale, currentLocale, getStoredLocale, setStoredLocale, t } from "../i18n";

export function useLocale() {
  const [locale, setLocaleState] = useState(currentLocale());

  useEffect(() => {
    applyLocale(getStoredLocale());
    const listener = (() => setLocaleState(currentLocale())) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, []);

  const setLocale = (nextLocale: string) => {
    setStoredLocale(nextLocale);
    setLocaleState(currentLocale());
  };

  return {
    locale,
    setLocale,
    t: (key: string) => t(key, locale),
  };
}
