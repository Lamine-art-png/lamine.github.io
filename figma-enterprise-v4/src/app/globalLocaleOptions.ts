import manifestData from "../../../shared/supported-locales.json";

export type GlobalLocaleOption = {
  code: string;
  languageCode: string;
  nativeName: string;
  englishName: string;
  dir: "ltr" | "rtl";
};

type RawLocale = {
  code: string;
  languageCode: string;
  nativeName?: string;
  englishName?: string;
  direction?: "ltr" | "rtl";
};

type LocaleManifest = {
  enabledUiLocales: string[];
  locales: RawLocale[];
};

const manifest = manifestData as LocaleManifest;
const enabled = new Set((manifest.enabledUiLocales || []).map((code) => code.toLowerCase()));

export const GLOBAL_UI_LOCALES: GlobalLocaleOption[] = (manifest.locales || [])
  .filter((locale) => enabled.has(locale.code.toLowerCase()))
  .map((locale) => ({
    code: locale.code,
    languageCode: locale.languageCode,
    nativeName: locale.nativeName || locale.code,
    englishName: locale.englishName || locale.nativeName || locale.code,
    dir: locale.direction || "ltr",
  }));

export const GLOBAL_UI_LOCALE_COUNT = GLOBAL_UI_LOCALES.length;
