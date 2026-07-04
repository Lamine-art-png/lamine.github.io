import manifestData from "../../../shared/supported-locales.json";

export type LocaleDirection = "ltr" | "rtl";
export type LocaleOption = {
  code: string;
  languageCode: string;
  nativeName: string;
  englishName: string;
  dir?: LocaleDirection;
  fallbackChain: string[];
};
export type LocaleResolution = {
  requestedLocale: string;
  selectedLocale: string;
  effectiveLocale: string;
  fallbackReason: "exact" | "auto" | "regional_fallback" | "language_fallback" | "unsupported_fallback" | "legacy_unsupported";
  fallbackChain: string[];
};

type RawLocale = { code: string; languageCode: string; direction?: LocaleDirection; fallbackChain?: string[] };
type LocaleManifest = {
  defaultLocale: string;
  storageKey?: string;
  enabledUiLocales: string[];
  catalogCompleteLocales?: string[];
  locales: RawLocale[];
  unsupportedLegacyLocales?: string[];
};

const MANIFEST = manifestData as LocaleManifest;

export const LANGUAGE_STORAGE_KEY = MANIFEST.storageKey || "agroai_locale_v1";
export const DEFAULT_LOCALE = MANIFEST.defaultLocale || "en";

const LABELS: Record<string, { nativeName: string; englishName: string }> = {
  auto: { nativeName: "Auto", englishName: "Browser default" },
  en: { nativeName: "English", englishName: "English" },
  "fr-FR": { nativeName: "Français (France)", englishName: "French (France)" },
};

const enabledCodes = new Set((MANIFEST.enabledUiLocales || []).map((code) => code.toLowerCase()));
const unsupportedLegacy = new Set((MANIFEST.unsupportedLegacyLocales || []).map((code) => code.toLowerCase()));
const rawLocaleByCode = new Map((MANIFEST.locales || []).map((locale) => [locale.code.toLowerCase(), locale]));

export const LOCALES: LocaleOption[] = (MANIFEST.locales || [])
  .filter((locale) => enabledCodes.has(locale.code.toLowerCase()))
  .map((locale) => ({
    code: locale.code,
    languageCode: locale.languageCode,
    nativeName: LABELS[locale.code]?.nativeName || locale.code,
    englishName: LABELS[locale.code]?.englishName || locale.code,
    dir: locale.direction,
    fallbackChain: locale.fallbackChain || [],
  }));
export const ENABLED_LOCALES = LOCALES;
const ENABLED_BY_CODE = new Map(ENABLED_LOCALES.map((locale) => [locale.code.toLowerCase(), locale]));

