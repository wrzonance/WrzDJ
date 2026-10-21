"""Focused tests for sync orchestration."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.sync.enrichment_pipeline import _extract_source_track_id, _get_isrc_from_spotify
from tests.sync_orchestrator_fixtures import (
    MockAdapter,  # noqa: F401
    _fixture_accepted_request,  # noqa: F401
    _fixture_accepted_request_no_query,  # noqa: F401
    _fixture_clean_registry,  # noqa: F401
    _fixture_tidal_event,  # noqa: F401
    _fixture_tidal_user,  # noqa: F401
    _make_accepted_request,  # noqa: F401
)


class TestExtractSourceTrackId:
    """Tests for _extract_source_track_id()."""

    def test_spotify_url(self):
        svc, tid = _extract_source_track_id("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
        assert svc == "spotify"
        assert tid == "4uLU6hMCjMI75M1A2tKUQC"

    def test_beatport_url(self):
        svc, tid = _extract_source_track_id(
            "https://www.beatport.com/track/the-house-of-house/12345"
        )
        assert svc == "beatport"
        assert tid == "12345"

    def test_tidal_url(self):
        svc, tid = _extract_source_track_id("https://tidal.com/browse/track/67890")
        assert svc == "tidal"
        assert tid == "67890"

    def test_tidal_url_no_browse(self):
        svc, tid = _extract_source_track_id("https://tidal.com/track/99999")
        assert svc == "tidal"
        assert tid == "99999"

    def test_none_url(self):
        svc, tid = _extract_source_track_id(None)
        assert svc is None
        assert tid is None

    def test_non_music_url(self):
        svc, tid = _extract_source_track_id("https://example.com/page")
        assert svc is None
        assert tid is None

    def test_empty_string(self):
        svc, tid = _extract_source_track_id("")
        assert svc is None
        assert tid is None


class TestGetIsrcFromSpotify:
    """Tests for _get_isrc_from_spotify()."""

    def test_returns_isrc_for_spotify_url(self):
        with patch(
            "app.services.providers.spotify.get_spotify_client",
        ) as mock_client:
            mock_client.return_value.track.return_value = {
                "external_ids": {"isrc": "USRC11700041"},
            }
            isrc = _get_isrc_from_spotify("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
            assert isrc == "USRC11700041"
            mock_client.return_value.track.assert_called_once_with("4uLU6hMCjMI75M1A2tKUQC")

    def test_returns_none_for_non_spotify_url(self):
        isrc = _get_isrc_from_spotify("https://tidal.com/browse/track/123")
        assert isrc is None

    def test_api_error_log_is_correlated_and_redacted(self, caplog):
        source_url = "https://open.spotify.com/track/abc123?access_token=private-token"
        with patch(
            "app.services.providers.spotify.get_spotify_client",
            side_effect=RuntimeError("provider echoed private-token"),
        ):
            isrc = _get_isrc_from_spotify(source_url, request_id=781)

        assert isrc is None
        assert "781" in caplog.text
        assert "RuntimeError" in caplog.text
        assert "private-token" not in caplog.text
        assert "open.spotify.com" not in caplog.text
        assert "provider echoed" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)

    def test_returns_none_for_none_url(self):
        assert _get_isrc_from_spotify(None) is None


class TestSourceProviderFailureLogs:
    def test_direct_provider_failures_log_only_request_and_exception_class(
        self, monkeypatch, caplog
    ):
        from app.services.sync.source_resolution import (
            resolve_direct_source_track,
            resolve_spotify_isrc_and_tidal_match,
        )

        request = SimpleNamespace(id=781, bpm=None, musical_key=None, source_url=None)
        user = SimpleNamespace(beatport_access_token="credential", tidal_access_token="credential")
        logger = logging.getLogger("app.services.sync.source_resolution")

        for provider, track_id, patch_target in (
            (
                "beatport",
                "beatport-track",
                "app.services.providers.beatport_catalog.get_beatport_track",
            ),
            ("tidal", "tidal-track", "app.services.providers.tidal_search.get_tidal_track_by_id"),
        ):
            caplog.clear()
            monkeypatch.setattr(
                patch_target, Mock(side_effect=RuntimeError("credential=private-value"))
            )
            result = resolve_direct_source_track(
                None,
                request,
                user=user,
                source_svc=provider,
                source_track_id=track_id,
                resolved_isrc="existing-isrc",
                logger=logger,
            )
            assert result.isrc == "existing-isrc"
            assert "781" in caplog.text
            assert "RuntimeError" in caplog.text
            assert "private-value" not in caplog.text
            assert all(record.exc_info is None for record in caplog.records)

        caplog.clear()
        monkeypatch.setattr(
            "app.services.providers.tidal_search.search_tidal_by_isrc",
            Mock(side_effect=RuntimeError("credential=private-value")),
        )
        result = resolve_spotify_isrc_and_tidal_match(
            None,
            request,
            user=user,
            source_svc="spotify",
            resolved_isrc="USABC1234567",
            settings_provider=lambda: SimpleNamespace(soundcharts_audio_features_enabled=False),
            isrc_resolver=lambda *_args, **_kwargs: None,
            logger=logger,
        )
        assert result.isrc == "USABC1234567"
        assert "781" in caplog.text
        assert "RuntimeError" in caplog.text
        assert "private-value" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)


class TestSourceResolutionResults:
    def test_direct_resolution_returns_provenance_without_mutating_request(self, monkeypatch):
        from app.services.sync.source_resolution import (
            SourceResolutionResult,
            resolve_direct_source_track,
        )

        request = SimpleNamespace(id=781, bpm=None, musical_key=None, genre=None, source_url=None)
        user = SimpleNamespace(beatport_access_token="credential", tidal_access_token=None)
        track = SimpleNamespace(
            title="Test Track",
            bpm=124,
            key="A Minor",
            genre="House",
            isrc="USABC1234567",
        )
        monkeypatch.setattr(
            "app.services.providers.beatport_catalog.get_beatport_track",
            Mock(return_value=track),
        )

        result = resolve_direct_source_track(
            None,
            request,
            user=user,
            source_svc="beatport",
            source_track_id="42",
            resolved_isrc=None,
            logger=logging.getLogger(__name__),
        )

        assert isinstance(result, SourceResolutionResult)
        assert result.isrc == "USABC1234567"
        assert {name: (field.value, field.source) for name, field in result.fields.items()} == {
            "bpm": (124.0, "beatport"),
            "musical_key": ("8A", "beatport"),
            "genre": ("House", "beatport"),
        }
        assert request.bpm is None
        assert request.musical_key is None
        assert request.genre is None
