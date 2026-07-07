import sharedUiSourcePart7 from "../../../shared/ui-literals.en.7.json";
import { TRANSLATIONS } from "./i18n";

export const COMMERCIAL_BOUNDARY_EN: Record<string, string> = Object.fromEntries(
  Object.entries(sharedUiSourcePart7).filter(([key]) => key.startsWith("commercialBoundary.")),
);

export const COMMERCIAL_BOUNDARY_FR: Record<string, string> = {
  "commercialBoundary.accessEyebrow": "Accès AGRO-AI",
  "commercialBoundary.close": "Fermer le message de mise à niveau",
  "commercialBoundary.title.quota": "Vous avez atteint la limite de ce forfait",
  "commercialBoundary.title.restore": "Rétablir l’accès commercial",
  "commercialBoundary.title.upgrade": "Mettre à niveau pour continuer",
  "commercialBoundary.body.quota": "Le quota commercial actuel est épuisé pour cette période. Passez à un forfait supérieur pour continuer à opérer sans attendre la réinitialisation.",
  "commercialBoundary.body.unavailable": "Cette fonctionnalité n’est pas incluse dans l’état commercial actuel de l’organisation.",
  "commercialBoundary.quotaReset": "L’utilisation est appliquée côté serveur et se réinitialise avec la période commerciale.",
  "commercialBoundary.currentPlan": "Forfait actuel",
  "commercialBoundary.recommended": "Recommandé",
  "commercialBoundary.why": "Pourquoi ce message s’affiche",
  "commercialBoundary.reason": "AGRO-AI applique les fonctionnalités commerciales et les quotas côté serveur, pas seulement dans l’interface.",
  "commercialBoundary.reasonFeature": "Fonctionnalité restreinte : {feature}. AGRO-AI applique l’accès côté serveur, pas seulement dans l’interface.",
  "commercialBoundary.reasonMetric": "Limite du forfait : {metric}. AGRO-AI applique les quotas côté serveur, pas seulement dans l’interface.",
  "commercialBoundary.reasonFeatureMetric": "Fonctionnalité restreinte : {feature}. Limite du forfait : {metric}. AGRO-AI applique les deux côté serveur, pas seulement dans l’interface.",
  "commercialBoundary.talkToSales": "Contacter l’équipe commerciale",
  "commercialBoundary.upgradeTo": "Passer au forfait {plan}",
  "commercialBoundary.notNow": "Pas maintenant",
  "commercialBoundary.perMonth": "/mois",
  "commercialBoundary.customPrice": "Sur mesure",
  "commercialBoundary.planUsage": "Utilisation du forfait",
  "commercialBoundary.restrictedCapability": "Fonctionnalité restreinte",
  "commercialBoundary.planLimit": "Limite du forfait",
  "commercialBoundary.feature.reportsGenerate": "Débloquer les rapports commerciaux",
  "commercialBoundary.feature.reportsPdfExport": "Débloquer les exports PDF",
  "commercialBoundary.feature.reportsEmailDelivery": "Débloquer l’envoi de rapports",
  "commercialBoundary.feature.connectorsLive": "Connecter les systèmes opérationnels en direct",
  "commercialBoundary.feature.connectorsOauthDocuments": "Connecter les sources documentaires approuvées",
  "commercialBoundary.feature.connectorsCustomIntegration": "Définir une intégration d’entreprise",
  "commercialBoundary.feature.teamInvite": "Ajouter votre équipe opérationnelle",
  "commercialBoundary.feature.adminRequests": "Débloquer la boîte de demandes",
  "commercialBoundary.feature.agentsExecuteSafe": "Débloquer l’exécution des agents",
  "commercialBoundary.feature.agentsExecuteApproval": "Débloquer les agents soumis à approbation",
  "commercialBoundary.feature.intelligenceDeepAnalysis": "Débloquer l’analyse approfondie",
  "commercialBoundary.capability.reportsGenerate": "Rapports commerciaux",
  "commercialBoundary.capability.reportsPdfExport": "Exports PDF",
  "commercialBoundary.capability.reportsEmailDelivery": "Envoi de rapports",
  "commercialBoundary.capability.connectorsLive": "Systèmes opérationnels en direct",
  "commercialBoundary.capability.connectorsOauthDocuments": "Sources documentaires approuvées",
  "commercialBoundary.capability.connectorsCustomIntegration": "Intégration personnalisée",
  "commercialBoundary.capability.teamInvite": "Invitations d’équipe",
  "commercialBoundary.capability.adminRequests": "Boîte de demandes",
  "commercialBoundary.capability.agentsExecuteSafe": "Exécution des agents",
  "commercialBoundary.capability.agentsExecuteApproval": "Agents soumis à approbation",
  "commercialBoundary.capability.intelligenceDeepAnalysis": "Analyse approfondie",
  "commercialBoundary.metric.workspaces": "Espaces de travail",
  "commercialBoundary.metric.seats": "Postes utilisateurs",
  "commercialBoundary.metric.intelligenceActions": "Actions AGRO-AI",
  "commercialBoundary.metric.evidenceUploads": "Imports de preuves",
  "commercialBoundary.metric.activeConnectors": "Connecteurs actifs",
  "commercialBoundary.metric.reportGenerations": "Générations de rapports",
  "commercialBoundary.metric.pdfExports": "Exports PDF",
  "commercialBoundary.metric.emailDeliveries": "Envois de rapports",
  "commercialBoundary.metric.agentRuns": "Exécutions d’agents",
  "commercialBoundary.metric.deepAnalyses": "Analyses approfondies",
  "commercialBoundary.plan.free": "Gratuit",
  "commercialBoundary.plan.professional": "Professionnel",
  "commercialBoundary.plan.team": "Équipe",
  "commercialBoundary.plan.network": "Réseau",
  "commercialBoundary.plan.enterprise": "Entreprise",
  "commercialBoundary.plan.free.bullet1": "1 espace de travail",
  "commercialBoundary.plan.free.bullet2": "25 actions AGRO-AI/mois",
  "commercialBoundary.plan.free.bullet3": "10 imports de preuves/mois",
  "commercialBoundary.plan.professional.bullet1": "5 espaces de travail et 3 postes",
  "commercialBoundary.plan.professional.bullet2": "500 actions AGRO-AI/mois",
  "commercialBoundary.plan.professional.bullet3": "Rapports, PDF et connecteurs en direct",
  "commercialBoundary.plan.team.bullet1": "25 espaces de travail et 10 postes",
  "commercialBoundary.plan.team.bullet2": "2 500 actions AGRO-AI/mois",
  "commercialBoundary.plan.team.bullet3": "Preuves partagées, rôles et approbations",
  "commercialBoundary.plan.network.bullet1": "50 espaces de travail et 25 postes",
  "commercialBoundary.plan.network.bullet2": "10 000 actions AGRO-AI/mois",
  "commercialBoundary.plan.network.bullet3": "Consolidation multi-espaces et rapports réseau",
  "commercialBoundary.plan.enterprise.bullet1": "Capacité configurée par contrat",
  "commercialBoundary.plan.enterprise.bullet2": "Intégrations personnalisées et gouvernance",
  "commercialBoundary.plan.enterprise.bullet3": "Déploiement dédié et revue de sécurité",
};

let installed = false;

export function installCommercialBoundaryBaseCatalogs() {
  if (installed) return;
  const enKeys = Object.keys(COMMERCIAL_BOUNDARY_EN).sort();
  const frKeys = Object.keys(COMMERCIAL_BOUNDARY_FR).sort();
  if (!enKeys.length || enKeys.length !== frKeys.length || enKeys.some((key, index) => key !== frKeys[index])) {
    throw new Error("Commercial boundary French catalog must have exact key parity with shared English source.");
  }
  Object.assign(TRANSLATIONS.en, COMMERCIAL_BOUNDARY_EN);
  Object.assign(TRANSLATIONS["fr-FR"], COMMERCIAL_BOUNDARY_FR);
  installed = true;
}