const en: Record<string, string> = {
  "app.loadingSession": "Loading session",
  "app.loadingPortal": "Loading portal",
  "app.recoveryEyebrow": "AGRO-AI Enterprise Portal",
  "app.recoveryTitle": "Portal recovery mode",
  "app.recoveryBody": "The portal booted safely, but one workspace route failed to load. This screen prevents a white page while the route is repaired.",
  "app.reloadPortal": "Reload portal",
  "app.clearSession": "Clear session and sign in again",
  language: "Language", save: "Save", saved: "Saved", saving: "Saving...", send: "Send", sending: "Sending...",
  retry: "Retry", remove: "Remove", ready: "Ready", done: "Done", working: "Working...",
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
  subscriptionBilling: "Subscription and billing", accountProfile: "Account profile", workspacePreferences: "Workspace preferences",
  notifications: "Notifications", integrationsControllers: "Integrations and controllers", pricingTitle: "Plans for serious field operations",
  pricingSubtitle: "Start with a focused operating layer, then scale into team, network, and enterprise workflows as your evidence graph grows.", upgrade: "Upgrade",
  "intelligence.title": "Ask AGRO-AI", "intelligence.newChat": "New chat", "intelligence.history": "History", "intelligence.search": "Search chats",
  "intelligence.closeSidebar": "Close sidebar", "intelligence.deleteChat": "Delete chat", "intelligence.workspaceBadge": "Workspace intelligence",
  "intelligence.subtitle": "Ask, import files, generate reports, create field tasks, record field updates, and prepare approval-gated operations.",
  "intelligence.placeholder": "Ask AGRO-AI or import files", "intelligence.importFiles": "Import files", "intelligence.loadingChats": "Loading chats...",
  "intelligence.noChats": "No saved chats yet.", "intelligence.enterHint": "Enter to send. Shift + Enter for a new line.",
  "intelligence.emptyTitle": "What should we work through?", "intelligence.emptyBody": "Start with a field, report, compliance requirement, customer account, irrigation decision, evidence gap, or messy dataset.",
  "intelligence.unavailable": "AGRO-AI could not complete the request.", "intelligence.retryState": "AGRO-AI could not complete this response. Retry.",
  "intelligence.languageGenerationFailed": "AGRO-AI produced the answer in the wrong language and could not safely repair it. Your message is preserved. Retry.",
  "intelligence.startThread": "Start a workspace thread", "intelligence.askOrImport": "Ask a question or import files.",
  "intelligence.liveEvidenceBody": "AGRO-AI uses live model inference, conversation history, and available workspace evidence to answer the question you actually asked.",
  "intelligence.prompt.data": "What should I do with my data?", "intelligence.prompt.checklist": "Create an operator checklist.",
  "intelligence.prompt.missingEvidence": "What evidence is missing?", "intelligence.prompt.report": "Generate a customer-ready report.",
  "intelligence.preparingAnswer": "Preparing the answer...", "intelligence.preparingPdf": "Preparing PDF...", "intelligence.downloadPdf": "Download PDF",
  "intelligence.emailToMe": "Email to me", "intelligence.emailing": "Sending...", "intelligence.summarizeImportedFiles": "Summarize the files I imported.",
  "intelligence.importFailed": "Import failed", "intelligence.fileQueued": "Queued", "intelligence.fileUploading": "Uploading...", "intelligence.fileImported": "Imported",
  "intelligence.fileFailed": "Failed", "intelligence.fileFailedBeforeSend": "One file failed to import. Remove it before sending.",
  "intelligence.reportEmailed": "Report emailed to {recipient}.", "intelligence.accountEmail": "your account email",
  "intelligence.pdfExportFailed": "AGRO-AI could not export the PDF report.", "intelligence.pdfEmailFailed": "AGRO-AI could not email the PDF report.",
  "intelligence.actionCompleted": "Action completed: {title}", "intelligence.actionExecuteFailed": "AGRO-AI could not execute this action.",
  "intelligence.approvalRequired": "Approval required", "intelligence.riskReady": "Ready", "intelligence.riskLabel": "{level} risk",
  "intelligence.createApproval": "Create approval", "intelligence.doIt": "Do it",
};

