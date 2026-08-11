"""Localized transactional Platform API lifecycle mail with durable dedupe."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.platform_product import PlatformNotification
from app.services.email_delivery import send_email


EMAIL_COPY = {
    "en": {
        "application_received": ("AGRO-AI API application received", "We received your API access application. Platform review does not grant access automatically."),
        "needs_information": ("More information is needed for your AGRO-AI API application", "The platform review team needs additional information. Sign in to review the request."),
        "application_approved": ("AGRO-AI API application approved", "Your application was approved. Access remains subject to the program, environment, billing, and live-access conditions shown in the Developer Console."),
        "application_rejected": ("AGRO-AI API application decision", "Your application was not approved. Sign in to review the decision."),
        "beta_access_granted": ("AGRO-AI API beta access granted", "Test access has been granted. API keys are created only in the Developer Console and are never sent by email."),
        "live_access_received": ("AGRO-AI API live-access request received", "We received your live-access request. Live access is never approved automatically."),
        "live_access_approved": ("AGRO-AI API live access approved", "Your live-access request was approved subject to the recorded conditions."),
        "live_access_denied": ("AGRO-AI API live-access decision", "Your live-access request was not approved. Sign in to review the decision."),
        "access_suspended": ("AGRO-AI API access suspended", "Your Platform API program access has been suspended. Existing API keys fail closed."),
        "partner_documentation_required": ("Partner integration documentation required", "The technical review requires official partner documentation before readiness can advance."),
        "usage_50": ("AGRO-AI API usage reached 50%", "Your API credit usage reached 50% of the included amount for this billing period."),
        "usage_80": ("AGRO-AI API usage reached 80%", "Your API credit usage reached 80% of the included amount for this billing period."),
        "usage_100": ("AGRO-AI API included credits used", "Your API usage reached the included credit amount for this billing period."),
        "overage_started": ("AGRO-AI API overage started", "Eligible metered overage has started for this API billing period."),
        "unusual_usage_spike": ("Unusual AGRO-AI API usage", "We detected an unusual API usage acceleration. Review request logs and active keys."),
        "rate_limit_pressure": ("AGRO-AI API rate-limit pressure", "Your integration is repeatedly approaching or exceeding its API rate limit."),
        "payment_failed": ("AGRO-AI API payment failed", "An API subscription payment failed. Review billing details in the Developer Console."),
        "grace_period_started": ("AGRO-AI API grace period started", "Your API subscription entered its configured payment grace period."),
        "subscription_canceled": ("AGRO-AI API subscription canceled", "Your API subscription was canceled. Paid-through access follows the recorded period end."),
        "key_nearing_expiration": ("AGRO-AI API key nearing expiration", "An API key is approaching expiration. Rotate it in the Developer Console; keys are never sent by email."),
        "support_received": ("AGRO-AI API support request received", "We received your support request. Sign in to the Developer Console to review its status."),
        "support_response": ("New response to your AGRO-AI API support request", "The platform support team responded to your request. Sign in to review the response."),
    },
    "fr": {
        "application_received": ("Demande d’accès à l’API AGRO-AI reçue", "Nous avons reçu votre demande. L’examen de la plateforme n’accorde aucun accès automatiquement."),
        "needs_information": ("Informations supplémentaires requises", "L’équipe d’examen a besoin d’informations supplémentaires. Connectez-vous pour consulter la demande."),
        "application_approved": ("Demande d’accès à l’API AGRO-AI approuvée", "Votre demande a été approuvée. L’accès reste soumis au programme, à l’environnement, à la facturation et aux conditions d’accès réel."),
        "application_rejected": ("Décision concernant votre demande API", "Votre demande n’a pas été approuvée. Connectez-vous pour consulter la décision."),
        "beta_access_granted": ("Accès bêta à l’API AGRO-AI accordé", "L’accès de test est accordé. Les clés API sont créées uniquement dans la console et ne sont jamais envoyées par courriel."),
        "live_access_received": ("Demande d’accès réel reçue", "Nous avons reçu votre demande. L’accès réel n’est jamais approuvé automatiquement."),
        "live_access_approved": ("Accès réel à l’API AGRO-AI approuvé", "Votre demande a été approuvée sous réserve des conditions enregistrées."),
        "live_access_denied": ("Décision concernant l’accès réel", "Votre demande n’a pas été approuvée. Connectez-vous pour consulter la décision."),
        "access_suspended": ("Accès à l’API AGRO-AI suspendu", "Votre accès au programme API a été suspendu. Les clés existantes sont refusées immédiatement."),
        "partner_documentation_required": ("Documentation d’intégration partenaire requise", "L’examen technique exige la documentation officielle du partenaire avant toute progression de l’état de préparation."),
        "usage_50": ("Utilisation de l’API AGRO-AI à 50 %", "Votre utilisation a atteint 50 % des crédits inclus pour cette période."),
        "usage_80": ("Utilisation de l’API AGRO-AI à 80 %", "Votre utilisation a atteint 80 % des crédits inclus pour cette période."),
        "usage_100": ("Crédits inclus de l’API AGRO-AI utilisés", "Votre utilisation a atteint les crédits inclus pour cette période."),
        "overage_started": ("Dépassement de l’API AGRO-AI commencé", "Le dépassement mesuré admissible a commencé pour cette période."),
        "unusual_usage_spike": ("Utilisation inhabituelle de l’API AGRO-AI", "Une accélération inhabituelle a été détectée. Vérifiez les journaux et les clés actives."),
        "rate_limit_pressure": ("Pression sur la limite de débit AGRO-AI", "Votre intégration approche ou dépasse régulièrement sa limite de débit."),
        "payment_failed": ("Échec du paiement de l’API AGRO-AI", "Un paiement a échoué. Vérifiez les informations de facturation dans la console."),
        "grace_period_started": ("Période de grâce de l’API AGRO-AI commencée", "Votre abonnement API est entré dans sa période de grâce configurée."),
        "subscription_canceled": ("Abonnement à l’API AGRO-AI annulé", "Votre abonnement API a été annulé. L’accès payé suit la date de fin enregistrée."),
        "key_nearing_expiration": ("Clé API AGRO-AI bientôt expirée", "Une clé approche de son expiration. Faites-la pivoter dans la console; aucune clé n’est envoyée par courriel."),
        "support_received": ("Demande d’assistance API AGRO-AI reçue", "Nous avons reçu votre demande d’assistance. Connectez-vous à la console pour consulter son état."),
        "support_response": ("Nouvelle réponse à votre demande d’assistance API AGRO-AI", "L’équipe d’assistance a répondu à votre demande. Connectez-vous pour consulter la réponse."),
    },
}


def queue_and_send_product_email(
    db: Session,
    *,
    organization_id: str,
    user_id: str | None,
    to_email: str,
    notification_type: str,
    dedupe_key: str,
    locale: str = "en",
    safe_context: dict | None = None,
) -> PlatformNotification:
    selected_locale = locale if locale in EMAIL_COPY else "en"
    existing = (
        db.query(PlatformNotification)
        .filter(
            PlatformNotification.organization_id == organization_id,
            PlatformNotification.notification_type == notification_type,
            PlatformNotification.dedupe_key == dedupe_key,
        )
        .first()
    )
    if existing:
        return existing
    row = PlatformNotification(
        organization_id=organization_id,
        user_id=user_id,
        notification_type=notification_type,
        dedupe_key=dedupe_key,
        locale=selected_locale,
        status="pending",
        safe_context_json=safe_context or {},
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        found = (
            db.query(PlatformNotification)
            .filter(
                PlatformNotification.organization_id == organization_id,
                PlatformNotification.notification_type == notification_type,
                PlatformNotification.dedupe_key == dedupe_key,
            )
            .first()
        )
        if found is None:
            raise
        return found
    subject, body = EMAIL_COPY[selected_locale][notification_type]
    result = send_email(to_email=to_email, subject=subject, text_body=body)
    row.status = "sent" if result.get("ok") else "delivery_pending"
    row.sent_at = datetime.utcnow() if result.get("ok") else None
    return row
