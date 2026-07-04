import { useEffect, useMemo, useState } from "react";

export type LocaleOption = { code: string; nativeName: string; englishName: string; dir?: "ltr" | "rtl" };
export type LocaleResolution = { requestedLocale: string; resolvedLocale: string; fallbackReason: string; fallbackChain: string[] };

export const LANGUAGE_STORAGE_KEY = "agroai_locale_v1";
export const DEFAULT_LOCALE = "en";

export const LOCALES: LocaleOption[] = [
  { code: "auto", nativeName: "Auto", englishName: "Browser default" },
  { code: "en", nativeName: "English", englishName: "English" },
  { code: "fr-FR", nativeName: "Français (France)", englishName: "French (France)" },
];
export const ENABLED_LOCALES = LOCALES;

const LEGACY_UNSUPPORTED = new Set(["aa", "ase", "ff", "ha", "ig", "wo", "yo"]);
const FALLBACKS: Record<string, string[]> = {
  fr: ["fr-FR", "en"],
  "fr-fr": ["fr-FR", "en"],
  "fr-ca": ["fr-FR", "en"],
};

const en: Record<string, string> = {
  language: "Language", save: "Save", saved: "Saved", saving: "Saving...", send: "Send", sending: "Sending...",
  newOperation: "New operation", fieldOperatingRoom: "Field operating room", workspace: "Workspace", operate: "Operate",
  intelligence: "Intelligence", account: "Account", commandCenter: "Command Center", fieldQueue: "Field Queue",
  tasks: "Tasks", decisions: "Decisions", evidence: "Evidence", reports: "Reports", connectors: "Connectors",
  askAgroAi: "Ask AGRO-AI", readiness: "Readiness", exceptions: "Exceptions", sources: "Sources", team: "Team",
  settings: "Settings", profile: "Profile", billing: "Billing", security: "Security", support: "Support", requests: "Requests",
  admin: "Admin", systemHealth: "System Health", logout: "Log out", plan: "Plan",
  settingsTitle: "Settings", settingsSubtitle: "Edit language, account, workspace preferences, notification settings, subscription, integrations, and operating safety from one place.",
  languageRegion: "Language and region", languageRegionHint: "Choose the portal language. Ask AGRO-AI also receives this preference when answering.",
  supportTitle: "Support", supportSubtitle: "Create a tracked support ticket for onboarding, integration help, operational support, or report review.",
  contactSupport: "Contact support", requestType: "Request type", subject: "Subject", message: "Message", priority: "Priority", sendRequest: "Send request", requestReceived: "Request received",
  "intelligence.title": "Ask AGRO-AI", "intelligence.newChat": "New chat", "intelligence.history": "History", "intelligence.search": "Search chats",
  "intelligence.placeholder": "Ask AGRO-AI or import files", "intelligence.importFiles": "Import files", "intelligence.loadingChats": "Loading chats...",
  "intelligence.noChats": "No saved chats yet.", "intelligence.enterHint": "Enter to send. Shift + Enter for a new line.",
  "intelligence.emptyTitle": "What should we work through?", "intelligence.emptyBody": "Start with a field, report, compliance requirement, customer account, irrigation decision, evidence gap, or messy dataset.",
  "intelligence.unavailable": "AGRO-AI could not complete the request.", "intelligence.retryState": "AGRO-AI could not complete this response. Retry.",
};

const frFR: Record<string, string> = {
  language: "Langue", save: "Enregistrer", saved: "Enregistré", saving: "Enregistrement...", send: "Envoyer", sending: "Envoi...",
  newOperation: "Nouvelle opération", fieldOperatingRoom: "Salle des opérations terrain", workspace: "Espace de travail", operate: "Opérations",
  intelligence: "Intelligence", account: "Compte", commandCenter: "Centre de pilotage", fieldQueue: "File des opérations terrain",
  tasks: "Tâches", decisions: "Décisions", evidence: "Preuves", reports: "Rapports", connectors: "Connecteurs",
  askAgroAi: "Interroger AGRO-AI", readiness: "État de préparation", exceptions: "Exceptions", sources: "Sources", team: "Équipe",
  settings: "Paramètres", profile: "Profil", billing: "Facturation", security: "Sécurité", support: "Assistance", requests: "Demandes",
  admin: "Administration", systemHealth: "État du système", logout: "Se déconnecter", plan: "Forfait",
  settingsTitle: "Paramètres", settingsSubtitle: "Modifiez la langue, le compte, les préférences de l’espace, les notifications, l’abonnement, les intégrations et la sécurité opérationnelle depuis un seul endroit.",
  languageRegion: "Langue et région", languageRegionHint: "Choisissez la langue du portail. AGRO-AI utilisera aussi cette préférence pour ses réponses.",
  supportTitle: "Assistance", supportSubtitle: "Créez une demande suivie pour l’accompagnement au démarrage, l’aide aux intégrations, l’assistance opérationnelle ou la revue de rapports.",
  contactSupport: "Contacter l’assistance", requestType: "Type de demande", subject: "Objet", message: "Message", priority: "Priorité", sendRequest: "Envoyer la demande", requestReceived: "Demande reçue",
  "intelligence.title": "Interroger AGRO-AI", "intelligence.newChat": "Nouvelle conversation", "intelligence.history": "Historique", "intelligence.search": "Rechercher des conversations",
  "intelligence.placeholder": "Interroger AGRO-AI ou importer des fichiers", "intelligence.importFiles": "Importer des fichiers", "intelligence.loadingChats": "Chargement des conversations...",
  "intelligence.noChats": "Aucune conversation enregistrée.", "intelligence.enterHint": "Entrée pour envoyer. Maj + Entrée pour une nouvelle ligne.",
  "intelligence.emptyTitle": "Sur quel sujet devons-nous travailler ?", "intelligence.emptyBody": "Commencez par un champ, un rapport, une exigence de conformité, un compte client, une décision d’irrigation, une preuve manquante ou un jeu de données difficile à exploiter.",
  "intelligence.unavailable": "AGRO-AI n’a pas pu compléter la demande.", "intelligence.retryState": "AGRO-AI n’a pas pu générer cette réponse. Réessayer.",
};