const frFR: Record<string, string> = {
  "app.loadingSession": "Chargement de la session",
  "app.loadingPortal": "Chargement du portail",
  "app.recoveryEyebrow": "Portail Entreprise AGRO-AI",
  "app.recoveryTitle": "Mode de récupération du portail",
  "app.recoveryBody": "Le portail a démarré en sécurité, mais un module de l’espace de travail n’a pas pu se charger. Cet écran évite une page blanche pendant la réparation du module.",
  "app.reloadPortal": "Recharger le portail",
  "app.clearSession": "Effacer la session et se reconnecter",
  language: "Langue", save: "Enregistrer", saved: "Enregistré", saving: "Enregistrement...", send: "Envoyer", sending: "Envoi...",
  retry: "Réessayer", remove: "Retirer", ready: "Prêt", done: "Terminé", working: "Traitement...",
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
  subscriptionBilling: "Abonnement et facturation", accountProfile: "Profil du compte", workspacePreferences: "Préférences de l’espace de travail",
  notifications: "Notifications", integrationsControllers: "Intégrations et contrôleurs", pricingTitle: "Forfaits pour des opérations terrain exigeantes",
  pricingSubtitle: "Commencez par un niveau opérationnel ciblé, puis étendez-vous aux flux d’équipe, de réseau et d’entreprise à mesure que votre graphe de preuves s’enrichit.", upgrade: "Mettre à niveau",
  "intelligence.title": "Interroger AGRO-AI", "intelligence.newChat": "Nouvelle conversation", "intelligence.history": "Historique", "intelligence.search": "Rechercher des conversations",
  "intelligence.closeSidebar": "Fermer la barre latérale", "intelligence.deleteChat": "Supprimer la conversation", "intelligence.workspaceBadge": "Intelligence de l’espace de travail",
  "intelligence.subtitle": "Interrogez AGRO-AI, importez des fichiers, générez des rapports, créez des tâches terrain, consignez les mises à jour et préparez les opérations soumises à approbation.",
  "intelligence.placeholder": "Interroger AGRO-AI ou importer des fichiers", "intelligence.importFiles": "Importer des fichiers", "intelligence.loadingChats": "Chargement des conversations...",
  "intelligence.noChats": "Aucune conversation enregistrée.", "intelligence.enterHint": "Entrée pour envoyer. Maj + Entrée pour une nouvelle ligne.",
  "intelligence.emptyTitle": "Sur quel sujet devons-nous travailler ?", "intelligence.emptyBody": "Commencez par un champ, un rapport, une exigence de conformité, un compte client, une décision d’irrigation, une preuve manquante ou un jeu de données difficile à exploiter.",
  "intelligence.unavailable": "AGRO-AI n’a pas pu compléter la demande.", "intelligence.retryState": "AGRO-AI n’a pas pu générer cette réponse. Réessayez.",
  "intelligence.languageGenerationFailed": "AGRO-AI a produit la réponse dans la mauvaise langue et n’a pas pu la corriger de manière sûre. Votre message est conservé. Réessayez.",
  "intelligence.startThread": "Démarrer une conversation dans l’espace de travail", "intelligence.askOrImport": "Posez une question ou importez des fichiers.",
  "intelligence.liveEvidenceBody": "AGRO-AI utilise l’inférence du modèle en direct, l’historique de la conversation et les éléments disponibles dans l’espace de travail pour répondre précisément à la question posée.",
  "intelligence.prompt.data": "Que dois-je faire avec mes données ?", "intelligence.prompt.checklist": "Créer une liste de contrôle pour l’opérateur.",
  "intelligence.prompt.missingEvidence": "Quelles preuves manquent ?", "intelligence.prompt.report": "Générer un rapport prêt à être présenté au client.",
  "intelligence.preparingAnswer": "Préparation de la réponse...", "intelligence.preparingPdf": "Préparation du PDF...", "intelligence.downloadPdf": "Télécharger le PDF",
  "intelligence.emailToMe": "Me l’envoyer par e-mail", "intelligence.emailing": "Envoi...", "intelligence.summarizeImportedFiles": "Résume les fichiers que j’ai importés.",
  "intelligence.importFailed": "Échec de l’import", "intelligence.fileQueued": "En attente", "intelligence.fileUploading": "Importation...", "intelligence.fileImported": "Importé",
  "intelligence.fileFailed": "Échec", "intelligence.fileFailedBeforeSend": "Un fichier n’a pas pu être importé. Retirez-le avant l’envoi.",
  "intelligence.reportEmailed": "Rapport envoyé à {recipient}.", "intelligence.accountEmail": "l’adresse e-mail de votre compte",
  "intelligence.pdfExportFailed": "AGRO-AI n’a pas pu exporter le rapport PDF.", "intelligence.pdfEmailFailed": "AGRO-AI n’a pas pu envoyer le rapport PDF par e-mail.",
  "intelligence.actionCompleted": "Action terminée : {title}", "intelligence.actionExecuteFailed": "AGRO-AI n’a pas pu exécuter cette action.",
  "intelligence.approvalRequired": "Approbation requise", "intelligence.riskReady": "Prêt", "intelligence.riskLabel": "Risque {level}",
  "intelligence.createApproval": "Créer une demande d’approbation", "intelligence.doIt": "Exécuter",
};

export const TRANSLATIONS: Record<string, Record<string, string>> = { en, "fr-FR": frFR };

const EN_KEYS = Object.keys(en).sort();
const FR_KEYS = Object.keys(frFR).sort();
if (EN_KEYS.length !== FR_KEYS.length || EN_KEYS.some((key, index) => key !== FR_KEYS[index])) {
  throw new Error("Enabled French catalog must have exact key parity with English.");
}

function cleanLocale(value?: string | null): string {
  return String(value || "auto").trim().replace("_", "-") || "auto";
}

function browserLanguage(): string {
  return typeof navigator === "undefined" ? DEFAULT_LOCALE : navigator.language || DEFAULT_LOCALE;
}

function enabledForLanguage(languageCode: string | undefined): LocaleOption | undefined {
  if (!languageCode || languageCode.toLowerCase() === "auto") return undefined;
  return ENABLED_LOCALES.find((locale) => locale.languageCode.toLowerCase() === languageCode.toLowerCase());
}

