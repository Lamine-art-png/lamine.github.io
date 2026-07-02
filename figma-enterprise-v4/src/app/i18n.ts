export type LocaleOption = { code: string; nativeName: string; englishName: string; flag: string; dir?: "ltr" | "rtl" };

export const LANGUAGE_STORAGE_KEY = "agroai_locale_v1";
export const DEFAULT_LOCALE = "en";

export const LOCALES: LocaleOption[] = [
  { code: "auto", nativeName: "Auto", englishName: "Browser default", flag: "🌐" },
  { code: "en", nativeName: "English", englishName: "English", flag: "🇺🇸" },
  { code: "fr", nativeName: "Français", englishName: "French", flag: "🇫🇷" },
  { code: "es", nativeName: "Español", englishName: "Spanish", flag: "🇪🇸" },
  { code: "pt", nativeName: "Português", englishName: "Portuguese", flag: "🇧🇷" },
  { code: "ar", nativeName: "العربية", englishName: "Arabic", flag: "🇸🇦", dir: "rtl" },
  { code: "zh", nativeName: "中文", englishName: "Chinese", flag: "🇨🇳" },
  { code: "hi", nativeName: "हिन्दी", englishName: "Hindi", flag: "🇮🇳" },
  { code: "bn", nativeName: "বাংলা", englishName: "Bengali", flag: "🇧🇩" },
  { code: "ru", nativeName: "Русский", englishName: "Russian", flag: "🇷🇺" },
  { code: "ja", nativeName: "日本語", englishName: "Japanese", flag: "🇯🇵" },
  { code: "ko", nativeName: "한국어", englishName: "Korean", flag: "🇰🇷" },
  { code: "de", nativeName: "Deutsch", englishName: "German", flag: "🇩🇪" },
  { code: "it", nativeName: "Italiano", englishName: "Italian", flag: "🇮🇹" },
  { code: "tr", nativeName: "Türkçe", englishName: "Turkish", flag: "🇹🇷" },
  { code: "id", nativeName: "Bahasa Indonesia", englishName: "Indonesian", flag: "🇮🇩" },
  { code: "sw", nativeName: "Kiswahili", englishName: "Swahili", flag: "🇰🇪" },
  { code: "wo", nativeName: "Wolof", englishName: "Wolof", flag: "🇸🇳" },
  { code: "ff", nativeName: "Fulfulde", englishName: "Fula", flag: "🇸🇳" },
  { code: "ha", nativeName: "Hausa", englishName: "Hausa", flag: "🇳🇬" },
  { code: "yo", nativeName: "Yorùbá", englishName: "Yoruba", flag: "🇳🇬" },
  { code: "ig", nativeName: "Igbo", englishName: "Igbo", flag: "🇳🇬" },
  { code: "am", nativeName: "አማርኛ", englishName: "Amharic", flag: "🇪🇹" },
  { code: "fa", nativeName: "فارسی", englishName: "Persian", flag: "🇮🇷", dir: "rtl" },
  { code: "ur", nativeName: "اردو", englishName: "Urdu", flag: "🇵🇰", dir: "rtl" },
  { code: "vi", nativeName: "Tiếng Việt", englishName: "Vietnamese", flag: "🇻🇳" },
  { code: "th", nativeName: "ไทย", englishName: "Thai", flag: "🇹🇭" },
  { code: "pl", nativeName: "Polski", englishName: "Polish", flag: "🇵🇱" },
  { code: "nl", nativeName: "Nederlands", englishName: "Dutch", flag: "🇳🇱" },
  { code: "uk", nativeName: "Українська", englishName: "Ukrainian", flag: "🇺🇦" },
  { code: "ro", nativeName: "Română", englishName: "Romanian", flag: "🇷🇴" },
  { code: "el", nativeName: "Ελληνικά", englishName: "Greek", flag: "🇬🇷" },
  { code: "he", nativeName: "עברית", englishName: "Hebrew", flag: "🇮🇱", dir: "rtl" },
];

export function normalizeLocale(value?: string | null): string {
  const raw = String(value || "").trim();
  if (!raw) return DEFAULT_LOCALE;
  if (raw === "auto") return navigator.language || DEFAULT_LOCALE;
  return raw;
}

export function getStoredLocale(): string {
  try {
    return localStorage.getItem(LANGUAGE_STORAGE_KEY) || "auto";
  } catch {
    return "auto";
  }
}

export function setStoredLocale(locale: string) {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, locale || "auto");
  } catch {
    // Best effort.
  }
  applyLocale(locale);
  window.dispatchEvent(new CustomEvent("agroai:locale-change", { detail: { locale } }));
}

export function isRtlLocale(locale: string) {
  const normalized = normalizeLocale(locale).split("-")[0];
  return ["ar", "fa", "ur", "he", "ps", "sd", "ku", "yi"].includes(normalized);
}

export function applyLocale(locale = getStoredLocale()) {
  const normalized = normalizeLocale(locale);
  document.documentElement.lang = normalized;
  document.documentElement.dir = isRtlLocale(normalized) ? "rtl" : "ltr";
}

export function currentLocale() {
  return normalizeLocale(getStoredLocale());
}

export const TRANSLATIONS: Record<string, Record<string, string>> = {
  en: { language: "Language", newOperation: "New operation", fieldOperatingRoom: "Field operating room", workspace: "Workspace", operate: "Operate", intelligence: "Intelligence", account: "Account", billing: "Billing", pricingTitle: "Choose the operating layer for your farm intelligence.", pricingSubtitle: "Start with a workspace, then scale into reports, controller readiness, field operations, compliance, and network reporting." },
  fr: { language: "Langue", newOperation: "Nouvelle opération", fieldOperatingRoom: "Salle d’opérations terrain", workspace: "Espace de travail", operate: "Opérations", intelligence: "Intelligence", account: "Compte", billing: "Facturation", pricingTitle: "Choisissez la couche opérationnelle pour votre intelligence agricole.", pricingSubtitle: "Commencez par un espace de travail, puis développez les rapports, la préparation des contrôleurs, les opérations terrain, la conformité et le reporting réseau." },
  es: { language: "Idioma", newOperation: "Nueva operación", fieldOperatingRoom: "Sala de operaciones de campo", workspace: "Espacio de trabajo", operate: "Operar", intelligence: "Inteligencia", account: "Cuenta", billing: "Facturación", pricingTitle: "Elige la capa operativa para la inteligencia de tu campo.", pricingSubtitle: "Empieza con un espacio de trabajo y escala hacia informes, controladores, operaciones de campo, cumplimiento y reportes de red." },
  ar: { language: "اللغة", newOperation: "عملية جديدة", fieldOperatingRoom: "غرفة عمليات الحقل", workspace: "مساحة العمل", operate: "التشغيل", intelligence: "الذكاء", account: "الحساب", billing: "الفوترة", pricingTitle: "اختر طبقة التشغيل لذكاء مزرعتك.", pricingSubtitle: "ابدأ بمساحة عمل ثم توسع إلى التقارير، جاهزية وحدات التحكم، عمليات الحقل، الامتثال، وتقارير الشبكة." },
};

export function t(key: string, locale = currentLocale()): string {
  const root = normalizeLocale(locale).split("-")[0];
  return TRANSLATIONS[root]?.[key] || TRANSLATIONS.en[key] || key;
}
