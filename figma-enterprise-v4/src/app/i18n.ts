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

const en = {
  language: "Language",
  save: "Save",
  saved: "Saved",
  saving: "Saving…",
  send: "Send",
  sending: "Sending…",
  newOperation: "New operation",
  fieldOperatingRoom: "Field operating room",
  workspace: "Workspace",
  operate: "Operate",
  intelligence: "Intelligence",
  account: "Account",
  commandCenter: "Command Center",
  fieldQueue: "Field Queue",
  tasks: "Tasks",
  decisions: "Decisions",
  evidence: "Evidence",
  reports: "Reports",
  connectors: "Connectors",
  askAgroAi: "Ask AGRO-AI",
  readiness: "Readiness",
  exceptions: "Exceptions",
  sources: "Sources",
  team: "Team",
  settings: "Settings",
  profile: "Profile",
  billing: "Billing",
  security: "Security",
  support: "Support",
  requests: "Requests",
  admin: "Admin",
  systemHealth: "System Health",
  logout: "Log out",
  plan: "Plan",
  pricingTitle: "Choose the operating layer for your farm intelligence.",
  pricingSubtitle: "Start with a workspace, then scale into reports, controller readiness, field operations, compliance, and network reporting.",
  settingsTitle: "Settings",
  settingsSubtitle: "Edit language, account, workspace preferences, notification settings, subscription, integrations, and operating safety from one place.",
  languageRegion: "Language & region",
  languageRegionHint: "Choose the portal language. Ask AGRO-AI also receives this preference when answering.",
  accountProfile: "Account profile",
  companyRole: "Company & role",
  workspacePreferences: "Workspace preferences",
  notifications: "Notifications",
  subscriptionBilling: "Subscription & billing",
  integrationsControllers: "Integrations & controllers",
  supportTitle: "Support",
  supportSubtitle: "Create a tracked support ticket for onboarding, integration help, operational support, or report review.",
  contactSupport: "Contact support",
  requestType: "Request type",
  subject: "Subject",
  message: "Message",
  priority: "Priority",
  sendRequest: "Send request",
  requestReceived: "Request received",
};

