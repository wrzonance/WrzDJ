"""Tests for MusicBrainz artist verification batch service."""

from datetime import timedelta
from unittest.mock import patch

from app.core.time import utcnow
from app.models.mb_artist_cache import MbArtistCache
from app.services.recommendation.mb_verify import (
    CACHE_TTL_DAYS,
    LB_MIN_USER_COUNT,
    verify_artists_batch,
)


class TestVerifyArtistsBatch:
    def test_empty_input_returns_empty(self, db):
        result = verify_artists_batch(db, [])
        assert result == {}

    def test_blank_names_ignored(self, db):
        result = verify_artists_batch(db, ["", "  "])
        assert result == {}

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_calls_api_for_uncached_artist(self, mock_check, db):
        mock_check.return_value = (True, "mbid-123")

        result = verify_artists_batch(db, ["Radiohead"])

        assert result == {"Radiohead": True}
        mock_check.assert_called_once_with("radiohead")

        # Verify cache entry was created
        cached = db.query(MbArtistCache).filter_by(artist_name="radiohead").first()
        assert cached is not None
        assert cached.verified is True
        assert cached.mbid == "mbid-123"

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_returns_cached_result_without_api_call(self, mock_check, db):
        # Pre-populate cache
        db.add(MbArtistCache(artist_name="radiohead", mbid="mbid-123", verified=True))
        db.commit()

        result = verify_artists_batch(db, ["Radiohead"])

        assert result == {"Radiohead": True}
        mock_check.assert_not_called()

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_caches_negative_result(self, mock_check, db):
        mock_check.return_value = (False, None)

        result = verify_artists_batch(db, ["AI Generated Music"])

        assert result == {"AI Generated Music": False}

        # Negative result should be cached too
        cached = db.query(MbArtistCache).filter_by(artist_name="ai generated music").first()
        assert cached is not None
        assert cached.verified is False
        assert cached.mbid is None

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_deduplicates_artist_names(self, mock_check, db):
        mock_check.return_value = (True, "mbid-456")

        result = verify_artists_batch(db, ["deadmau5", "Deadmau5", "DEADMAU5"])

        # All three map to the same normalized name, only one API call
        mock_check.assert_called_once_with("deadmau5")
        assert result["deadmau5"] is True
        assert result["Deadmau5"] is True
        assert result["DEADMAU5"] is True

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_mixed_cached_and_uncached(self, mock_check, db):
        # Pre-populate one entry
        db.add(MbArtistCache(artist_name="radiohead", mbid="mbid-1", verified=True))
        db.commit()

        mock_check.return_value = (True, "mbid-2")

        result = verify_artists_batch(db, ["Radiohead", "Daft Punk"])

        assert result["Radiohead"] is True
        assert result["Daft Punk"] is True
        # Only Daft Punk should trigger an API call
        mock_check.assert_called_once_with("daft punk")

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_multiple_uncached_artists(self, mock_check, db):
        mock_check.side_effect = [
            (True, "mbid-a"),
            (False, None),
            (True, "mbid-c"),
        ]

        result = verify_artists_batch(db, ["Artist A", "Artist B", "Artist C"])

        assert result["Artist A"] is True
        assert result["Artist B"] is False
        assert result["Artist C"] is True
        assert mock_check.call_count == 3

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_expired_cache_triggers_reverification(self, mock_check, db):
        """Stale cache entries (older than TTL) should be re-verified via API."""
        expired_time = utcnow() - timedelta(days=CACHE_TTL_DAYS + 1)
        db.add(
            MbArtistCache(
                artist_name="electrofab music",
                mbid=None,
                verified=True,
                created_at=expired_time,
            )
        )
        db.commit()

        # Now-fixed API correctly rejects this fake artist
        mock_check.return_value = (False, None)

        result = verify_artists_batch(db, ["Electrofab Music"])

        assert result["Electrofab Music"] is False
        mock_check.assert_called_once_with("electrofab music")

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_expired_cache_upserts_existing_row(self, mock_check, db):
        """Re-verification of expired entry updates the existing row, not a duplicate."""
        expired_time = utcnow() - timedelta(days=CACHE_TTL_DAYS + 1)
        db.add(
            MbArtistCache(
                artist_name="fake artist",
                mbid=None,
                verified=True,
                created_at=expired_time,
            )
        )
        db.commit()

        mock_check.return_value = (False, None)
        verify_artists_batch(db, ["Fake Artist"])

        # Should have exactly one row (updated), not two
        rows = db.query(MbArtistCache).filter_by(artist_name="fake artist").all()
        assert len(rows) == 1
        assert rows[0].verified is False
        # created_at should be refreshed (newer than the expired time)
        assert rows[0].created_at > expired_time

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    def test_fresh_cache_still_served(self, mock_check, db):
        """Cache entries within TTL should still be served without API calls."""
        fresh_time = utcnow() - timedelta(days=CACHE_TTL_DAYS - 1)
        db.add(
            MbArtistCache(
                artist_name="radiohead",
                mbid="mbid-123",
                verified=True,
                created_at=fresh_time,
                lb_user_count=500,
            )
        )
        db.commit()

        result = verify_artists_batch(db, ["Radiohead"])

        assert result["Radiohead"] is True
        mock_check.assert_not_called()


