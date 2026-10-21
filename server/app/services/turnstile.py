"""Cloudflare Turnstile CAPTCHA verification."""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# SECURITY (H-A6): explicit timeout prevents Cloudflare outages from
# hanging uvicorn workers indefinitely.
TURNSTILE_TIMEOUT_SECONDS = 10.0


async def verify_turnstile_token(token: str, remote_ip: str | None = None) -> bool:
    """Verify a Turnstile token with Cloudflare.

    Returns True if valid, False otherwise.
    Skips verification in dev if no secret key is configured.
    """
    settings = get_settings()

    if not settings.turnstile_secret_key:
        if settings.is_production:
            # Reject registration when CAPTCHA is not configured in production
            return False
        # No key configured — skip verification (dev mode)
        return True

    data = {
        "secret": settings.turnstile_secret_key,
        "response": token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=TURNSTILE_TIMEOUT_SECONDS) as client:
            resp = await client.post(VERIFY_URL, data=data)
            result = resp.json()
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.warning("Turnstile verification failed: %s", type(exc).__name__)
        return False
    except (ValueError, KeyError):
        logger.warning("Turnstile returned malformed response")
        return False

    if not isinstance(result, dict):
        logger.warning("Turnstile returned malformed response")
        return False

    success = result.get("success") is True
    if not success:
        logger.warning(
            "Turnstile verification rejected: error-codes=%s",
            result.get("error-codes"),
        )
    return success
