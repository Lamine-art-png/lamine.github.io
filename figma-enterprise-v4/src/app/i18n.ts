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
  "home.eyebrow": "Live operations",
  "home.title": "AGRO-AI operating room",
  "home.body": "The portal is online. Use Ask AGRO-AI to work through field data, imported files, readiness gaps, water/compliance evidence, and customer-ready reports.",
  "home.openAsk": "Open Ask AGRO-AI",
  "home.reviewEvidence": "Review evidence",
  "home.checkReadiness": "Check readiness",
  "routeRecovery.title": "Workspace module recovered safely.",
  "routeRecovery.body": "This route hit a safe recovery boundary instead of crashing the portal. Continue to the operating room, Ask AGRO-AI, or Settings.",
  "routeRecovery.continue": "Continue to portal",
  "routeRecovery.openAsk": "Open Ask AGRO-AI",
  "routeRecovery.settings": "Settings",
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
  fieldIntelligence: "Field Intelligence",
  "fieldIntel.eyebrow": "Voice-first field capture",
  "fieldIntel.title": "Field Intelligence",
  "fieldIntel.subtitle": "Record or type an observation, attach evidence, capture location, and sync it into AGRO-AI — even offline.",
  "fieldIntel.online": "Online", "fieldIntel.offline": "Offline", "fieldIntel.pending": "Pending",
  "fieldIntel.lastSync": "Last sync", "fieldIntel.never": "Never", "fieldIntel.syncNow": "Sync now",
  "fieldIntel.timeline": "Timeline", "fieldIntel.map": "Map",
  "fieldIntel.compose": "New observation", "fieldIntel.record": "Record", "fieldIntel.stop": "Stop",
  "fieldIntel.recording": "Recording", "fieldIntel.micUnsupported": "Voice recording is not supported on this device. Use a typed note.",
  "fieldIntel.micDenied": "Microphone permission was denied. Use a typed note or enable the microphone.",
  "fieldIntel.typedNote": "Typed note", "fieldIntel.notePlaceholder": "Describe what you observed in the field...",
  "fieldIntel.field": "Field", "fieldIntel.block": "Block", "fieldIntel.crop": "Crop", "fieldIntel.assignee": "Assignee",
  "fieldIntel.eventType": "Event type", "fieldIntel.severity": "Severity",
  "fieldIntel.captureLocation": "Capture location", "fieldIntel.locationCaptured": "Location captured",
  "fieldIntel.locationDenied": "Location permission was denied or unavailable.", "fieldIntel.accuracy": "Accuracy",
  "fieldIntel.attach": "Attach", "fieldIntel.attachments": "attachments",
  "fieldIntel.saveOffline": "Save observation", "fieldIntel.saved": "Observation saved and queued for sync.",
  "fieldIntel.searchPlaceholder": "Search observations", "fieldIntel.filterSeverity": "Filter by severity",
  "fieldIntel.filterState": "Filter by sync state", "fieldIntel.all": "All",
  "fieldIntel.noObservations": "No observations yet. Record or type your first field note.",
  "fieldIntel.voiceCapture": "Voice capture", "fieldIntel.unassignedField": "Unassigned field", "fieldIntel.needsReview": "Needs review",
  "fieldIntel.confidence": "Confidence", "fieldIntel.tasks": "tasks",
  "fieldIntel.retry": "Retry", "fieldIntel.delete": "Delete",
  "fieldIntel.confirmDelete": "Delete this unsynced capture? Its recording and photos will be lost.",
  "fieldIntel.mapFallback": "Map view", "fieldIntel.noGeolocated": "No geolocated observations to show yet.",
  "fieldIntel.transcript": "Transcript", "fieldIntel.summary": "Summary", "fieldIntel.recommended": "Recommended next action",
  "fieldIntel.createTask": "Create task", "fieldIntel.correlation": "AGRO-AI correlation",
  "fieldIntel.noCorrelation": "No correlated evidence found in the observation window.", "fieldIntel.sources": "Sources",
  "fieldIntel.provenance": "Provenance", "fieldIntel.audit": "Audit history", "fieldIntel.uncertain": "Uncertain fields",
  "fieldIntel.correctTranscript": "Correct transcript", "fieldIntel.save": "Save", "fieldIntel.cancel": "Cancel", "fieldIntel.close": "Close",
  "fieldIntel.locked": "Field Intelligence is available on a higher plan. Upgrade to capture voice-first field observations.",
  "fieldIntel.upgrade": "View plans",
  "fieldIntel.sev.info": "Info", "fieldIntel.sev.low": "Low", "fieldIntel.sev.medium": "Medium", "fieldIntel.sev.high": "High", "fieldIntel.sev.critical": "Critical",
  "fieldIntel.evt.observation": "Observation", "fieldIntel.evt.irrigation_event": "Irrigation event", "fieldIntel.evt.issue": "Issue",
  "fieldIntel.evt.meter_reading": "Meter reading", "fieldIntel.evt.pest_disease": "Pest or disease", "fieldIntel.evt.equipment": "Equipment",
  "fieldIntel.evt.compliance_note": "Compliance note", "fieldIntel.evt.operator_note": "Operator note",
  "fieldIntel.state.draft": "Draft", "fieldIntel.state.queued": "Queued", "fieldIntel.state.syncing": "Syncing",
  "fieldIntel.state.processing": "Processing", "fieldIntel.state.synced": "Synced", "fieldIntel.state.failed": "Failed", "fieldIntel.state.conflict": "Conflict",
  "fieldIntel.state.manual_recovery": "Needs manual retry",
  "fieldIntel.maxDurationReached": "Maximum recording length reached — recording stopped.",
  "fieldIntel.recordingReady": "Recording ready",
  "fieldIntel.reviewTitle": "Review before saving",
  "fieldIntel.reviewHint": "Play back the recording, check details and attachments, then confirm.",
  "fieldIntel.retake": "Retake recording",
  "fieldIntel.removeAttachment": "Remove",
  "fieldIntel.backToEdit": "Back to edit",
  "fieldIntel.confirmQueue": "Confirm and queue",
  "fieldIntel.reviewAndSave": "Review and save",
  "fieldIntel.media": "Media",
  "fieldIntel.mediaLoading": "Loading media…",
  "fieldIntel.mediaFailed": "Media could not be loaded.",
  "fieldIntel.mediaDeleted": "This media has been deleted.",
  "fieldIntel.download": "Download",
  "fieldIntel.audioPlayer": "Audio evidence player",
  "fieldIntel.videoPlayer": "Video evidence player",
  "fieldIntel.photoEvidence": "Photo evidence",
  "fieldIntel.fileEvidence": "File evidence",
  "fieldIntel.transcriptWithAudio": "Transcript",
  "fieldIntel.kind.audio": "Audio", "fieldIntel.kind.video": "Video",
  "fieldIntel.kind.photo": "Photo", "fieldIntel.kind.file": "File",
  "syncCenter.indicator": "Synchronization status",
  "syncCenter.title": "Sync center",
  "syncCenter.close": "Close",
  "syncCenter.workspace": "Workspace",
  "syncCenter.account": "Account",
  "syncCenter.queued": "Queued", "syncCenter.syncing": "Syncing", "syncCenter.processing": "Processing",
  "syncCenter.failed": "Failed", "syncCenter.conflict": "Conflict", "syncCenter.manualRecovery": "Manual",
  "syncCenter.needsAttention": "Needs attention",
  "syncCenter.retry": "Retry", "syncCenter.inspect": "Inspect", "syncCenter.export": "Export",
  "syncCenter.discard": "Discard",
  "syncCenter.discardConfirm": "Discard this unsynced observation? Its local recording and attachments will be lost.",
  "syncCenter.noErrorDetail": "No error detail recorded.",
};

