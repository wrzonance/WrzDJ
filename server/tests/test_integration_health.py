"""Tests for integration health service."""

from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.schemas.integration_health import CapabilityStatus, ServiceCapabilities
from app.services.integration_health import (
    VALID_SERVICES,
    check_integration_health,
    get_all_integration_statuses,
)


class TestGetAllIntegrationStatuses:
    def test_returns_all_four_services(self, db: Session):
        statuses = get_all_integration_statuses(db)
        service_names = {s.service for s in statuses}
        assert service_names == VALID_SERVICES

    def test_all_enabled_by_default(self, db: Session):
        statuses = get_all_integration_statuses(db)
        for s in statuses:
            assert s.enabled is True

    def test_display_names_present(self, db: Session):
        statuses = get_all_integration_statuses(db)
        for s in statuses:
            assert s.display_name
            assert len(s.display_name) > 0

    def test_bridge_has_not_implemented_capabilities(self, db: Session):
        statuses = get_all_integration_statuses(db)
        bridge = next(s for s in statuses if s.service == "bridge")
        assert bridge.capabilities.catalog_search == CapabilityStatus.NOT_IMPLEMENTED
        assert bridge.capabilities.playlist_sync == CapabilityStatus.NOT_IMPLEMENTED

    def test_spotify_playlist_sync_not_implemented(self, db: Session):
        statuses = get_all_integration_statuses(db)
        spotify = next(s for s in statuses if s.service == "spotify")
        assert spotify.capabilities.playlist_sync == CapabilityStatus.NOT_IMPLEMENTED

    @patch("app.services.integration_health.get_settings")
    def test_unconfigured_spotify(self, mock_settings, db: Session):
        mock_obj = MagicMock()
        mock_obj.spotify_client_id = ""
        mock_obj.spotify_client_secret = ""
        mock_obj.beatport_client_id = "test"
        mock_obj.bridge_api_key = "test"
        mock_settings.return_value = mock_obj

        statuses = get_all_integration_statuses(db)
        spotify = next(s for s in statuses if s.service == "spotify")
        assert spotify.configured is False
        assert spotify.capabilities.auth == CapabilityStatus.NOT_CONFIGURED

    @patch("app.services.integration_health.get_settings")
    def test_unconfigured_beatport(self, mock_settings, db: Session):
        mock_obj = MagicMock()
        mock_obj.spotify_client_id = "test"
        mock_obj.spotify_client_secret = "test"
        mock_obj.beatport_client_id = ""
        mock_obj.bridge_api_key = "test"
        mock_settings.return_value = mock_obj

        statuses = get_all_integration_statuses(db)
        beatport = next(s for s in statuses if s.service == "beatport")
        assert beatport.configured is False
        assert beatport.capabilities.auth == CapabilityStatus.NOT_CONFIGURED

    @patch("app.services.integration_health.get_settings")
    def test_unconfigured_bridge(self, mock_settings, db: Session):
        mock_obj = MagicMock()
        mock_obj.spotify_client_id = "test"
        mock_obj.spotify_client_secret = "test"
        mock_obj.beatport_client_id = "test"
        mock_obj.bridge_api_key = ""
        mock_settings.return_value = mock_obj

        statuses = get_all_integration_statuses(db)
        bridge = next(s for s in statuses if s.service == "bridge")
        assert bridge.configured is False
        assert bridge.capabilities.auth == CapabilityStatus.NOT_CONFIGURED

    def test_tidal_always_configured(self, db: Session):
        """Tidal uses per-user auth; tidalapi is always a dependency."""
        statuses = get_all_integration_statuses(db)
        tidal = next(s for s in statuses if s.service == "tidal")
        assert tidal.configured is True
        assert tidal.capabilities.auth == CapabilityStatus.CONFIGURED

    def test_tidal_has_all_capabilities(self, db: Session):
        statuses = get_all_integration_statuses(db)
        tidal = next(s for s in statuses if s.service == "tidal")
        assert tidal.capabilities.catalog_search == CapabilityStatus.CONFIGURED
        assert tidal.capabilities.playlist_sync == CapabilityStatus.CONFIGURED

    def test_no_tokens_in_response(self, db: Session):
        """SECURITY: Verify no token/credential data is returned."""
        statuses = get_all_integration_statuses(db)
        for s in statuses:
            serialized = s.model_dump_json()
            assert "secret" not in serialized.lower()
            assert "password" not in serialized.lower()

    def test_disabled_integration_reflected(self, db: Session):
        from app.services.system_settings import SystemSettingsPatch, update_system_settings

        update_system_settings(db, SystemSettingsPatch(spotify_enabled=False))
        statuses = get_all_integration_statuses(db)
        spotify = next(s for s in statuses if s.service == "spotify")
        assert spotify.enabled is False


