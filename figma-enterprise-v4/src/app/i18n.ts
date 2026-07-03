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
];

export function normalizeLocale(value?: string | null): string {
  const raw = String(value || "").trim();
  if (!raw) return DEFAULT_LOCALE;
  if (raw === "auto") return navigator.language || DEFAULT_LOCALE;
  return raw;
}

export function getStoredLocale(): string {
  try { return localStorage.getItem(LANGUAGE_STORAGE_KEY) || "auto"; } catch { return "auto"; }
}

export function isRtlLocale(locale: string) {
  const normalized = normalizeLocale(locale).split("-")[0];
  return ["ar", "fa", "ur", "he", "ps", "sd", "ku", "yi", "ckb"].includes(normalized);
}

export function currentLocale() {
  return normalizeLocale(getStoredLocale());
}

const en = {
  language: "Language", save: "Save", saved: "Saved", saving: "Saving…", send: "Send", sending: "Sending…", newOperation: "New operation", fieldOperatingRoom: "Field operating room", workspace: "Workspace", operate: "Operate", intelligence: "Intelligence", account: "Account", commandCenter: "Command Center", fieldQueue: "Field Queue", tasks: "Tasks", decisions: "Decisions", evidence: "Evidence", reports: "Reports", connectors: "Connectors", askAgroAi: "Ask AGRO-AI", readiness: "Readiness", exceptions: "Exceptions", sources: "Sources", team: "Team", settings: "Settings", profile: "Profile", billing: "Billing", security: "Security", support: "Support", requests: "Requests", admin: "Admin", systemHealth: "System Health", logout: "Log out", plan: "Plan", pricingTitle: "Choose the operating layer for your farm intelligence.", pricingSubtitle: "Start with a workspace, then scale into reports, controller readiness, field operations, compliance, and network reporting.", settingsTitle: "Settings", settingsSubtitle: "Edit language, account, workspace preferences, notification settings, subscription, integrations, and operating safety from one place.", languageRegion: "Language & region", languageRegionHint: "Choose the portal language. Ask AGRO-AI also receives this preference when answering.", accountProfile: "Account profile", companyRole: "Company & role", workspacePreferences: "Workspace preferences", notifications: "Notifications", subscriptionBilling: "Subscription & billing", integrationsControllers: "Integrations & controllers", supportTitle: "Support", supportSubtitle: "Create a tracked support ticket for onboarding, integration help, operational support, or report review.", contactSupport: "Contact support", requestType: "Request type", subject: "Subject", message: "Message", priority: "Priority", sendRequest: "Send request", requestReceived: "Request received",
};