export const TRANSLATIONS: Record<string, Record<string, string>> = { en, "fr-FR": frFR };

function cleanLocale(value?: string | null): string {
  return String(value || "auto").trim().replace("_", "-") || "auto";
}

function browserLanguage(): string {
  return typeof navigator === "undefined" ? DEFAULT_LOCALE : navigator.language || DEFAULT_LOCALE;
}

export function resolveLocaleDetailed(value?: string | null): LocaleResolution {
  const requestedLocale = cleanLocale(value);
  const lower = requestedLocale.toLowerCase();
  if (lower === "auto") return { requestedLocale: "auto", resolvedLocale: "auto", fallbackReason: "auto", fallbackChain: [DEFAULT_LOCALE] };
  if (LEGACY_UNSUPPORTED.has(lower)) return { requestedLocale, resolvedLocale: "auto", fallbackReason: "legacy_unsupported", fallbackChain: ["auto", DEFAULT_LOCALE] };
  const exact = LOCALES.find((locale) => locale.code.toLowerCase() === lower);
  if (exact) return { requestedLocale, resolvedLocale: exact.code, fallbackReason: "exact", fallbackChain: [] };
  const chain = FALLBACKS[lower] || FALLBACKS[lower.split("-")[0]] || [DEFAULT_LOCALE];
  const resolved = chain.find((code) => LOCALES.some((locale) => locale.code.toLowerCase() === code.toLowerCase()));
  return resolved ? { requestedLocale, resolvedLocale: resolved, fallbackReason: "regional_fallback", fallbackChain: chain } : { requestedLocale, resolvedLocale: "auto", fallbackReason: "unsupported_fallback", fallbackChain: ["auto", DEFAULT_LOCALE] };
}

export function normalizeLocale(value?: string | null): string {
  const resolved = resolveLocaleDetailed(value).resolvedLocale;
  if (resolved === "auto") {
    const browserResolved = resolveLocaleDetailed(browserLanguage()).resolvedLocale;
    return browserResolved === "auto" ? DEFAULT_LOCALE : browserResolved;
  }
  return resolved;
}

export function getStoredLocale(): string {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY) || "auto";
    return resolveLocaleDetailed(stored).fallbackReason === "legacy_unsupported" ? "auto" : stored;
  } catch {
    return "auto";
  }
}

export function currentLocale() {
  return normalizeLocale(getStoredLocale());
}

export function isRtlLocale(locale: string) {
  return ["ar", "fa", "ur"].includes(normalizeLocale(locale).split("-")[0]);
}

export function t(key: string, locale = currentLocale()): string {
  const normalized = normalizeLocale(locale);
  const catalog = TRANSLATIONS[normalized] || TRANSLATIONS.en;
  return catalog[key] || TRANSLATIONS.en[key] || key;
}

export function applyLocale(locale = getStoredLocale()) {
  if (typeof document === "undefined") return;
  const normalized = normalizeLocale(locale);
  document.documentElement.lang = normalized;
  document.documentElement.dir = isRtlLocale(normalized) ? "rtl" : "ltr";
}

export function setStoredLocale(locale: string) {
  const requested = locale || "auto";
  try {
    localStorage.removeItem("agroai_locale");
    localStorage.setItem(LANGUAGE_STORAGE_KEY, requested);
  } catch {
    // Best effort.
  }
  applyLocale(requested);
  window.dispatchEvent(new CustomEvent("agroai:locale-change", { detail: { locale: requested } }));
}

export function useLocale() {
  const [locale, setLocaleState] = useState(getStoredLocale());
  useEffect(() => {
    applyLocale(locale);
    const listener = ((event: CustomEvent) => setLocaleState(event.detail?.locale || getStoredLocale())) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, [locale]);
  const normalizedLocale = useMemo(() => normalizeLocale(locale), [locale]);
  const setLocale = (next: string) => {
    setLocaleState(next);
    setStoredLocale(next);
  };
  return { locale, normalizedLocale, setLocale, t: (key: string) => t(key, locale), resolution: resolveLocaleDetailed(locale) };
}

applyLocale();
