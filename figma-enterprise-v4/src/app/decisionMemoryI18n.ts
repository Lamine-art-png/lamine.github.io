import sharedDecisionMemoryEn from "../../../shared/ui-decision-memory.en.json";
import { TRANSLATIONS } from "./i18n";

export const DECISION_MEMORY_EN: Record<string, string> = {
  ...sharedDecisionMemoryEn,
};

export const DECISION_MEMORY_FR: Record<string, string> = {
  "decisionMemory.lifecycle": "Cycle de décision",
  "decisionMemory.specialists": "Cellules spécialisées",
  "decisionMemory.learning": "Résultats vérifiés",
  "decisionMemory.approve": "Approuver la décision",
  "decisionMemory.reject": "Rejeter la décision",
  "decisionMemory.rejectionReason": "Motif du rejet",
  "decisionMemory.startExecution": "Démarrer l’exécution",
  "decisionMemory.executionEvidence": "Preuves d’exécution",
  "decisionMemory.recordExecution": "Enregistrer l’exécution",
  "decisionMemory.startVerification": "Démarrer la vérification",
  "decisionMemory.verificationEvidence": "Preuves de vérification",
  "decisionMemory.outcome": "Résultat vérifié",
  "decisionMemory.verify": "Enregistrer le résultat vérifié",
  "decisionMemory.noEvidence": "Aucune preuve durable admissible n’est disponible pour cette portée.",
  "decisionMemory.selectEvidence": "Sélectionnez au moins une preuve durable.",
  "decisionMemory.state.proposed": "Proposée",
  "decisionMemory.state.awaiting_approval": "En attente d’approbation",
  "decisionMemory.state.approved": "Approuvée",
  "decisionMemory.state.rejected": "Rejetée",
  "decisionMemory.state.execution_pending": "Exécution en attente",
  "decisionMemory.state.executed": "Exécutée",
  "decisionMemory.state.verification_pending": "Vérification en attente",
  "decisionMemory.state.verified": "Vérifiée",
  "decisionMemory.state.failed": "Échec",
  "decisionMemory.state.expired": "Expirée",
  "decisionMemory.state.cancelled": "Annulée",
  "decisionMemory.domain.water": "Eau",
  "decisionMemory.domain.crop_health": "Santé des cultures",
  "decisionMemory.domain.equipment": "Équipement",
  "decisionMemory.domain.assurance": "Assurance",
  "decisionMemory.domain.reporting": "Rapports",
  "decisionMemory.domain.operations": "Opérations",
  "decisionMemory.specialistStatus.evidence_available": "Preuves disponibles",
  "decisionMemory.specialistStatus.evidence_limited": "Preuves limitées",
  "decisionMemory.specialistStatus.conflict_review": "Conflit à examiner",
  "decisionMemory.evidenceType.evidence_record": "Preuve enregistrée",
  "decisionMemory.evidenceType.field_observation": "Observation terrain",
  "decisionMemory.evidenceType.execution_verification": "Vérification d’exécution",
  "decisionMemory.outcome.effective": "Efficace",
  "decisionMemory.outcome.partially_effective": "Partiellement efficace",
  "decisionMemory.outcome.ineffective": "Inefficace",
  "decisionMemory.outcome.matched": "Conforme",
  "decisionMemory.outcome.partially_matched": "Partiellement conforme",
  "decisionMemory.outcome.deviated": "Écart constaté",
  "decisionMemory.outcome.failed": "Échec",
  "decisionMemory.outcome.agronomically_ineffective": "Inefficace sur le plan agronomique",
  "decisionMemory.outcome.inconclusive": "Non concluant",
  "decisionMemory.outcome.no_change": "Aucun changement",
  "decisionMemory.task.chat": "Conversation",
  "decisionMemory.task.field_diagnosis": "Diagnostic terrain",
  "decisionMemory.task.exception_triage": "Triage des exceptions",
  "decisionMemory.task.decision_workbench": "Atelier de décision",
  "decisionMemory.task.report_factory": "Génération de rapports",
  "decisionMemory.task.connector_diagnosis": "Diagnostic des connecteurs",
  "decisionMemory.task.readiness_analysis": "Analyse de préparation",
  "decisionMemory.task.irrigation_decision": "Décision d’irrigation",
  "decisionMemory.change.first_decision": "Aucune décision immuable antérieure n’existe dans la même portée de champ et de domaine.",
  "decisionMemory.change.evidence_changed": "L’ensemble des preuves a changé.",
  "decisionMemory.change.science_changed": "Un ou plusieurs résultats scientifiques déterministes ont changé.",
  "decisionMemory.change.conflicts_changed": "L’ensemble des conflits de preuves enregistrés a changé.",
  "decisionMemory.change.unknowns_changed": "L’ensemble des inconnues non résolues a changé.",
  "decisionMemory.change.confidence_changed": "La confiance de l’ancrage a changé.",
  "decisionMemory.change.field_state_changed": "La décision fait référence à une autre révision immuable de l’état du champ.",
  "decisionMemory.change.recommendation_changed": "La recommandation gouvernée a changé après validation.",
  "decisionMemory.change.no_material_change": "Aucune différence matérielle dans les entrées persistées ou la décision n’a été détectée.",
};

let installed = false;

export function installDecisionMemoryBaseCatalogs() {
  if (installed) return;
  const enKeys = Object.keys(DECISION_MEMORY_EN).sort();
  const frKeys = Object.keys(DECISION_MEMORY_FR).sort();
  if (!enKeys.length || enKeys.length !== frKeys.length || enKeys.some((key, index) => key !== frKeys[index])) {
    throw new Error("Decision Memory French catalog must have exact key parity with the English source.");
  }
  Object.assign(TRANSLATIONS.en, DECISION_MEMORY_EN);
  Object.assign(TRANSLATIONS["fr-FR"], DECISION_MEMORY_FR);
  installed = true;
}