class TestCheckIntegrationHealth:
    def test_unknown_service_returns_unhealthy(self, db: Session):
        healthy, _caps, error = check_integration_health(db, "nonexistent")
        assert healthy is False
        assert error is not None
        assert "Unknown" in error

    @patch("app.services.integration_health._CAPABILITY_CHECKERS")
    def test_spotify_healthy(self, mock_checkers, db: Session):
        expected_caps = ServiceCapabilities(
            auth=CapabilityStatus.YES,
            catalog_search=CapabilityStatus.YES,
            playlist_sync=CapabilityStatus.NOT_IMPLEMENTED,
        )
        mock_checkers.get = lambda svc: (lambda: expected_caps) if svc == "spotify" else None
        healthy, caps, error = check_integration_health(db, "spotify")
        assert healthy is True
        assert caps.auth == CapabilityStatus.YES
        assert error is None

    @patch("app.services.integration_health._CAPABILITY_CHECKERS")
    def test_spotify_unhealthy(self, mock_checkers, db: Session):
        def raise_error():
            raise Exception("Connection timeout")

        mock_checkers.get = lambda service: raise_error if service == "spotify" else None
        healthy, caps, error = check_integration_health(db, "spotify")
        assert healthy is False
        assert error is not None

    @patch("app.services.integration_health._CAPABILITY_CHECKERS")
    def test_tidal_configured_is_healthy(self, mock_checkers, db: Session):
        expected_caps = ServiceCapabilities(
            auth=CapabilityStatus.CONFIGURED,
            catalog_search=CapabilityStatus.CONFIGURED,
            playlist_sync=CapabilityStatus.CONFIGURED,
        )
        mock_checkers.get = lambda service: (lambda: expected_caps) if service == "tidal" else None
        healthy, _caps, error = check_integration_health(db, "tidal")
        assert healthy is True
        assert error is None

    def test_bridge_health_check(self, db: Session):
        healthy, caps, error = check_integration_health(db, "bridge")
        assert caps.catalog_search == CapabilityStatus.NOT_IMPLEMENTED
        assert caps.playlist_sync == CapabilityStatus.NOT_IMPLEMENTED
        assert error is None

    def test_valid_services_constant(self):
        assert "spotify" in VALID_SERVICES
        assert "tidal" in VALID_SERVICES
        assert "beatport" in VALID_SERVICES
        assert "bridge" in VALID_SERVICES
        assert len(VALID_SERVICES) == 4


