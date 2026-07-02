import { useEffect, useState } from "react";
import { Globe2 } from "lucide-react";
import { applyLocale, getStoredLocale, LOCALES, setStoredLocale, t } from "../i18n";

export function LanguageSelector({ compact = false, dark = false }: { compact?: boolean; dark?: boolean }) {
  const [locale, setLocale] = useState(getStoredLocale());

  useEffect(() => {
    applyLocale(locale);
    const listener = ((event: CustomEvent) => setLocale(event.detail?.locale || getStoredLocale())) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, [locale]);

  const labelColor = dark ? "rgba(255,255,255,0.58)" : "#65736A";
  const selectBg = dark ? "rgba(255,255,255,0.06)" : "#FFFDF8";
  const selectColor = dark ? "white" : "#10231B";
  const border = dark ? "rgba(255,255,255,0.10)" : "#D6DDD0";

  return (
    <label className={`flex ${compact ? "items-center gap-2" : "flex-col gap-1"}`} style={{ color: labelColor }}>
      <span className="inline-flex items-center gap-1 text-[11px] font-medium">
        <Globe2 className="h-3.5 w-3.5" /> {compact ? "" : t("language", locale)}
      </span>
      <select
        value={locale}
        onChange={(event) => {
          setLocale(event.target.value);
          setStoredLocale(event.target.value);
        }}
        className="h-8 rounded-md px-2 text-[12px] outline-none"
        style={{ background: selectBg, color: selectColor, border: `1px solid ${border}` }}
        title="Language"
      >
        {LOCALES.map((item) => (
          <option key={item.code} value={item.code}>{item.nativeName} · {item.englishName}</option>
        ))}
      </select>
    </label>
  );
}
