import { useEffect, useState } from "react";
import { ChevronDown, Globe2 } from "lucide-react";
import { apiClient } from "../api/client";
import { applyLocale, ENABLED_LOCALES, getStoredLocale, setStoredLocale, t } from "../i18n";

export function LanguageSelector({ compact = false, dark = false }: { compact?: boolean; dark?: boolean }) {
  const [locale, setLocale] = useState(getStoredLocale());

  useEffect(() => {
    applyLocale(locale);
    const listener = ((event: CustomEvent) => setLocale(event.detail?.selectedLocale || event.detail?.locale || getStoredLocale())) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, [locale]);

  async function changeLanguage(nextLocale: string) {
    const canonical = setStoredLocale(nextLocale);
    setLocale(canonical);
    try {
      await apiClient.patch("/v1/settings/preferences", { locale: canonical });
    } catch {
      // Preference sync is best effort. The local switch remains active.
    }
  }

  const labelColor = dark ? "rgba(255,255,255,0.58)" : "#65736A";
  const selectBg = dark ? "rgba(255,255,255,0.06)" : "#FFFDF8";
  const selectColor = dark ? "white" : "#10231B";
  const border = dark ? "rgba(255,255,255,0.10)" : "#D6DDD0";

  return (
    <label className={`flex ${compact ? "items-center gap-2" : "flex-col gap-1"}`} style={{ color: labelColor }}>
      {!compact ? <span className="inline-flex items-center gap-1 text-[11px] font-medium"><Globe2 className="h-3.5 w-3.5" /> {t("language", locale)}</span> : null}
      <span className="relative inline-flex w-full items-center">
        {compact ? <Globe2 className="pointer-events-none absolute left-2 h-3.5 w-3.5" style={{ color: labelColor }} /> : null}
        <select
          value={locale}
          onChange={(event) => changeLanguage(event.target.value)}
          className={`h-9 w-full appearance-none rounded-md py-1 pr-8 text-[12px] outline-none ${compact ? "pl-8" : "pl-3"}`}
          style={{ background: selectBg, color: selectColor, border: `1px solid ${border}` }}
          title={t("language", locale)}
        >
          {ENABLED_LOCALES.map((item) => <option key={item.code} value={item.code}>{item.nativeName} · {item.englishName}</option>)}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5" style={{ color: labelColor }} />
      </span>
    </label>
  );
}
