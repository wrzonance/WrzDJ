"""Email sending via Resend API for verification codes."""

import logging

import resend

from app.core.config import get_settings

_logger = logging.getLogger("app.email")


class EmailNotConfiguredError(Exception):
    """Raised when email API key is missing."""


class EmailSendError(Exception):
    """Raised when email sending fails."""


def send_verification_email(to_address: str, code: str) -> None:
    """Send a 6-digit verification code via Resend."""
    settings = get_settings()

    if not settings.resend_api_key or not settings.email_from_address:
        raise EmailNotConfiguredError("Resend API key or from address is not configured")

    resend.api_key = settings.resend_api_key

    try:
        resend.Emails.send(
            {
                "from": settings.email_from_address,
                "to": [to_address],
                "subject": "Your WrzDJ verification code",
                "text": (
                    f"Your verification code is: {code}\n\n"
                    f"Enter this code on the WrzDJ page. It expires in 15 minutes.\n\n"
                    f"If you didn't request this, you can safely ignore this email.\n"
                ),
            }
        )
    except Exception as exc:
        _logger.error("email.send_failed to_hash=%s error=%s", to_address[:3] + "***", exc)
        raise EmailSendError(str(exc)) from exc

    _logger.info("email.sent to_hash=%s", to_address[:3] + "***")


def send_email_confirmation(to_address: str, confirmation_url: str) -> None:
    """Send an email address confirmation link via Resend."""
    settings = get_settings()

    if not settings.resend_api_key or not settings.email_from_address:
        raise EmailNotConfiguredError("Resend API key or from address is not configured")

    resend.api_key = settings.resend_api_key

    try:
        resend.Emails.send(
            {
                "from": settings.email_from_address,
                "to": [to_address],
                "subject": "Confirm your new WrzDJ email address",
                "text": (
                    "Click the link below to confirm your new email address:\n\n"
                    f"{confirmation_url}\n\n"
                    "This link expires in 24 hours.\n\n"
                    "If you didn't request this change, you can safely ignore this email.\n"
                ),
            }
        )
    except Exception as exc:
        _logger.error(
            "email.confirmation_send_failed to_hash=%s error=%s",
            to_address[:3] + "***",
            exc,
        )
        raise EmailSendError(str(exc)) from exc

    _logger.info("email.confirmation_sent to_hash=%s", to_address[:3] + "***")


def send_connector_auth_invalid_notification(
    to_address: str, display_name: str, connector_type: str
) -> None:
    """Notify a DJ that their LLM connector failed a background health check.

    Triggered by the periodic connector health monitor (issue #340) when a
    previously-active connector transitions to ``auth_invalid``. Never
    includes credential material — only the display name and provider type
    so the DJ can identify which key to rotate.
    """
    settings = get_settings()

    if not settings.resend_api_key or not settings.email_from_address:
        raise EmailNotConfiguredError("Resend API key or from address is not configured")

    # Strip control characters defensively — display_name is user-supplied
    # (DJ-set) and already validated at creation, but the connector_type comes
    # from the registry. Belt-and-braces for an email body.
    safe_display = "".join(c for c in (display_name or "") if c.isprintable())
    safe_type = "".join(c for c in (connector_type or "") if c.isprintable())

    resend.api_key = settings.resend_api_key

    try:
        resend.Emails.send(
            {
                "from": settings.email_from_address,
                "to": [to_address],
                "subject": "Your WrzDJ AI connector needs attention",
                "text": (
                    f'Your AI connector "{safe_display}" ({safe_type}) failed a '
                    f"health check and was marked invalid.\n\n"
                    f"This usually means the API key was revoked, expired, or the "
                    f"upstream account is no longer in good standing.\n\n"
                    f"To restore AI features, sign in to WrzDJ and rotate the "
                    f"credentials on your AI Settings page.\n\n"
                    f"If this looks wrong, you can re-test the connector from the "
                    f"same page — a successful test restores its status automatically.\n"
                ),
            }
        )
    except Exception as exc:
        _logger.error(
            "email.connector_auth_invalid_send_failed to_hash=%s error=%s",
            to_address[:3] + "***",
            exc,
        )
        raise EmailSendError(str(exc)) from exc

    _logger.info(
        "email.connector_auth_invalid_sent to_hash=%s connector_type=%s",
        to_address[:3] + "***",
        safe_type,
    )
