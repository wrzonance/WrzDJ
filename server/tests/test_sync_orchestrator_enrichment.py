"""Focused tests for sync orchestration."""

from unittest.mock import patch

from app.models.request import RequestStatus
from app.services.sync.orchestrator import (
    enrich_request_metadata,
)
from tests.sync_orchestrator_fixtures import (
    MockAdapter,  # noqa: F401
    _fixture_accepted_request,  # noqa: F401
    _fixture_accepted_request_no_query,  # noqa: F401
    _fixture_clean_registry,  # noqa: F401
    _fixture_tidal_event,  # noqa: F401
    _fixture_tidal_user,  # noqa: F401
    _make_accepted_request,  # noqa: F401
)


class TestEnrichRequestMetadata:
    """Tests for enrich_request_metadata background task."""

    def test_skips_when_all_metadata_present(self, db, tidal_event):
        """Requests with genre, bpm, and key are skipped entirely."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Test Artist", "enrich_skip")
        request.genre = "country"
        request.bpm = 120.0
        request.musical_key = "8A"
        db.commit()

        enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "country"
        assert request.bpm == 120.0
        assert request.musical_key == "8A"

    def test_skips_nonexistent_request(self, db):
        """Non-existent request ID is a no-op."""
        enrich_request_metadata(db, 999999)  # Should not raise

    def test_musicbrainz_fills_genre_first(self, db, tidal_event):
        """MusicBrainz is tried first for genre (before Beatport)."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Radiohead", "enrich_mb")
        db.commit()

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value="alternative rock",
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "alternative rock"

    def test_musicbrainz_skipped_when_genre_present(self, db, tidal_event):
        """MusicBrainz is not called when genre already exists."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Artist", "enrich_mb_skip")
        request.genre = "country"
        db.commit()

        with patch("app.services.sync.enrichment_pipeline.lookup_artist_genre") as mock_mb:
            enrich_request_metadata(db, request.id)
            mock_mb.assert_not_called()

    def test_beatport_fills_bpm_key_and_backfills_genre(self, db, tidal_event, tidal_user):
        """Beatport fills BPM/key (and genre when MusicBrainz missed)."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "enrich_bp")
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        mock_results = [
            BeatportSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                genre="Progressive House",
                bpm=128,
                key="F Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "Progressive House"  # Backfilled by Beatport
        assert request.bpm == 128.0
        assert request.musical_key == "4A"  # F Minor -> 4A in Camelot

    def test_beatport_skips_genre_when_musicbrainz_filled(self, db, tidal_event, tidal_user):
        """Beatport doesn't overwrite genre already set by MusicBrainz."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "enrich_bp_nogenre")
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        mock_results = [
            BeatportSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                genre="Progressive House",
                bpm=128,
                key="F Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value="electronic",
        ):
            with patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "electronic"  # MusicBrainz's genre kept
        assert request.bpm == 128.0  # Beatport's BPM used
        assert request.musical_key == "4A"  # Beatport's key used

    def test_tidal_fills_bpm_key_when_beatport_missing(self, db, tidal_event, tidal_user):
        """Tidal provides BPM/key when Beatport is not connected."""
        # User has Tidal but no Beatport
        assert tidal_user.beatport_access_token is None

        request = _make_accepted_request(db, tidal_event, "Test Song", "Artist", "enrich_tidal")
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        mock_results = [
            TidalSearchResult(
                track_id="999",
                title="Test Song",
                artist="Artist",
                bpm=120.0,
                key="D Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value="pop",
        ):
            with patch(
                "app.services.providers.tidal_search.search_tidal_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "pop"  # From MusicBrainz
        assert request.bpm == 120.0  # From Tidal
        assert request.musical_key == "7A"  # D Minor -> 7A from Tidal

    def test_tidal_skipped_when_beatport_filled_bpm_key(self, db, tidal_event, tidal_user):
        """Tidal is not called when Beatport already provided BPM + key."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "enrich_skip_tidal")
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        mock_bp_results = [
            BeatportSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                genre="Progressive House",
                bpm=128,
                key="F Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks",
                return_value=mock_bp_results,
            ):
                with patch(
                    "app.services.providers.tidal_search.search_tidal_tracks",
                ) as mock_tidal:
                    enrich_request_metadata(db, request.id)
                    mock_tidal.assert_not_called()

    def test_tidal_enrichment_failure_is_graceful(self, db, tidal_event, tidal_user):
        """Tidal enrichment exceptions don't crash the task."""
        request = _make_accepted_request(db, tidal_event, "Song", "Artist", "enrich_tidal_fail")
        db.commit()

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.providers.tidal_search.search_tidal_tracks",
                side_effect=RuntimeError("Tidal API down"),
            ):
                enrich_request_metadata(db, request.id)  # Should not raise

        db.refresh(request)
        assert request.bpm is None  # Gracefully degraded

    def test_normalizes_key_from_enrichment(self, db, tidal_event):
        """Musical key from enrichment is normalized to Camelot notation."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Artist", "enrich_key_norm")
        request.musical_key = "D Minor"
        db.commit()

        enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.musical_key == "7A"  # D Minor = 7A

    def test_musicbrainz_failure_is_graceful(self, db, tidal_event):
        """MusicBrainz exceptions don't crash the enrichment task."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Artist", "enrich_mb_fail")
        db.commit()

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            side_effect=RuntimeError("Network error"),
        ):
            enrich_request_metadata(db, request.id)  # Should not raise

        db.refresh(request)
        assert request.genre is None  # Gracefully degraded

    def test_beatport_enrichment_skips_non_matching_results(self, db, tidal_event, tidal_user):
        """Beatport results that don't match the requested song are skipped."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(
            db, tidal_event, "Feel The Beat", "Darude", "enrich_no_match"
        )
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        # Beatport returns a totally different track first
        mock_results = [
            BeatportSearchResult(
                track_id="999",
                title="Wrong Song",
                artist="Wrong Artist",
                genre="Techno",
                bpm=72,
                key="A Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.bpm is None  # Should NOT take 72 BPM from wrong track
        assert request.genre is None
        assert request.musical_key is None

    def test_tidal_enrichment_skips_non_matching_results(self, db, tidal_event, tidal_user):
        """Tidal results that don't match the requested song are skipped."""
        request = _make_accepted_request(
            db, tidal_event, "Feel The Beat", "Darude", "enrich_tidal_no_match"
        )
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        mock_results = [
            TidalSearchResult(
                track_id="999",
                title="Totally Different Track",
                artist="Some Other Artist",
                bpm=72.0,
                key="C Major",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.providers.tidal_search.search_tidal_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.bpm is None  # Should NOT take BPM from wrong track
        assert request.musical_key is None

    def test_beatport_enrichment_rejects_same_title_wrong_artist(self, db, tidal_event, tidal_user):
        """Beatport result with matching title but wrong artist is rejected.

        Real-world case: searching "Darude Feel The Beat" returns
        "Feel the Beat" by LB aka LABAT (72 BPM) as the first result.
        The title matches perfectly but the artist is completely different.
        """
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(
            db, tidal_event, "Feel The Beat", "Darude", "enrich_wrong_artist"
        )
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        mock_results = [
            BeatportSearchResult(
                track_id="16190399",
                title="Feel the Beat",
                artist="LB aka LABAT",
                genre="House",
                bpm=72,
                key="Gb Major",
            ),
            BeatportSearchResult(
                track_id="13280071",
                title="Darude",
                artist="Victor Vandale",
                genre="Techno (Peak Time / Driving)",
                bpm=124,
                key="F# Minor",
            ),
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.bpm is None  # Must NOT take 72 BPM from LB aka LABAT
        assert request.genre is None  # Must NOT take "House" from wrong track
        assert request.musical_key is None

    def test_bpm_context_excludes_new_requests(self, db, tidal_event, tidal_user):
        """BPM context correction should only use accepted/played/playing requests."""
        # Create accepted requests with BPMs to form context (median ~130)
        for i, bpm_val in enumerate([128.0, 130.0, 132.0]):
            r = _make_accepted_request(db, tidal_event, f"Track {i}", f"Artist {i}", f"bpm_ctx_{i}")
            r.status = RequestStatus.ACCEPTED.value
            r.bpm = bpm_val
        db.commit()

        # Create a NEW request with BPM that should NOT be in context
        new_req = _make_accepted_request(db, tidal_event, "Troll Track", "Troll", "bpm_ctx_new")
        new_req.status = RequestStatus.NEW.value
        new_req.bpm = 200.0  # Would skew median if included
        db.commit()

        # Create the request to enrich — 65 BPM should double to 130
        # (within 15% of median 130). Leave musical_key=None so we don't
        # hit the "already complete" early-return.
        target = _make_accepted_request(
            db, tidal_event, "Half Time Track", "Artist", "bpm_ctx_target"
        )
        target.genre = "electronic"
        target.bpm = 65.0
        db.commit()

        # Mock external services to avoid network calls (Tidal fills missing key)
        with patch(
            "app.services.providers.tidal_search.search_tidal_tracks",
            return_value=[],
        ):
            enrich_request_metadata(db, target.id)

        db.refresh(target)
        # With status filter: median = 130, 65*2 = 130 → corrected
        # Without status filter: median would include 200, skewing context
        assert target.bpm == 130.0


class TestDirectFetchEnrichment:
    """Tests for source URL direct fetch in enrich_request_metadata."""

    def test_direct_beatport_enrichment(self, db, tidal_event, tidal_user):
        """Beatport source URL triggers direct fetch, skipping fuzzy search."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(
            db, tidal_event, "The House of House", "Cherrymoon Trax", "enrich_bp_direct"
        )
        request.source_url = "https://www.beatport.com/track/the-house-of-house/99999"
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        direct_track = BeatportSearchResult(
            track_id="99999",
            title="The House Of House",
            artist="Cherrymoon Trax",
            genre="Trance",
            bpm=132,
            key="A Minor",
            mix_name="Original Mix",
        )

        with (
            patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre",
                return_value=None,
            ),
            patch(
                "app.services.providers.beatport_catalog.get_beatport_track",
                return_value=direct_track,
            ) as mock_direct,
            patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks",
                return_value=[],
            ),
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        # Direct fetch should have been called with the extracted track ID
        mock_direct.assert_called_once_with(db, tidal_user, "99999")
        assert request.bpm == 132.0
        assert request.genre == "Trance"

    def test_isrc_tidal_enrichment(self, db, tidal_event, tidal_user):
        """Spotify source URL triggers ISRC lookup → exact Tidal match."""
        request = _make_accepted_request(
            db, tidal_event, "The House of House", "Cherrymoon Trax", "enrich_isrc"
        )
        request.source_url = "https://open.spotify.com/track/abc123"
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        isrc_match = TidalSearchResult(
            track_id="777",
            title="The House Of House",
            artist="Cherrymoon Trax",
            bpm=132.0,
            key="A Minor",
        )

        with (
            patch(
                "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
                return_value="NLRD19800001",
            ),
            patch(
                "app.services.providers.tidal_search.search_tidal_by_isrc",
                return_value=isrc_match,
            ) as mock_isrc,
            patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre",
                return_value="trance",
            ),
            patch(
                "app.services.providers.tidal_search.search_tidal_tracks",
                return_value=[],
            ),
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        mock_isrc.assert_called_once_with(db, tidal_user, "NLRD19800001")
        assert request.bpm == 132.0  # From ISRC match, not fuzzy search
        assert request.genre == "trance"  # From MusicBrainz

    def test_isrc_fallback_to_fuzzy_when_no_match(self, db, tidal_event, tidal_user):
        """When ISRC returns no Tidal match, falls through to fuzzy search."""
        request = _make_accepted_request(
            db, tidal_event, "Test Song", "Test Artist", "enrich_isrc_fallback"
        )
        request.source_url = "https://open.spotify.com/track/xyz789"
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        fuzzy_result = TidalSearchResult(
            track_id="888",
            title="Test Song",
            artist="Test Artist",
            bpm=120.0,
            key="C Major",
        )

        with (
            patch(
                "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
                return_value="TEST12345678",
            ),
            patch(
                "app.services.providers.tidal_search.search_tidal_by_isrc",
                return_value=None,
            ),
            patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre",
                return_value=None,
            ),
            patch(
                "app.services.providers.tidal_search.search_tidal_tracks",
                return_value=[fuzzy_result],
            ),
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        # Should have fallen through to fuzzy Tidal search
        assert request.bpm == 120.0

    def test_direct_tidal_enrichment(self, db, tidal_event, tidal_user):
        """Tidal source URL triggers direct fetch by track ID."""
        request = _make_accepted_request(
            db, tidal_event, "Test Song", "Test Artist", "enrich_tidal_direct"
        )
        request.source_url = "https://tidal.com/browse/track/55555"
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        direct_track = TidalSearchResult(
            track_id="55555",
            title="Test Song",
            artist="Test Artist",
            bpm=140.0,
            key="D Minor",
        )

        with (
            patch(
                "app.services.providers.tidal_search.get_tidal_track_by_id",
                return_value=direct_track,
            ) as mock_direct,
            patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre",
                return_value=None,
            ),
            patch(
                "app.services.providers.tidal_search.search_tidal_tracks",
                return_value=[],
            ),
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        mock_direct.assert_called_once_with(db, tidal_user, "55555")
        assert request.bpm == 140.0
