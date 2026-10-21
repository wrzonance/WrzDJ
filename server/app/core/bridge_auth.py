"""API key authentication for StageLinQ bridge service."""

import logging
import secrets

from fastapi import Header, HTTPException

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def verify_bridge_api_key(x_bridge_api_key: str = Header(...)) -> None:
    """
    Verify the bridge API key from request header.

    Uses constant-time comparison to prevent timing attacks.
    Returns consistent 401 to prevent enumeration attacks.
    """
    settings = get_settings()

    # Check if key is configured and matches (consistent response for both failures)
    if not settings.bridge_api_key:
        logger.error("Bridge API key not configured - rejecting request")
        raise HTTPException(
            status_code=401,
            detail="Authentication failed",
        )

    # Use constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(x_bridge_api_key, settings.bridge_api_key):
        raise HTTPException(
            status_code=401,
            detail="Authentication failed",
        )
