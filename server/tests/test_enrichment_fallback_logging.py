"""Safe, contextual logging for best-effort enrichment fallbacks."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.services.sync.enrichment_pipeline import (
    _backfill_energy_for_cached,
    _enrich_beatport,
    _enrich_musicbrainz_genre,
    _enrich_tidal,
    _resolve_soundcharts_audio_features,
    _safe_upsert_track,
)
from app.services.tracks.store import TrackIdentity

_PRIVATE_ERROR = "provider failed: https://private.invalid/?token=DO_NOT_LOG"
_REQUEST_ID = 731


def _request():
    return SimpleNamespace(
        id=_REQUEST_ID,
        artist="Test Artist",
        song_title="Test Song",
        source_url=None,
        genre=None,
        bpm=None,
        musical_key=None,
    )


@pytest.mark.parametrize(
    "provider",
    ["musicbrainz", "beatport", "tidal", "soundcharts", "soundcharts_backfill"],
)
def test_provider_failure_keeps_fallback_and_logs_only_safe_context(provider, caplog):
    request = _request()
    resolved = {}
    error = RuntimeError(_PRIVATE_ERROR)
    user = SimpleNamespace(
        beatport_access_token="private-beatport-token", tidal_access_token="private-tidal-token"
    )
    with caplog.at_level(logging.WARNING, logger="app.services.sync.enrichment_pipeline"):
        if provider == "musicbrainz":
            with patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre", side_effect=error
            ):
                _enrich_musicbrainz_genre(request, resolved)
        elif provider == "beatport":
            with patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks", side_effect=error
            ):
                _enrich_beatport(
                    Mock(),
                    request,
                    user=user,
                    search_query="Test Song Test Artist",
                    prefer_original=False,
                    resolved=resolved,
                    resolved_isrc=None,
                )
        elif provider == "tidal":
            with patch(
                "app.services.providers.tidal_search.search_tidal_tracks", side_effect=error
            ):
                _enrich_tidal(
                    Mock(),
                    request,
                    user=user,
                    search_query="Test Song Test Artist",
                    prefer_original=False,
                    resolved=resolved,
                    resolved_isrc=None,
                )
        elif provider == "soundcharts":
            with (
                patch(
                    "app.services.sync.enrichment_pipeline.get_settings",
                    return_value=SimpleNamespace(soundcharts_audio_features_enabled=True),
                ),
                patch(
                    "app.services.providers.soundcharts.get_song_features_by_isrc",
                    side_effect=error,
                ),
            ):
                assert (
                    _resolve_soundcharts_audio_features(
                        request, resolved=resolved, resolved_isrc="USABC1234567", cached=None
                    )
                    is None
                )
        else:
            cached = SimpleNamespace(isrc="USABC1234567", energy=None)
            with patch(
                "app.services.providers.soundcharts.get_song_features_by_isrc", side_effect=error
            ):
                _backfill_energy_for_cached(Mock(), request, cached, "signature")

    assert request.genre is None
    assert request.bpm is None
    assert request.musical_key is None
    assert resolved == {}
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    warning = warnings[0]
    assert str(_REQUEST_ID) in warning.getMessage()
    assert "RuntimeError" in warning.getMessage()
    assert _PRIVATE_ERROR not in warning.getMessage()
    assert "private-beatport-token" not in warning.getMessage()
    assert "private-tidal-token" not in warning.getMessage()
    assert warning.exc_info is None


def test_track_store_failure_logs_exception_type_without_losing_request_context(caplog):
    db = Mock()
    error = RuntimeError(_PRIVATE_ERROR)
    with caplog.at_level(logging.WARNING, logger="app.services.sync.enrichment_pipeline"):
        with patch("app.services.sync.enrichment_pipeline.upsert_track", side_effect=error):
            _safe_upsert_track(
                db,
                identity=TrackIdentity(title="Test Song", artist="Test Artist", signature="sig"),
                values={"genre": "house"},
                sources={"genre": "musicbrainz"},
                request_id=_REQUEST_ID,
            )

    assert db.commit.call_count == 1
    db.rollback.assert_called_once()
    warning = next(record for record in caplog.records if record.levelno == logging.WARNING)
    assert str(_REQUEST_ID) in warning.getMessage()
    assert "RuntimeError" in warning.getMessage()
    assert _PRIVATE_ERROR not in warning.getMessage()
    assert warning.exc_info is None