class TestListenBrainzGate:
    """Tests for the ListenBrainz popularity gate integration."""

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    @patch("app.services.providers.listenbrainz.fetch_artist_popularity")
    def test_lb_backfill_only_for_verified_with_mbid_and_no_lb_data(self, mock_lb, mock_check, db):
        """LB backfill should only query artists that are verified, have mbid, and no lb data."""
        mock_check.return_value = (True, "mbid-real")
        mock_lb.return_value = {
            "mbid-real": {"total_listen_count": 5000, "total_user_count": 100},
        }

        verify_artists_batch(db, ["Real Artist"])

        mock_lb.assert_called_once_with(["mbid-real"])

        # Verify LB data was cached
        cached = db.query(MbArtistCache).filter_by(artist_name="real artist").first()
        assert cached.lb_user_count == 100
        assert cached.lb_listen_count == 5000

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    @patch("app.services.providers.listenbrainz.fetch_artist_popularity")
    def test_lb_failure_passes_through(self, mock_lb, mock_check, db):
        """LB API failure → lb_user_count stays None → artist passes through."""
        mock_check.return_value = (True, "mbid-123")
        mock_lb.return_value = {}  # API failure returns empty

        result = verify_artists_batch(db, ["Some Artist"])

        assert result["Some Artist"] is True  # Passes through

        cached = db.query(MbArtistCache).filter_by(artist_name="some artist").first()
        assert cached.lb_user_count is None  # Not set

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    @patch("app.services.providers.listenbrainz.fetch_artist_popularity")
    def test_lb_zero_listeners_rejects(self, mock_lb, mock_check, db):
        """Artist confirmed with 0 LB listeners should be rejected."""
        mock_check.return_value = (True, "mbid-stock")
        mock_lb.return_value = {}  # MBID not in response

        result = verify_artists_batch(db, ["Stock Producer"])

        # First call: LB returns empty → skip backfill (pass through)
        assert result["Stock Producer"] is True

        # But on a SECOND call after LB data is stored as 0...
        cached = db.query(MbArtistCache).filter_by(artist_name="stock producer").first()
        # Manually simulate the case where LB returned data but this MBID was absent
        # (the code stores 0 for MBIDs not in LB response when LB did return data)
        cached.lb_user_count = 0
        cached.lb_listen_count = 0
        db.commit()

        result2 = verify_artists_batch(db, ["Stock Producer"])
        assert result2["Stock Producer"] is False

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    @patch("app.services.providers.listenbrainz.fetch_artist_popularity")
    def test_lb_below_threshold_rejects(self, mock_lb, mock_check, db):
        """Artist with lb_user_count below threshold should be rejected."""
        mock_check.return_value = (True, "mbid-low")
        mock_lb.return_value = {
            "mbid-low": {"total_listen_count": 10, "total_user_count": LB_MIN_USER_COUNT - 1},
        }

        result = verify_artists_batch(db, ["Low Pop Artist"])

        assert result["Low Pop Artist"] is False

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    @patch("app.services.providers.listenbrainz.fetch_artist_popularity")
    def test_lb_at_threshold_passes(self, mock_lb, mock_check, db):
        """Artist with lb_user_count exactly at threshold should pass."""
        mock_check.return_value = (True, "mbid-ok")
        mock_lb.return_value = {
            "mbid-ok": {"total_listen_count": 50, "total_user_count": LB_MIN_USER_COUNT},
        }

        result = verify_artists_batch(db, ["OK Artist"])

        assert result["OK Artist"] is True

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    @patch("app.services.providers.listenbrainz.fetch_artist_popularity")
    def test_cached_lb_data_not_refetched(self, mock_lb, mock_check, db):
        """Artists with existing lb_user_count should not trigger LB API calls."""
        db.add(
            MbArtistCache(
                artist_name="radiohead",
                mbid="mbid-rh",
                verified=True,
                lb_user_count=50000,
                lb_listen_count=1000000,
            )
        )
        db.commit()

        result = verify_artists_batch(db, ["Radiohead"])

        assert result["Radiohead"] is True
        mock_lb.assert_not_called()
        mock_check.assert_not_called()

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    @patch("app.services.providers.listenbrainz.fetch_artist_popularity")
    def test_unverified_artists_skip_lb(self, mock_lb, mock_check, db):
        """Artists that failed MB verification should not be queried against LB."""
        mock_check.return_value = (False, None)

        result = verify_artists_batch(db, ["Fake Artist"])

        assert result["Fake Artist"] is False
        mock_lb.assert_not_called()

    @patch("app.services.recommendation.mb_verify.check_artist_exists")
    @patch("app.services.providers.listenbrainz.fetch_artist_popularity")
    def test_mbid_absent_from_lb_response_stores_zero(self, mock_lb, mock_check, db):
        """MBIDs present in request but absent from LB response should get 0 stored."""
        mock_check.return_value = (True, "mbid-unknown")
        # LB returns data for a different MBID (simulating partial response)
        mock_lb.return_value = {
            "mbid-other": {"total_listen_count": 100, "total_user_count": 50},
        }

        result = verify_artists_batch(db, ["Unknown LB Artist"])

        # Should be rejected (0 < LB_MIN_USER_COUNT)
        assert result["Unknown LB Artist"] is False

        cached = db.query(MbArtistCache).filter_by(artist_name="unknown lb artist").first()
        assert cached.lb_user_count == 0
        assert cached.lb_listen_count == 0