const frFR: Record<string, string> = {
  "app.loadingSession": "Chargement de la session",
  "app.loadingPortal": "Chargement du portail",
  "app.recoveryEyebrow": "Portail Entreprise AGRO-AI",
  "app.recoveryTitle": "Mode de récupération du portail",
  "app.recoveryBody": "Le portail a démarré en sécurité, mais un module de l’espace de travail n’a pas pu se charger. Cet écran évite une page blanche pendant la réparation du module.",
  "app.reloadPortal": "Recharger le portail",
  "app.clearSession": "Effacer la session et se reconnecter",
  "home.eyebrow": "Opérations en direct",
  "home.title": "Salle des opérations AGRO-AI",
  "home.body": "Le portail est en ligne. Utilisez AGRO-AI pour travailler sur les données terrain, les fichiers importés, les écarts de préparation, les preuves liées à l’eau et à la conformité, ainsi que les rapports prêts à être présentés aux clients.",
  "home.openAsk": "Ouvrir AGRO-AI",
  "home.reviewEvidence": "Examiner les preuves",
  "home.checkReadiness": "Vérifier l’état de préparation",
  "routeRecovery.title": "Le module de l’espace de travail a été récupéré en toute sécurité.",
  "routeRecovery.body": "Cette route a atteint une limite de récupération sûre au lieu de faire planter le portail. Continuez vers la salle des opérations, AGRO-AI ou les paramètres.",
  "routeRecovery.continue": "Continuer vers le portail",
  "routeRecovery.openAsk": "Ouvrir AGRO-AI",
  "routeRecovery.settings": "Paramètres",
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
  fieldIntelligence: "Intelligence terrain",
  "fieldIntel.eyebrow": "Capture terrain à la voix",
  "fieldIntel.title": "Intelligence terrain",
  "fieldIntel.subtitle": "Enregistrez ou saisissez une observation, joignez des preuves, capturez la localisation et synchronisez le tout dans AGRO-AI — même hors ligne.",
  "fieldIntel.online": "En ligne", "fieldIntel.offline": "Hors ligne", "fieldIntel.pending": "En attente",
  "fieldIntel.lastSync": "Dernière synchro", "fieldIntel.never": "Jamais", "fieldIntel.syncNow": "Synchroniser",
  "fieldIntel.timeline": "Chronologie", "fieldIntel.map": "Carte",
  "fieldIntel.compose": "Nouvelle observation", "fieldIntel.record": "Enregistrer", "fieldIntel.stop": "Arrêter",
  "fieldIntel.recording": "Enregistrement", "fieldIntel.micUnsupported": "L’enregistrement vocal n’est pas pris en charge sur cet appareil. Utilisez une note saisie.",
  "fieldIntel.micDenied": "L’accès au microphone a été refusé. Utilisez une note saisie ou activez le microphone.",
  "fieldIntel.typedNote": "Note saisie", "fieldIntel.notePlaceholder": "Décrivez ce que vous avez observé sur le terrain...",
  "fieldIntel.field": "Champ", "fieldIntel.block": "Bloc", "fieldIntel.crop": "Culture", "fieldIntel.assignee": "Responsable",
  "fieldIntel.eventType": "Type d’événement", "fieldIntel.severity": "Gravité",
  "fieldIntel.captureLocation": "Capturer la localisation", "fieldIntel.locationCaptured": "Localisation capturée",
  "fieldIntel.locationDenied": "L’accès à la localisation a été refusé ou est indisponible.", "fieldIntel.accuracy": "Précision",
  "fieldIntel.attach": "Joindre", "fieldIntel.attachments": "pièces jointes",
  "fieldIntel.saveOffline": "Enregistrer l’observation", "fieldIntel.saved": "Observation enregistrée et mise en file pour synchronisation.",
  "fieldIntel.searchPlaceholder": "Rechercher des observations", "fieldIntel.filterSeverity": "Filtrer par gravité",
  "fieldIntel.filterState": "Filtrer par état de synchro", "fieldIntel.all": "Tous",
  "fieldIntel.noObservations": "Aucune observation pour l’instant. Enregistrez ou saisissez votre première note terrain.",
  "fieldIntel.voiceCapture": "Capture vocale", "fieldIntel.unassignedField": "Champ non attribué", "fieldIntel.needsReview": "À vérifier",
  "fieldIntel.confidence": "Confiance", "fieldIntel.tasks": "tâches",
  "fieldIntel.retry": "Réessayer", "fieldIntel.delete": "Supprimer",
  "fieldIntel.confirmDelete": "Supprimer cette capture non synchronisée ? Son enregistrement et ses photos seront perdus.",
  "fieldIntel.mapFallback": "Vue carte", "fieldIntel.noGeolocated": "Aucune observation géolocalisée à afficher pour l’instant.",
  "fieldIntel.transcript": "Transcription", "fieldIntel.summary": "Résumé", "fieldIntel.recommended": "Action recommandée",
  "fieldIntel.createTask": "Créer une tâche", "fieldIntel.correlation": "Corrélation AGRO-AI",
  "fieldIntel.noCorrelation": "Aucune preuve corrélée trouvée dans la fenêtre d’observation.", "fieldIntel.sources": "Sources",
  "fieldIntel.provenance": "Provenance", "fieldIntel.audit": "Historique d’audit", "fieldIntel.uncertain": "Champs incertains",
  "fieldIntel.correctTranscript": "Corriger la transcription", "fieldIntel.save": "Enregistrer", "fieldIntel.cancel": "Annuler", "fieldIntel.close": "Fermer",
  "fieldIntel.locked": "L’Intelligence terrain est disponible sur un forfait supérieur. Mettez à niveau pour capturer des observations terrain à la voix.",
  "fieldIntel.upgrade": "Voir les forfaits",
  "fieldIntel.sev.info": "Info", "fieldIntel.sev.low": "Faible", "fieldIntel.sev.medium": "Moyenne", "fieldIntel.sev.high": "Élevée", "fieldIntel.sev.critical": "Critique",
  "fieldIntel.evt.observation": "Observation", "fieldIntel.evt.irrigation_event": "Événement d’irrigation", "fieldIntel.evt.issue": "Problème",
  "fieldIntel.evt.meter_reading": "Relevé de compteur", "fieldIntel.evt.pest_disease": "Ravageur ou maladie", "fieldIntel.evt.equipment": "Équipement",
  "fieldIntel.evt.compliance_note": "Note de conformité", "fieldIntel.evt.operator_note": "Note d’opérateur",
  "fieldIntel.state.draft": "Brouillon", "fieldIntel.state.queued": "En file", "fieldIntel.state.syncing": "Synchronisation",
  "fieldIntel.state.processing": "Traitement", "fieldIntel.state.synced": "Synchronisé", "fieldIntel.state.failed": "Échec", "fieldIntel.state.conflict": "Conflit",
  "fieldIntel.state.manual_recovery": "Nouvelle tentative manuelle requise",
  "fieldIntel.maxDurationReached": "Durée maximale d’enregistrement atteinte — enregistrement arrêté.",
  "fieldIntel.recordingReady": "Enregistrement prêt",
  "fieldIntel.reviewTitle": "Vérifier avant d’enregistrer",
  "fieldIntel.reviewHint": "Réécoutez l’enregistrement, vérifiez les détails et pièces jointes, puis confirmez.",
  "fieldIntel.retake": "Refaire l’enregistrement",
  "fieldIntel.removeAttachment": "Retirer",
  "fieldIntel.backToEdit": "Revenir à l’édition",
  "fieldIntel.confirmQueue": "Confirmer et mettre en file",
  "fieldIntel.reviewAndSave": "Vérifier et enregistrer",
  "fieldIntel.media": "Médias",
  "fieldIntel.mediaLoading": "Chargement du média…",
  "fieldIntel.mediaFailed": "Impossible de charger le média.",
  "fieldIntel.mediaDeleted": "Ce média a été supprimé.",
  "fieldIntel.download": "Télécharger",
  "fieldIntel.audioPlayer": "Lecteur audio des preuves",
  "fieldIntel.videoPlayer": "Lecteur vidéo des preuves",
  "fieldIntel.photoEvidence": "Preuve photo",
  "fieldIntel.fileEvidence": "Preuve fichier",
  "fieldIntel.transcriptWithAudio": "Transcription",
  "fieldIntel.kind.audio": "Audio", "fieldIntel.kind.video": "Vidéo",
  "fieldIntel.kind.photo": "Photo", "fieldIntel.kind.file": "Fichier",
  "syncCenter.indicator": "État de synchronisation",
  "syncCenter.title": "Centre de synchronisation",
  "syncCenter.close": "Fermer",
  "syncCenter.workspace": "Espace de travail",
  "syncCenter.account": "Compte",
  "syncCenter.queued": "En file", "syncCenter.syncing": "Synchronisation", "syncCenter.processing": "Traitement",
  "syncCenter.failed": "Échec", "syncCenter.conflict": "Conflit", "syncCenter.manualRecovery": "Manuel",
  "syncCenter.needsAttention": "Attention requise",
  "syncCenter.retry": "Réessayer", "syncCenter.inspect": "Inspecter", "syncCenter.export": "Exporter",
  "syncCenter.discard": "Abandonner",
  "syncCenter.discardConfirm": "Abandonner cette observation non synchronisée ? Son enregistrement local et ses pièces jointes seront perdus.",
  "syncCenter.noErrorDetail": "Aucun détail d’erreur enregistré.",
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