export const TRANSLATIONS: Record<string, Record<string, string>> = {
  en,
  fr: { ...en, language: "Langue", save: "Enregistrer", saved: "Enregistré", saving: "Enregistrement…", send: "Envoyer", sending: "Envoi…", newOperation: "Nouvelle opération", fieldOperatingRoom: "Salle d’opérations terrain", workspace: "Espace de travail", operate: "Opérations", intelligence: "Intelligence", account: "Compte", commandCenter: "Centre de commandement", fieldQueue: "File terrain", tasks: "Tâches", decisions: "Décisions", evidence: "Preuves", reports: "Rapports", connectors: "Connecteurs", askAgroAi: "Demander à AGRO-AI", readiness: "Préparation", exceptions: "Exceptions", sources: "Sources", team: "Équipe", settings: "Paramètres", profile: "Profil", billing: "Facturation", security: "Sécurité", support: "Support", requests: "Demandes", admin: "Admin", systemHealth: "Santé système", logout: "Déconnexion", plan: "Forfait", settingsTitle: "Paramètres", settingsSubtitle: "Modifiez la langue, le compte, les préférences de l’espace, les notifications, l’abonnement, les intégrations et la sécurité opérationnelle depuis un seul endroit.", languageRegion: "Langue et région", languageRegionHint: "Choisissez la langue du portail. AGRO-AI reçoit aussi cette préférence pour ses réponses.", accountProfile: "Profil du compte", companyRole: "Entreprise et rôle", workspacePreferences: "Préférences de l’espace", notifications: "Notifications", subscriptionBilling: "Abonnement et facturation", integrationsControllers: "Intégrations et contrôleurs", supportTitle: "Support", supportSubtitle: "Créez un ticket suivi pour l’onboarding, l’aide d’intégration, le support opérationnel ou la revue de rapport.", contactSupport: "Contacter le support", requestType: "Type de demande", subject: "Objet", message: "Message", priority: "Priorité", sendRequest: "Envoyer la demande", requestReceived: "Demande reçue", pricingTitle: "Choisissez la couche opérationnelle pour votre intelligence agricole.", pricingSubtitle: "Commencez par un espace de travail, puis développez les rapports, la préparation des contrôleurs, les opérations terrain, la conformité et le reporting réseau." },
  es: { ...en, language: "Idioma", save: "Guardar", saved: "Guardado", saving: "Guardando…", send: "Enviar", sending: "Enviando…", newOperation: "Nueva operación", fieldOperatingRoom: "Sala de operaciones de campo", workspace: "Espacio de trabajo", operate: "Operar", intelligence: "Inteligencia", account: "Cuenta", commandCenter: "Centro de mando", fieldQueue: "Cola de campo", tasks: "Tareas", decisions: "Decisiones", evidence: "Evidencia", reports: "Informes", connectors: "Conectores", askAgroAi: "Preguntar a AGRO-AI", readiness: "Preparación", exceptions: "Excepciones", sources: "Fuentes", team: "Equipo", settings: "Configuración", profile: "Perfil", billing: "Facturación", security: "Seguridad", support: "Soporte", requests: "Solicitudes", admin: "Admin", systemHealth: "Estado del sistema", logout: "Cerrar sesión", plan: "Plan", contactSupport: "Contactar soporte", requestType: "Tipo de solicitud", subject: "Asunto", message: "Mensaje", priority: "Prioridad", sendRequest: "Enviar solicitud", requestReceived: "Solicitud recibida" },
  pt: { ...en, language: "Idioma", save: "Salvar", saved: "Salvo", saving: "Salvando…", send: "Enviar", sending: "Enviando…", newOperation: "Nova operação", workspace: "Espaço de trabalho", operate: "Operar", account: "Conta", commandCenter: "Centro de comando", fieldQueue: "Fila de campo", tasks: "Tarefas", decisions: "Decisões", evidence: "Evidências", reports: "Relatórios", connectors: "Conectores", askAgroAi: "Perguntar ao AGRO-AI", readiness: "Prontidão", settings: "Configurações", profile: "Perfil", billing: "Cobrança", security: "Segurança", support: "Suporte", requests: "Solicitações", plan: "Plano", contactSupport: "Contatar suporte", requestType: "Tipo de solicitação", subject: "Assunto", message: "Mensagem", priority: "Prioridade", sendRequest: "Enviar solicitação", requestReceived: "Solicitação recebida" },
  ar: { ...en, language: "اللغة", save: "حفظ", saved: "تم الحفظ", saving: "جارٍ الحفظ…", send: "إرسال", sending: "جارٍ الإرسال…", newOperation: "عملية جديدة", workspace: "مساحة العمل", operate: "التشغيل", account: "الحساب", commandCenter: "مركز القيادة", fieldQueue: "قائمة الحقول", tasks: "المهام", decisions: "القرارات", evidence: "الأدلة", reports: "التقارير", connectors: "الموصلات", askAgroAi: "اسأل AGRO-AI", readiness: "الجاهزية", settings: "الإعدادات", profile: "الملف الشخصي", billing: "الفوترة", security: "الأمان", support: "الدعم", requests: "الطلبات", plan: "الخطة", contactSupport: "اتصل بالدعم", requestType: "نوع الطلب", subject: "الموضوع", message: "الرسالة", priority: "الأولوية", sendRequest: "إرسال الطلب", requestReceived: "تم استلام الطلب" },
};