export const TRANSLATIONS: Record<string, Record<string, string>> = {
  en,
  fr: {
    ...en,
    language: "Langue", save: "Enregistrer", saved: "Enregistré", saving: "Enregistrement…", send: "Envoyer", sending: "Envoi…", newOperation: "Nouvelle opération", fieldOperatingRoom: "Salle d’opérations terrain", workspace: "Espace de travail", operate: "Opérations", intelligence: "Intelligence", account: "Compte", commandCenter: "Centre de commandement", fieldQueue: "File terrain", tasks: "Tâches", decisions: "Décisions", evidence: "Preuves", reports: "Rapports", connectors: "Connecteurs", askAgroAi: "Demander à AGRO-AI", readiness: "Préparation", exceptions: "Exceptions", sources: "Sources", team: "Équipe", settings: "Paramètres", profile: "Profil", billing: "Facturation", security: "Sécurité", support: "Support", requests: "Demandes", admin: "Admin", systemHealth: "Santé système", logout: "Déconnexion", plan: "Forfait", settingsTitle: "Paramètres", settingsSubtitle: "Modifiez la langue, le compte, les préférences de l’espace, les notifications, l’abonnement, les intégrations et la sécurité opérationnelle depuis un seul endroit.", languageRegion: "Langue et région", languageRegionHint: "Choisissez la langue du portail. AGRO-AI reçoit aussi cette préférence pour ses réponses.", accountProfile: "Profil du compte", companyRole: "Entreprise et rôle", workspacePreferences: "Préférences de l’espace", notifications: "Notifications", subscriptionBilling: "Abonnement et facturation", integrationsControllers: "Intégrations et contrôleurs", supportTitle: "Support", supportSubtitle: "Créez un ticket suivi pour l’onboarding, l’aide d’intégration, le support opérationnel ou la revue de rapport.", contactSupport: "Contacter le support", requestType: "Type de demande", subject: "Objet", message: "Message", priority: "Priorité", sendRequest: "Envoyer la demande", requestReceived: "Demande reçue", pricingTitle: "Choisissez la couche opérationnelle pour votre intelligence agricole.", pricingSubtitle: "Commencez par un espace de travail, puis développez les rapports, la préparation des contrôleurs, les opérations terrain, la conformité et le reporting réseau."
  },
  es: {
    ...en,
    language: "Idioma", save: "Guardar", saved: "Guardado", saving: "Guardando…", send: "Enviar", sending: "Enviando…", newOperation: "Nueva operación", fieldOperatingRoom: "Sala de operaciones de campo", workspace: "Espacio de trabajo", operate: "Operar", intelligence: "Inteligencia", account: "Cuenta", commandCenter: "Centro de mando", fieldQueue: "Cola de campo", tasks: "Tareas", decisions: "Decisiones", evidence: "Evidencia", reports: "Informes", connectors: "Conectores", askAgroAi: "Preguntar a AGRO-AI", readiness: "Preparación", exceptions: "Excepciones", sources: "Fuentes", team: "Equipo", settings: "Configuración", profile: "Perfil", billing: "Facturación", security: "Seguridad", support: "Soporte", requests: "Solicitudes", admin: "Admin", systemHealth: "Estado del sistema", logout: "Cerrar sesión", plan: "Plan", settingsTitle: "Configuración", settingsSubtitle: "Edita idioma, cuenta, preferencias del espacio, notificaciones, suscripción, integraciones y seguridad operativa desde un solo lugar.", languageRegion: "Idioma y región", languageRegionHint: "Elige el idioma del portal. AGRO-AI también recibe esta preferencia al responder.", accountProfile: "Perfil de cuenta", companyRole: "Empresa y rol", workspacePreferences: "Preferencias del espacio", notifications: "Notificaciones", subscriptionBilling: "Suscripción y facturación", integrationsControllers: "Integraciones y controladores", supportTitle: "Soporte", supportSubtitle: "Crea un ticket de soporte para onboarding, integraciones, soporte operativo o revisión de informes.", contactSupport: "Contactar soporte", requestType: "Tipo de solicitud", subject: "Asunto", message: "Mensaje", priority: "Prioridad", sendRequest: "Enviar solicitud", requestReceived: "Solicitud recibida", pricingTitle: "Elige la capa operativa para la inteligencia de tu campo.", pricingSubtitle: "Empieza con un espacio de trabajo y escala hacia informes, controladores, operaciones de campo, cumplimiento y reportes de red."
  },
  pt: {
    ...en,
    language: "Idioma", save: "Salvar", saved: "Salvo", saving: "Salvando…", send: "Enviar", sending: "Enviando…", newOperation: "Nova operação", fieldOperatingRoom: "Sala de operações de campo", workspace: "Espaço de trabalho", operate: "Operar", intelligence: "Inteligência", account: "Conta", commandCenter: "Centro de comando", fieldQueue: "Fila de campo", tasks: "Tarefas", decisions: "Decisões", evidence: "Evidências", reports: "Relatórios", connectors: "Conectores", askAgroAi: "Perguntar ao AGRO-AI", readiness: "Prontidão", exceptions: "Exceções", sources: "Fontes", team: "Equipe", settings: "Configurações", profile: "Perfil", billing: "Cobrança", security: "Segurança", support: "Suporte", requests: "Solicitações", admin: "Admin", systemHealth: "Saúde do sistema", logout: "Sair", plan: "Plano", settingsTitle: "Configurações", settingsSubtitle: "Edite idioma, conta, preferências do espaço de trabalho, notificações, assinatura, integrações e segurança operacional em um só lugar.", languageRegion: "Idioma e região", languageRegionHint: "Escolha o idioma do portal. O AGRO-AI também recebe essa preferência ao responder.", accountProfile: "Perfil da conta", companyRole: "Empresa e função", workspacePreferences: "Preferências do espaço", notifications: "Notificações", subscriptionBilling: "Assinatura e cobrança", integrationsControllers: "Integrações e controladores", supportTitle: "Suporte", supportSubtitle: "Crie um ticket rastreável para onboarding, ajuda com integrações, suporte operacional ou revisão de relatórios.", contactSupport: "Contatar suporte", requestType: "Tipo de solicitação", subject: "Assunto", message: "Mensagem", priority: "Prioridade", sendRequest: "Enviar solicitação", requestReceived: "Solicitação recebida", pricingTitle: "Escolha a camada operacional para a inteligência da sua fazenda.", pricingSubtitle: "Comece com um espaço de trabalho e avance para relatórios, prontidão de controladores, operações de campo, conformidade e relatórios de rede."
  },
  ar: {
    ...en,
    language: "اللغة", save: "حفظ", saved: "تم الحفظ", saving: "جارٍ الحفظ…", send: "إرسال", sending: "جارٍ الإرسال…", newOperation: "عملية جديدة", fieldOperatingRoom: "غرفة عمليات الحقل", workspace: "مساحة العمل", operate: "التشغيل", intelligence: "الذكاء", account: "الحساب", commandCenter: "مركز القيادة", fieldQueue: "قائمة الحقول", tasks: "المهام", decisions: "القرارات", evidence: "الأدلة", reports: "التقارير", connectors: "الموصلات", askAgroAi: "اسأل AGRO-AI", readiness: "الجاهزية", exceptions: "الاستثناءات", sources: "المصادر", team: "الفريق", settings: "الإعدادات", profile: "الملف الشخصي", billing: "الفوترة", security: "الأمان", support: "الدعم", requests: "الطلبات", admin: "الإدارة", systemHealth: "حالة النظام", logout: "تسجيل الخروج", plan: "الخطة", settingsTitle: "الإعدادات", settingsSubtitle: "عدّل اللغة والحساب وتفضيلات مساحة العمل والتنبيهات والاشتراك والتكاملات وسلامة التشغيل من مكان واحد.", languageRegion: "اللغة والمنطقة", languageRegionHint: "اختر لغة البوابة. يتلقى AGRO-AI هذا التفضيل أيضًا عند الإجابة.", accountProfile: "ملف الحساب", companyRole: "الشركة والدور", workspacePreferences: "تفضيلات مساحة العمل", notifications: "الإشعارات", subscriptionBilling: "الاشتراك والفوترة", integrationsControllers: "التكاملات ووحدات التحكم", supportTitle: "الدعم", supportSubtitle: "أنشئ تذكرة دعم قابلة للتتبع للإعداد أو التكاملات أو الدعم التشغيلي أو مراجعة التقارير.", contactSupport: "اتصل بالدعم", requestType: "نوع الطلب", subject: "الموضوع", message: "الرسالة", priority: "الأولوية", sendRequest: "إرسال الطلب", requestReceived: "تم استلام الطلب", pricingTitle: "اختر طبقة التشغيل لذكاء مزرعتك.", pricingSubtitle: "ابدأ بمساحة عمل ثم توسع إلى التقارير، جاهزية وحدات التحكم، عمليات الحقل، الامتثال، وتقارير الشبكة."
  },
};

export function t(key: string, locale = currentLocale()): string {
  const root = normalizeLocale(locale).split("-")[0];
  return TRANSLATIONS[root]?.[key] || TRANSLATIONS.en[key] || key;
}
