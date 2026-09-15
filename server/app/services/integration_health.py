"""Integration health checking service.

Provides lightweight health checks for external service integrations.
CRITICAL: Never returns tokens, credentials, or secrets in responses.
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.integration_health import (
    CapabilityStatus,
    IntegrationServiceStatus,
    ServiceCapabilities,
)
from app.services.system_settings import get_system_settings

logger = logging.getLogger(__name__)

VALID_SERVICES = {"spotify", "tidal", "beatport", "bridge"}

_DISPLAY_NAMES = {
    "spotify": "Spotify",
    "tidal": "Tidal",
    "beatport": "Beatport",
    "bridge": "Bridge (DJ Equipment)",
}


def _check_spotify_capabilities() -> ServiceCapabilities:
    """Check Spotify integration via a lightweight search call."""
    settings = get_settings()
    has_credentials = bool(settings.spotify_client_id and settings.spotify_client_secret)

    if not has_credentials:
        return ServiceCapabilities(
            auth=CapabilityStatus.NOT_CONFIGURED,
            catalog_search=CapabilityStatus.NOT_CONFIGURED,
            playlist_sync=CapabilityStatus.NOT_IMPLEMENTED,
        )

    auth_status = CapabilityStatus.CONFIGURED
    search_status = CapabilityStatus.CONFIGURED
    try:
        from app.services.spotify import _get_spotify_client

        sp = _get_spotify_client()
        result = sp.search(q="test", type="track", limit=1)
        if result is not None:
            auth_status = CapabilityStatus.YES
            search_status = CapabilityStatus.YES
    except Exception as e:
        logger.warning("Spotify health check failed: %s", type(e).__name__)
        auth_status = CapabilityStatus.NO
        search_status = CapabilityStatus.NO

    return ServiceCapabilities(
        auth=auth_status,
        catalog_search=search_status,
        playlist_sync=CapabilityStatus.NOT_IMPLEMENTED,
    )


def _check_tidal_capabilities() -> ServiceCapabilities:
    """Check Tidal availability (per-user auth, system-level = library check)."""
    try:
        import tidalapi  # noqa: F401

        return ServiceCapabilities(
            auth=CapabilityStatus.CONFIGURED,
            catalog_search=CapabilityStatus.CONFIGURED,
            playlist_sync=CapabilityStatus.CONFIGURED,
        )
    except ImportError:
        return ServiceCapabilities(
            auth=CapabilityStatus.NOT_CONFIGURED,
            catalog_search=CapabilityStatus.NOT_CONFIGURED,
            playlist_sync=CapabilityStatus.NOT_CONFIGURED,
        )


def _check_beatport_capabilities() -> ServiceCapabilities:
    """Check Beatport configuration and API reachability."""
    settings = get_settings()
    has_client_id = bool(settings.beatport_client_id)

    if not has_client_id:
        return ServiceCapabilities(
            auth=CapabilityStatus.NOT_CONFIGURED,
            catalog_search=CapabilityStatus.NOT_CONFIGURED,
            playlist_sync=CapabilityStatus.NOT_CONFIGURED,
        )

    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            response = client.get(
                "https://api.beatport.com/v4/catalog/search/",
                params={"q": "test", "per_page": 1, "type": "tracks"},
            )
            if response.status_code in (200, 401, 403):
                auth_status = CapabilityStatus.CONFIGURED
            else:
                auth_status = CapabilityStatus.NO
    except Exception as e:
        logger.warning("Beatport reachability check failed: %s", type(e).__name__)
        auth_status = CapabilityStatus.NO

    return ServiceCapabilities(
        auth=auth_status,
        catalog_search=auth_status,
        playlist_sync=auth_status,
    )


def _check_bridge_capabilities() -> ServiceCapabilities:
    """Check Bridge API key configuration."""
    settings = get_settings()
    has_key = bool(settings.bridge_api_key)

    return ServiceCapabilities(
        auth=CapabilityStatus.CONFIGURED if has_key else CapabilityStatus.NOT_CONFIGURED,
        catalog_search=CapabilityStatus.NOT_IMPLEMENTED,
        playlist_sync=CapabilityStatus.NOT_IMPLEMENTED,
    )


_CAPABILITY_CHECKERS = {
    "spotify": _check_spotify_capabilities,
    "tidal": _check_tidal_capabilities,
    "beatport": _check_beatport_capabilities,
    "bridge": _check_bridge_capabilities,
}


def get_all_integration_statuses(db: Session) -> list[IntegrationServiceStatus]:
    """Get status of all integrations without triggering active health checks.

    Returns configuration state and enabled/disabled status.
    Does NOT make external API calls.
    """
    settings = get_settings()
    sys_settings = get_system_settings(db)

    enabled_map = {
        "spotify": sys_settings.spotify_enabled,
        "tidal": sys_settings.tidal_enabled,
        "beatport": sys_settings.beatport_enabled,
        "bridge": sys_settings.bridge_enabled,
    }

    configured_map = {
        "spotify": bool(settings.spotify_client_id and settings.spotify_client_secret),
        "tidal": True,  # tidalapi is always a dependency
        "beatport": bool(settings.beatport_client_id),
        "bridge": bool(settings.bridge_api_key),
    }

    results = []
    for service in ("spotify", "tidal", "beatport", "bridge"):
        configured = configured_map[service]
        is_search_capable = service not in ("bridge",)
        is_sync_capable = service not in ("spotify", "bridge")

        if not configured:
            capabilities = ServiceCapabilities(
                auth=CapabilityStatus.NOT_CONFIGURED,
                catalog_search=(
                    CapabilityStatus.NOT_CONFIGURED
                    if is_search_capable
                    else CapabilityStatus.NOT_IMPLEMENTED
                ),
                playlist_sync=(
                    CapabilityStatus.NOT_CONFIGURED
                    if is_sync_capable
                    else CapabilityStatus.NOT_IMPLEMENTED
                ),
            )
        else:
            capabilities = ServiceCapabilities(
                auth=CapabilityStatus.CONFIGURED,
                catalog_search=(
                    CapabilityStatus.CONFIGURED
                    if is_search_capable
                    else CapabilityStatus.NOT_IMPLEMENTED
                ),
                playlist_sync=(
                    CapabilityStatus.CONFIGURED
                    if is_sync_capable
                    else CapabilityStatus.NOT_IMPLEMENTED
                ),
            )

        results.append(
            IntegrationServiceStatus(
                service=service,
                display_name=_DISPLAY_NAMES[service],
                enabled=enabled_map[service],
                configured=configured,
                capabilities=capabilities,
            )
        )

    return results


def check_integration_health(
    db: Session, service: str
) -> tuple[bool, ServiceCapabilities, str | None]:
    """Run an active health check for a specific service.

    Makes lightweight external API calls to verify the service is reachable.
    Returns (healthy, capabilities, error_message).

    SECURITY: Never returns tokens or credentials.
    """
    checker = _CAPABILITY_CHECKERS.get(service)
    if not checker:
        return (
            False,
            ServiceCapabilities(
                auth=CapabilityStatus.NO,
                catalog_search=CapabilityStatus.NO,
                playlist_sync=CapabilityStatus.NO,
            ),
            f"Unknown service: {service}",
        )

    try:
        capabilities = checker()
        healthy = capabilities.auth in (CapabilityStatus.YES, CapabilityStatus.CONFIGURED)
        return healthy, capabilities, None
    except Exception as e:
        logger.error("Health check failed for %s: %s", service, type(e).__name__)
        error_msg = f"Health check failed: {type(e).__name__}"
        return (
            False,
            ServiceCapabilities(
                auth=CapabilityStatus.NO,
                catalog_search=CapabilityStatus.NO,
                playlist_sync=CapabilityStatus.NO,
            ),
            error_msg,
        )