const LITERALS: Record<string, Record<string, string>> = {
  fr: {
    "Support": "Support", "AGRO-AI support desk": "Bureau support AGRO-AI", "This creates a tracked request for the AGRO-AI team.": "Cela crée une demande suivie pour l’équipe AGRO-AI.", "What happens next": "Ce qui se passe ensuite", "The request is saved.": "La demande est enregistrée.", "The team receives it when delivery is configured.": "L’équipe la reçoit lorsque l’envoi est configuré.", "The status can be tracked in Requests.": "Le statut peut être suivi dans Demandes.", "Workspace context": "Contexte de l’espace", "Open request inbox": "Ouvrir la boîte des demandes", "Name": "Nom", "Email": "E-mail", "Integration": "Intégration", "Issue": "Problème", "Onboarding": "Onboarding", "Sales": "Ventes",
    "Billing": "Facturation", "Review your current plan, usage, and upgrade paths.": "Consultez votre forfait actuel, l’utilisation et les options de mise à niveau.", "Current plan": "Forfait actuel", "Usage": "Utilisation", "Billing status": "Statut de facturation", "Monthly price": "Prix mensuel", "Annual price": "Prix annuel", "Annual savings": "Économies annuelles", "Evidence uploads": "Importations de preuves", "AGRO-AI messages": "Messages AGRO-AI", "Reports": "Rapports", "Field updates": "Mises à jour terrain", "Upgrade options": "Options de mise à niveau", "Add-ons": "Modules complémentaires", "Monthly": "Mensuel", "Annual": "Annuel", "Upgrade to Professional": "Passer à Professional", "Get Team plan": "Obtenir le forfait Team", "Start Network rollout": "Démarrer le déploiement Network", "Not available": "Non disponible", "Free": "Gratuit",
    "Ask AGRO-AI": "Demander à AGRO-AI", "New chat": "Nouvelle conversation", "Search chats": "Rechercher des conversations", "History": "Historique", "No saved chats yet.": "Aucune conversation enregistrée.", "Loading chats…": "Chargement des conversations…", "Start a workspace thread": "Démarrer une conversation d’espace", "Ask a question or import files.": "Posez une question ou importez des fichiers.", "AGRO-AI can save threads, reload past work, and move from answer to action: reports, email delivery, field tasks, field evidence, and approval-gated controller work.": "AGRO-AI peut enregistrer les conversations, recharger le travail passé et passer de la réponse à l’action : rapports, envoi par e-mail, tâches terrain, preuves terrain et actions contrôleur avec approbation.", "What should I do with my data?": "Que dois-je faire avec mes données ?", "Create an operator checklist.": "Créer une checklist opérateur.", "What evidence is missing?": "Quelles preuves manquent ?", "Generate a customer-ready report.": "Générer un rapport prêt pour le client.", "Preparing the answer…": "Préparation de la réponse…", "Import files": "Importer des fichiers", "Ask AGRO-AI or import files": "Demander à AGRO-AI ou importer des fichiers", "Enter to send. Shift + Enter for a new line.": "Entrée pour envoyer. Maj + Entrée pour une nouvelle ligne.", "Download PDF": "Télécharger le PDF", "Preparing PDF…": "Préparation du PDF…", "Email to me": "M’envoyer par e-mail", "Sending…": "Envoi…", "Done": "Terminé", "Working…": "Traitement…", "Create approval": "Créer une approbation", "Do it": "Exécuter",
    "Data Sources": "Sources de données", "Manage connected data sources and telemetry feeds.": "Gérez les sources de données connectées et les flux de télémétrie.", "Open brain": "Ouvrir le cerveau", "Run decision": "Lancer la décision", "Live operations": "Opérations en direct", "Workspace": "Espace de travail", "Field": "Champ", "telemetry records": "relevés télémétriques", "connectors need setup": "connecteurs à configurer", "Water": "Eau", "Assurance": "Assurance"
  },
  es: { "Billing": "Facturación", "Current plan": "Plan actual", "Usage": "Uso", "Ask AGRO-AI": "Preguntar a AGRO-AI", "New chat": "Nuevo chat", "Search chats": "Buscar chats", "History": "Historial", "Start a workspace thread": "Iniciar conversación del espacio", "Ask a question or import files.": "Haz una pregunta o importa archivos.", "Import files": "Importar archivos", "Send request": "Enviar solicitud", "Request received": "Solicitud recibida", "Subject": "Asunto", "Message": "Mensaje", "Open brain": "Abrir cerebro", "Run decision": "Ejecutar decisión" },
  pt: { "Billing": "Cobrança", "Current plan": "Plano atual", "Usage": "Uso", "Ask AGRO-AI": "Perguntar ao AGRO-AI", "New chat": "Novo chat", "Search chats": "Buscar conversas", "History": "Histórico", "Start a workspace thread": "Iniciar conversa do espaço", "Ask a question or import files.": "Faça uma pergunta ou importe arquivos.", "Import files": "Importar arquivos", "Send request": "Enviar solicitação", "Request received": "Solicitação recebida", "Subject": "Assunto", "Message": "Mensagem", "Open brain": "Abrir cérebro", "Run decision": "Executar decisão" },
  ar: { "Billing": "الفوترة", "Current plan": "الخطة الحالية", "Usage": "الاستخدام", "Ask AGRO-AI": "اسأل AGRO-AI", "New chat": "محادثة جديدة", "Search chats": "البحث في المحادثات", "History": "السجل", "Start a workspace thread": "ابدأ محادثة مساحة العمل", "Ask a question or import files.": "اطرح سؤالاً أو استورد ملفات.", "Import files": "استيراد الملفات", "Send request": "إرسال الطلب", "Request received": "تم استلام الطلب", "Subject": "الموضوع", "Message": "الرسالة", "Open brain": "فتح الدماغ", "Run decision": "تشغيل القرار" }
};