class TestCheckSpotifyCapabilities:
    """Direct unit tests for _check_spotify_capabilities."""

    @patch("app.services.integration_health.get_settings")
    def test_unconfigured_returns_not_configured(self, mock_settings):
        mock_obj = MagicMock()
        mock_obj.spotify_client_id = ""
        mock_obj.spotify_client_secret = ""
        mock_settings.return_value = mock_obj

        from app.services.integration_health import _check_spotify_capabilities

        caps = _check_spotify_capabilities()
        assert caps.auth == CapabilityStatus.NOT_CONFIGURED
        assert caps.catalog_search == CapabilityStatus.NOT_CONFIGURED

    @patch("app.services.integration_health.get_settings")
    @patch("app.services.providers.spotify.get_spotify_client")
    def test_configured_and_search_success(self, mock_sp, mock_settings):
        mock_obj = MagicMock()
        mock_obj.spotify_client_id = "test_id"
        mock_obj.spotify_client_secret = "test_secret"
        mock_settings.return_value = mock_obj
        mock_sp.return_value.search.return_value = {"tracks": {"items": []}}

        from app.services.integration_health import _check_spotify_capabilities

        caps = _check_spotify_capabilities()
        assert caps.auth == CapabilityStatus.YES
        assert caps.catalog_search == CapabilityStatus.YES

    @patch("app.services.integration_health.get_settings")
    @patch("app.services.providers.spotify.get_spotify_client")
    def test_configured_but_search_exception(self, mock_sp, mock_settings):
        mock_obj = MagicMock()
        mock_obj.spotify_client_id = "test_id"
        mock_obj.spotify_client_secret = "test_secret"
        mock_settings.return_value = mock_obj
        mock_sp.side_effect = Exception("Connection refused")

        from app.services.integration_health import _check_spotify_capabilities

        caps = _check_spotify_capabilities()
        assert caps.auth == CapabilityStatus.NO
        assert caps.catalog_search == CapabilityStatus.NO


class TestCheckBeatportCapabilities:
    """Direct unit tests for _check_beatport_capabilities."""

    @patch("app.services.integration_health.get_settings")
    def test_unconfigured_returns_not_configured(self, mock_settings):
        mock_obj = MagicMock()
        mock_obj.beatport_client_id = ""
        mock_settings.return_value = mock_obj

        from app.services.integration_health import _check_beatport_capabilities

        caps = _check_beatport_capabilities()
        assert caps.auth == CapabilityStatus.NOT_CONFIGURED

    @patch("app.services.integration_health.get_settings")
    @patch("httpx.Client")
    def test_configured_api_reachable(self, mock_client_cls, mock_settings):
        mock_obj = MagicMock()
        mock_obj.beatport_client_id = "test_id"
        mock_settings.return_value = mock_obj

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from app.services.integration_health import _check_beatport_capabilities

        caps = _check_beatport_capabilities()
        assert caps.auth == CapabilityStatus.CONFIGURED

    @patch("app.services.integration_health.get_settings")
    @patch("httpx.Client")
    def test_configured_api_unreachable(self, mock_client_cls, mock_settings):
        mock_obj = MagicMock()
        mock_obj.beatport_client_id = "test_id"
        mock_settings.return_value = mock_obj

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Connection timeout")
        mock_client_cls.return_value = mock_client

        from app.services.integration_health import _check_beatport_capabilities

        caps = _check_beatport_capabilities()
        assert caps.auth == CapabilityStatus.NO


class TestCascadeIntegrationStatuses:
    """Cascade test: mixed service states."""

    @patch("app.services.integration_health.get_settings")
    def test_mixed_configured_and_unconfigured(self, mock_settings, db: Session):
        """Spotify unconfigured + Bridge configured → mixed results."""
        mock_obj = MagicMock()
        mock_obj.spotify_client_id = ""
        mock_obj.spotify_client_secret = ""
        mock_obj.beatport_client_id = ""
        mock_obj.bridge_api_key = "valid-key"
        mock_settings.return_value = mock_obj

        statuses = get_all_integration_statuses(db)
        spotify = next(s for s in statuses if s.service == "spotify")
        bridge = next(s for s in statuses if s.service == "bridge")

        assert spotify.configured is False
        assert bridge.configured is True
        assert spotify.capabilities.auth == CapabilityStatus.NOT_CONFIGURED
        assert bridge.capabilities.auth == CapabilityStatus.CONFIGURED
