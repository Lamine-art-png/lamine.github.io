from __future__ import annotations

import logging
from html import escape

from app.core.config import settings
from app.models.saas import AccountAccessAppeal, User
from app.services.email_delivery import send_email

logger = logging.getLogger(__name__)


def portal_url() -> str:
    return (settings.APP_URL or settings.RESEND_APP_URL or "https://app.agroai-pilot.com").strip().rstrip("/")


def _frame(title: str, body: str, button_label: str | None = None, button_url: str | None = None) -> str:
    button = ""
    if button_label and button_url:
        safe_url = escape(button_url, quote=True)
        button = (
            f'<p style="margin:28px 0;text-align:center"><a href="{safe_url}" '
            f'style="display:inline-block;background:#0b3326;color:white;text-decoration:none;'
            f'padding:14px 24px;border-radius:10px;font-weight:700">{escape(button_label)}</a></p>'
        )
    return f"""<!doctype html><html><body style="margin:0;background:#f6f3ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#10231b"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:36px 16px"><tr><td align="center"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:580px;background:white;border:1px solid #e5e0d6;border-radius:18px;overflow:hidden"><tr><td style="background:#082f23;color:white;padding:28px 32px"><div style="font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:#d9f99d;font-weight:700">AGRO-AI SECURITY</div><h1 style="margin:12px 0 0;font-size:27px">{escape(title)}</h1></td></tr><tr><td style="padding:32px;font-size:15px;line-height:1.7">{body}{button}<p style="margin:26px 0 0;color:#718078;font-size:13px">AGRO-AI Enterprise Portal · Secure agricultural intelligence workspace</p></td></tr></table></td></tr></table></body></html>"""


def send_appeal_link(user: User, appeal: AccountAccessAppeal, token: str) -> dict:
    url = f"{portal_url()}/appeal?token={token}"
    subject = "Complete your AGRO-AI access appeal"
    text = (
        "Your AGRO-AI Enterprise Portal access is restricted while your organization is reverified.\n\n"
        f"Submit your appeal securely here: {url}\n\nThe link expires in 48 hours."
    )
    html = _frame(
        "Complete your access appeal",
        "<p>Your AGRO-AI Enterprise Portal access is currently restricted while we reverify the organization and intended operational use associated with the account.</p><p>Use the secure link below to provide your professional role, organization evidence, agricultural use case, and supporting information. Submitting an appeal does not automatically restore access.</p><p>The secure link expires in 48 hours.</p>",
        "Submit access appeal",
        url,
    )
    result = send_email(to_email=user.email, subject=subject, text_body=text, html_body=html)
    if not result.get("ok"):
        logger.warning("Access appeal link delivery failed user_id=%s appeal_id=%s result=%s", user.id, appeal.id, result)
    return result


def send_appeal_receipt(user: User) -> dict:
    subject = "AGRO-AI access appeal received"
    text = (
        "We received your AGRO-AI access appeal. Your account remains restricted while the information is reviewed. "
        "You will receive a decision by email."
    )
    html = _frame(
        "Access appeal received",
        "<p>We received the information you submitted.</p><p>Your account remains restricted while the appeal is reviewed. You will receive a decision or a request for additional information by email.</p>",
    )
    return send_email(to_email=user.email, subject=subject, text_body=text, html_body=html)


def send_appeal_decision(user: User, *, action: str, notes: str | None = None) -> dict:
    notes_text = (notes or "").strip()
    if action == "approve":
        subject = "Your AGRO-AI access has been restored"
        text = "Your access appeal was approved. You may sign in to the AGRO-AI Enterprise Portal again."
        body = "<p>Your access appeal was approved and portal access has been restored.</p><p>Sign in using your existing account credentials. For security, any older active session has been invalidated.</p>"
        return send_email(
            to_email=user.email,
            subject=subject,
            text_body=text,
            html_body=_frame("Access restored", body, "Sign in", portal_url()),
        )
    if action == "request_information":
        subject = "Additional information is required for your AGRO-AI access appeal"
        default_note = "Please provide stronger organization and operational evidence."
        text = (
            f"Additional information is required. Request a new secure appeal link at {portal_url()}/appeal.\n\n"
            f"Notes: {notes_text or default_note}"
        )
        body = (
            "<p>Additional information is required before a decision can be made.</p>"
            f"<p><strong>Review note:</strong> {escape(notes_text or default_note)}</p>"
            "<p>Request a new secure link from the appeal page and submit the missing information.</p>"
        )
        return send_email(
            to_email=user.email,
            subject=subject,
            text_body=text,
            html_body=_frame("More information required", body, "Return to appeal page", f"{portal_url()}/appeal"),
        )
    default_note = "The submitted information did not sufficiently verify a legitimate agricultural organization and use case."
    subject = "Your AGRO-AI access appeal was not approved"
    text = f"Your access appeal was not approved. Your account remains restricted.\n\nNotes: {notes_text or default_note}"
    body = (
        "<p>Your access appeal was not approved, and the account remains restricted.</p>"
        f"<p><strong>Decision note:</strong> {escape(notes_text or default_note)}</p>"
    )
    return send_email(
        to_email=user.email,
        subject=subject,
        text_body=text,
        html_body=_frame("Appeal not approved", body),
    )