export function t(key: string, locale = currentLocale()): string {
  const root = normalizeLocale(locale).split("-")[0];
  return TRANSLATIONS[root]?.[key] || LITERALS[root]?.[key] || TRANSLATIONS.en[key] || key;
}

function translatedText(text: string, root: string) {
  const trimmed = text.trim();
  if (!trimmed || root === "en") return null;
  const hit = LITERALS[root]?.[trimmed] || TRANSLATIONS[root]?.[trimmed];
  if (!hit || hit === trimmed) return null;
  return text.replace(trimmed, hit);
}

function localizeNode(node: Node, root: string) {
  if (root === "en") return;
  const skip = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "SELECT", "OPTION", "CODE", "PRE"]);
  if (node.nodeType === Node.ELEMENT_NODE && skip.has((node as Element).tagName)) return;
  if (node.nodeType === Node.TEXT_NODE) {
    const next = translatedText(node.textContent || "", root);
    if (next) node.textContent = next;
    return;
  }
  if (node.nodeType === Node.ELEMENT_NODE) {
    const el = node as HTMLElement;
    ["placeholder", "title", "aria-label"].forEach((attr) => {
      const value = el.getAttribute(attr);
      const next = value ? translatedText(value, root) : null;
      if (next) el.setAttribute(attr, next);
    });
  }
  node.childNodes.forEach((child) => localizeNode(child, root));
}

let observer: MutationObserver | null = null;
export function applyTextLocalization(locale = currentLocale()) {
  if (typeof document === "undefined") return;
  const root = normalizeLocale(locale).split("-")[0];
  window.setTimeout(() => localizeNode(document.body, root), 0);
  if (observer) observer.disconnect();
  if (root === "en") return;
  observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      mutation.addedNodes.forEach((node) => localizeNode(node, root));
      if (mutation.type === "characterData") localizeNode(mutation.target, root);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}

export function applyLocale(locale = getStoredLocale()) {
  const normalized = normalizeLocale(locale);
  document.documentElement.lang = normalized;
  document.documentElement.dir = isRtlLocale(normalized) ? "rtl" : "ltr";
  applyTextLocalization(normalized);
}

export function setStoredLocale(locale: string) {
  try { localStorage.setItem(LANGUAGE_STORAGE_KEY, locale || "auto"); } catch { /* Best effort. */ }
  applyLocale(locale);
  window.dispatchEvent(new CustomEvent("agroai:locale-change", { detail: { locale } }));
}
