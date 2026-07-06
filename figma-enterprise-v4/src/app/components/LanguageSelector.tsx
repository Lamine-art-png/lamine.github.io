import { useState } from "react";
import { ChevronDown, Globe2 } from "lucide-react";
import { apiClient } from "../api/client";
import { GLOBAL_UI_LOCALES } from "../globalLocaleOptions";
import { useLocale } from "../hooks/useLocale";

export function LanguageSelector({ compact = false, dark = false }: { compact?: boolean; dark?: boolean }) {
  const { selectedLocale, activateLocale, t, catalogLoading, catalogError } = useLocale();
  const [pendingLocale, setPendingLocale] = useState<string | null>(null);

  async function changeLanguage(nextLocale: string) {
    setPendingLocale(nextLocale);
    try {
      const canonical = await activateLocale(nextLocale);
      try {
        await apiClient.patch("/v1/settings/preferences", { locale: canonical });
      } catch {
        // Preference sync is best effort. The activated local switch remains authoritative for this session.
      }
    } finally {
      setPendingLocale(null);
    }
  }

  const labelColor = dark ? "rgba(255,255,255,0.58)" : "#65736A";
  const selectBg = dark ? "rgba(255,255,255,0.06)" : "#FFFDF8";
  const selectColor = dark ? "white" : "#10231B";
  const border = dark ? "rgba(255,255,255,0.10)" : "#D6DDD0";
  const busy = Boolean(pendingLocale) || catalogLoading;

  return (
    <label className={`flex ${compact ? "items-center gap-2" : "flex-col gap-1"}`} style={{ color: labelColor }}>
      {!compact ? (
        <span className="inline-flex items-center gap-1 text-[11px] font-medium">
          <Globe2 className="h-3.5 w-3.5" /> {t("language")}
          {busy ? <span aria-hidden="true"> · …</span> : null}
        </span>
      ) : null}
      <span className="relative inline-flex w-full items-center">
        {compact ? <Globe2 className="pointer-events-none absolute left-2 h-3.5 w-3.5" style={{ color: labelColor }} /> : null}
        <select
          value={pendingLocale || selectedLocale}
          onChange={(event) => void changeLanguage(event.target.value)}
          disabled={Boolean(pendingLocale)}
          className={`h-9 w-full appearance-none rounded-md py-1 pr-8 text-[12px] outline-none ${compact ? "pl-8" : "pl-3"}`}
          style={{ background: selectBg, color: selectColor, border: `1px solid ${catalogError ? "#B42318" : border}`, opacity: pendingLocale ? 0.78 : 1 }}
          title={catalogError || t("language")}
          aria-label={t("language")}
          aria-busy={busy}
        >
          {GLOBAL_UI_LOCALES.map((item) => (
            <option key={item.code} value={item.code} dir={item.dir}>
              {item.nativeName} · {item.englishName}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5" style={{ color: labelColor }} />
      </span>
    </label>
  );
}