export function canonicalizeSelectedLocale(value?: string | null): string {
  const requested = cleanLocale(value);
  const lower = requested.toLowerCase();
  if (lower === "auto") return "auto";
  const exact = ENABLED_BY_CODE.get(lower);
  if (exact) return exact.code;
  if (unsupportedLegacy.has(lower)) return "auto";

  const known = rawLocaleByCode.get(lower);
  const fallbackChain = known?.fallbackChain || [];
  for (const fallback of fallbackChain) {
    const exactFallback = ENABLED_BY_CODE.get(fallback.toLowerCase());
    if (exactFallback) return exactFallback.code;
    const fallbackMeta = rawLocaleByCode.get(fallback.toLowerCase());
    const languageFallback = enabledForLanguage(fallbackMeta?.languageCode || fallback);
    if (languageFallback) return languageFallback.code;
  }

  const languageRoot = known?.languageCode || requested.split("-")[0];
  const languageMatch = enabledForLanguage(languageRoot);
  return languageMatch?.code || "auto";
}

export function resolveLocaleDetailed(value?: string | null): LocaleResolution {
  const requestedLocale = cleanLocale(value);
  const selectedLocale = canonicalizeSelectedLocale(requestedLocale);
  if (selectedLocale === "auto") {
    const browserSelected = canonicalizeSelectedLocale(browserLanguage());
    const effectiveLocale = browserSelected === "auto" ? DEFAULT_LOCALE : browserSelected;
    const reason = requestedLocale.toLowerCase() === "auto" ? "auto" : unsupportedLegacy.has(requestedLocale.toLowerCase()) ? "legacy_unsupported" : "unsupported_fallback";
    return { requestedLocale, selectedLocale, effectiveLocale, fallbackReason: reason, fallbackChain: ["auto", DEFAULT_LOCALE] };
  }
  const reason = selectedLocale.toLowerCase() === requestedLocale.toLowerCase() ? "exact" : "regional_fallback";
  return { requestedLocale, selectedLocale, effectiveLocale: selectedLocale, fallbackReason: reason, fallbackChain: selectedLocale === requestedLocale ? [] : [selectedLocale] };
}

export function normalizeLocale(value?: string | null): string {
  return resolveLocaleDetailed(value).effectiveLocale;
}

export function getStoredLocale(): string {
  try {
    const raw = localStorage.getItem(LANGUAGE_STORAGE_KEY) || "auto";
    const canonical = canonicalizeSelectedLocale(raw);
    if (canonical !== raw) localStorage.setItem(LANGUAGE_STORAGE_KEY, canonical);
    return canonical;
  } catch {
    return "auto";
  }
}

export function currentLocale() {
  return normalizeLocale(getStoredLocale());
}

export function isRtlLocale(locale: string) {
  const normalized = normalizeLocale(locale);
  const option = ENABLED_BY_CODE.get(normalized.toLowerCase());
  return option?.dir === "rtl" || ["ar", "fa", "ur"].includes(normalized.split("-")[0]);
}

export function t(key: string, locale = getStoredLocale()): string {
  const normalized = normalizeLocale(locale);
  const catalog = TRANSLATIONS[normalized] || TRANSLATIONS.en;
  const value = catalog[key];
  if (value !== undefined) return value;
  if (normalized !== "en" && import.meta.env?.DEV) console.error(`[i18n] Missing ${key} for ${normalized}`);
  return TRANSLATIONS.en[key] || key;
}

export function formatTranslation(template: string, values: Record<string, string | number | undefined>) {
  return template.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ""));
}

export function applyLocale(locale = getStoredLocale()) {
  if (typeof document === "undefined") return;
  const normalized = normalizeLocale(locale);
  document.documentElement.lang = normalized;
  document.documentElement.dir = isRtlLocale(normalized) ? "rtl" : "ltr";
}

export function setStoredLocale(locale: string): string {
  const selectedLocale = canonicalizeSelectedLocale(locale);
  try {
    localStorage.removeItem("agroai_locale");
    localStorage.setItem(LANGUAGE_STORAGE_KEY, selectedLocale);
  } catch {
    // Best effort.
  }
  applyLocale(selectedLocale);
  window.dispatchEvent(new CustomEvent("agroai:locale-change", { detail: { selectedLocale, locale: selectedLocale, effectiveLocale: normalizeLocale(selectedLocale) } }));
  return selectedLocale;
}

applyLocale();
