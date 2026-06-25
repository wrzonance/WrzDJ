"""Unit tests for the WrzDJSet pool service + public-URL validator (issue #388)."""

import pytest
from sqlalchemy.orm import Session

from app.api import setbuilder as setbuilder_api
from app.models.request import Request, RequestStatus
from app.models.set import Set
from app.models.set_pool import SetPoolTrack
from app.models.user import User
from app.services.setbuilder import pool
from app.services.setbuilder.playlist_url import (
    InvalidPlaylistUrl,
    parse_public_playlist_url,
)


@pytest.fixture
def test_set(db: Session, test_user: User) -> Set:
    s = Set(owner_id=test_user.id, name="Pool Test Set")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _candidate(title: str, artist: str, **kwargs) -> pool.PoolCandidate:
    return pool.PoolCandidate(title=title, artist=artist, **kwargs)


class TestPoolRuntime:
    """Total pool runtime surfaced before generation (#538)."""

    def _add_track(self, db, set_obj, source, idx, **kw):
        from app.models.set_pool import SetPoolTrack

        defaults = dict(
            set_id=set_obj.id,
            source_id=source.id,
            track_id=f"tidal:{idx}",
            title=f"T{idx}",
            artist=f"A{idx}",
            duration_sec=240,
            dedupe_sig=f"sig-{idx}",
        )
        defaults.update(kw)
        row = SetPoolTrack(**defaults)
        db.add(row)
        db.commit()
        return row

    def test_runtime_sums_durations(self, db: Session, test_set: Set):
        src = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        for idx in range(3):
            self._add_track(db, test_set, src, idx, duration_sec=240)

        assert pool.pool_runtime_sec(db, test_set.id) == 720

    def test_runtime_uses_avg_fallback_for_missing_duration(self, db: Session, test_set: Set):
        from app.services.setbuilder.pass1_deterministic import AVG_TRACK_LENGTH_SEC

        src = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        self._add_track(db, test_set, src, 0, duration_sec=240)
        self._add_track(db, test_set, src, 1, duration_sec=None)
        self._add_track(db, test_set, src, 2, duration_sec=0)

        # 240 + two fallbacks (None and the non-positive 0 both use the avg).
        assert pool.pool_runtime_sec(db, test_set.id) == 240 + 2 * AVG_TRACK_LENGTH_SEC

    def test_runtime_empty_pool_is_zero(self, db: Session, test_set: Set):
        assert pool.pool_runtime_sec(db, test_set.id) == 0


class TestDedupeSignature:
    def test_strips_generic_mix_suffix(self):
        assert pool.dedupe_signature("Artist", "Song (Original Mix)") == pool.dedupe_signature(
            "Artist", "Song"
        )

    def test_canonicalizes_feat(self):
        assert pool.dedupe_signature("A feat. B", "Song") == pool.dedupe_signature(
            "A featuring B", "Song"
        )

    def test_case_insensitive(self):
        assert pool.dedupe_signature("ARTIST", "SONG") == pool.dedupe_signature("artist", "song")

    def test_distinct_tracks_differ(self):
        assert pool.dedupe_signature("Artist", "Song A") != pool.dedupe_signature(
            "Artist", "Song B"
        )


class TestCamelotCode:
    def test_major_key(self):
        assert pool.camelot_code("C major") == "8B"

    def test_camelot_passthrough(self):
        assert pool.camelot_code("8A") == "8A"

    def test_none(self):
        assert pool.camelot_code(None) is None

    def test_unparseable(self):
        assert pool.camelot_code("not a key") is None


class TestSources:
    def test_get_or_create_source_creates(self, db, test_set):
        src = pool.get_or_create_source(
            db, test_set, kind="tidal", external_ref="pl-1", label="My Playlist"
        )
        assert src.id is not None
        assert src.kind == "tidal"

    def test_get_or_create_source_reuses_row(self, db, test_set):
        a = pool.get_or_create_source(
            db, test_set, kind="tidal", external_ref="pl-1", label="My Playlist"
        )
        b = pool.get_or_create_source(
            db, test_set, kind="tidal", external_ref="pl-1", label="My Playlist (renamed)"
        )
        assert a.id == b.id
        assert b.label == "My Playlist (renamed)"

    def test_manual_bucket_is_singleton_per_set(self, db, test_set):
        a = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        b = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        assert a.id == b.id


class TestImportCandidates:
    def test_imports_and_counts(self, db, test_set):
        src = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        added, deduped = pool.import_candidates(
            db,
            test_set,
            src,
            [
                _candidate("Song A", "Artist 1", key="C major", bpm=124.0),
                _candidate("Song B", "Artist 2"),
            ],
        )
        assert (added, deduped) == (2, 0)
        _, tracks = pool.get_pool(db, test_set.id)
        assert len(tracks) == 2
        assert tracks[0].camelot == "8B"
        assert tracks[0].source_id == src.id

    def test_fuzzy_dedupe_preserves_first_source_tag(self, db, test_set):
        src1 = pool.get_or_create_source(
            db, test_set, kind="event", external_ref="1", label="Event"
        )
        src2 = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        pool.import_candidates(db, test_set, src1, [_candidate("Song A", "Artist")])
        added, deduped = pool.import_candidates(
            db, test_set, src2, [_candidate("Song A (Original Mix)", "Artist")]
        )
        assert (added, deduped) == (0, 1)
        _, tracks = pool.get_pool(db, test_set.id)
        assert len(tracks) == 1
        assert tracks[0].source_id == src1.id

    def test_isrc_dedupe_with_different_titles(self, db, test_set):
        src = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        pool.import_candidates(
            db, test_set, src, [_candidate("Song A", "Artist", isrc="USUM71703861")]
        )
        added, deduped = pool.import_candidates(
            db, test_set, src, [_candidate("Totally Different Name", "Artist", isrc="usum71703861")]
        )
        assert (added, deduped) == (0, 1)

    def test_reimport_same_source_zero_added(self, db, test_set):
        src = pool.get_or_create_source(db, test_set, kind="tidal", external_ref="p", label="P")
        cands = [_candidate("Song A", "Artist"), _candidate("Song B", "Artist")]
        pool.import_candidates(db, test_set, src, cands)
        added, deduped = pool.import_candidates(db, test_set, src, cands)
        assert (added, deduped) == (0, 2)

    def test_blank_candidates_skipped(self, db, test_set):
        src = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        added, deduped = pool.import_candidates(
            db, test_set, src, [_candidate("", " "), _candidate("Real", "Artist")]
        )
        assert (added, deduped) == (1, 0)

    def test_intra_batch_dedupe(self, db, test_set):
        src = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        added, deduped = pool.import_candidates(
            db, test_set, src, [_candidate("Song A", "Artist"), _candidate("Song A", "Artist")]
        )
        assert (added, deduped) == (1, 1)

    def test_import_marks_complete_tracks_enriched_and_gaps_pending(self, db, test_set):
        src = pool.get_or_create_source(
            db, test_set, kind="tidal", external_ref="p", label="Playlist"
        )
        pool.import_candidates(
            db,
            test_set,
            src,
            [
                _candidate(
                    "Complete",
                    "Artist",
                    bpm=126.0,
                    key="8A",
                    genre="House",
                    duration_sec=300,
                ),
                _candidate("Gap", "Artist"),
            ],
        )

        _, tracks = pool.get_pool(db, test_set.id)
        by_title = {track.title: track for track in tracks}
        assert by_title["Complete"].enrichment_status == "enriched"
        assert by_title["Gap"].enrichment_status == "pending"

    def test_pool_state_includes_enrichment_summary(self, db, test_set):
        src = pool.get_or_create_source(
            db, test_set, kind="manual", external_ref=None, label="Manual"
        )
        db.add_all(
            [
                SetPoolTrack(
                    set_id=test_set.id,
                    source_id=src.id,
                    title="Pending",
                    artist="Artist",
                    dedupe_sig="pending",
                    enrichment_status="pending",
                ),
                SetPoolTrack(
                    set_id=test_set.id,
                    source_id=src.id,
                    title="Enriched",
                    artist="Artist",
                    dedupe_sig="enriched",
                    enrichment_status="enriched",
                ),
                SetPoolTrack(
                    set_id=test_set.id,
                    source_id=src.id,
                    title="Failed",
                    artist="Artist",
                    dedupe_sig="failed",
                    enrichment_status="failed",
                ),
            ]
        )
        db.commit()

        state = setbuilder_api._pool_state(db, test_set.id)

        assert state.enrichment.total == 3
        assert state.enrichment.enriched == 1
        assert state.enrichment.failed == 1
        assert state.enrichment.pending == 1
        assert state.enrichment.in_progress is True


class TestRemoval:
    def test_remove_tracks_scoped_to_set(self, db, test_user, test_set):
        other_set = Set(owner_id=test_user.id, name="Other")
        db.add(other_set)
        db.commit()
        src_a = pool.get_or_create_source(db, test_set, kind="manual", external_ref=None, label="M")
        src_b = pool.get_or_create_source(
            db, other_set, kind="manual", external_ref=None, label="M"
        )
        pool.import_candidates(db, test_set, src_a, [_candidate("Song A", "Artist")])
        pool.import_candidates(db, other_set, src_b, [_candidate("Song B", "Artist")])
        _, other_tracks = pool.get_pool(db, other_set.id)
        removed = pool.remove_tracks(db, test_set, [t.id for t in other_tracks])
        assert removed == 0
        _, still_there = pool.get_pool(db, other_set.id)
        assert len(still_there) == 1

    def test_remove_source_removes_exactly_its_tracks(self, db, test_set):
        src1 = pool.get_or_create_source(db, test_set, kind="tidal", external_ref="p1", label="P1")
        src2 = pool.get_or_create_source(
            db, test_set, kind="beatport", external_ref="p2", label="P2"
        )
        pool.import_candidates(
            db, test_set, src1, [_candidate("Song A", "Artist"), _candidate("Song B", "Artist")]
        )
        pool.import_candidates(db, test_set, src2, [_candidate("Song C", "Artist")])
        removed = pool.remove_source(db, test_set, src1)
        assert removed == 2
        sources, tracks = pool.get_pool(db, test_set.id)
        assert [s.id for s in sources] == [src2.id]
        assert len(tracks) == 1
        assert tracks[0].title == "Song C"


class TestEventCandidates:
    def test_maps_requests_excluding_rejected(self, db, test_user, test_event):
        db.add_all(
            [
                Request(
                    event_id=test_event.id,
                    song_title="Keep Me",
                    artist="Artist",
                    dedupe_key="k1",
                    genre="House",
                    bpm=126.0,
                    musical_key="8A",
                ),
                Request(
                    event_id=test_event.id,
                    song_title="Rejected",
                    artist="Artist",
                    dedupe_key="k2",
                    status=RequestStatus.REJECTED.value,
                ),
            ]
        )
        db.commit()
        result = pool.candidates_from_event(db, test_user, test_event.id)
        assert result is not None
        event, cands = result
        assert event.id == test_event.id
        assert [c.title for c in cands] == ["Keep Me"]
        assert cands[0].track_id.startswith("request:")
        assert cands[0].genre == "House"

    def test_unowned_event_returns_none(self, db, test_user, test_event):
        from app.services.auth import get_password_hash

        other = User(username="other", password_hash=get_password_hash("x" * 12), role="dj")
        db.add(other)
        db.commit()
        assert pool.candidates_from_event(db, other, test_event.id) is None


class TestUrlParser:
    def test_spotify_playlist(self):
        p = parse_public_playlist_url("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        assert (p.provider, p.supported) == ("spotify", True)
        assert p.playlist_id == "37i9dQZF1DXcBWIGoYBM5M"

    def test_spotify_with_query(self):
        p = parse_public_playlist_url(
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123"
        )
        assert p.playlist_id == "37i9dQZF1DXcBWIGoYBM5M"

    def test_tidal_browse_playlist(self):
        p = parse_public_playlist_url(
            "https://tidal.com/browse/playlist/12345678-90ab-cdef-1234-567890abcdef"
        )
        assert (p.provider, p.supported) == ("tidal", True)
        assert p.playlist_id == "12345678-90ab-cdef-1234-567890abcdef"

    def test_listen_tidal_playlist(self):
        p = parse_public_playlist_url(
            "https://listen.tidal.com/playlist/12345678-90ab-cdef-1234-567890abcdef"
        )
        assert (p.provider, p.supported) == ("tidal", True)

    def test_apple_music_recognized_unsupported(self):
        p = parse_public_playlist_url("https://music.apple.com/us/playlist/top-hits/pl.abc123DEF")
        assert (p.provider, p.supported) == ("apple_music", False)
        assert p.message

    def test_youtube_recognized_unsupported(self):
        p = parse_public_playlist_url("https://www.youtube.com/playlist?list=PLabc_123-xyz")
        assert (p.provider, p.supported) == ("youtube", False)

    def test_soundcloud_recognized_unsupported(self):
        p = parse_public_playlist_url("https://soundcloud.com/some-dj/sets/some-playlist")
        assert (p.provider, p.supported) == ("soundcloud", False)

    def test_beatport_recognized_unsupported(self):
        p = parse_public_playlist_url("https://www.beatport.com/playlists/123456")
        assert (p.provider, p.supported) == ("beatport", False)

    @pytest.mark.parametrize(
        "url",
        [
            "http://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",  # not https
            "https://evil.com/playlist/37i9dQZF1DXcBWIGoYBM5M",  # bad host
            "https://open.spotify.com@evil.com/playlist/37i9dQZF1DXcBWIGoYBM5M",  # userinfo
            "https://open.spotify.com:8443/playlist/37i9dQZF1DXcBWIGoYBM5M",  # port
            "https://open.spotify.com/playlist/../../etc/passwd",  # bad id charset
            "https://open.spotify.com/track/37i9dQZF1DXcBWIGoYBM5M",  # not a playlist
            "javascript:alert(1)",
            "ftp://tidal.com/browse/playlist/12345678-90ab-cdef-1234-567890abcdef",
            "not a url at all",
            "https://tidal.com/browse/playlist/not-a-uuid",
        ],
    )
    def test_rejected_urls(self, url):
        with pytest.raises(InvalidPlaylistUrl):
            parse_public_playlist_url(url)


class TestPlaylistCandidates:
    def test_tidal_candidates_mapped(self, db, test_user, monkeypatch):
        from app.schemas.tidal import TidalSearchResult

        class FakeTrack:
            pass

        def fake_get_playlist_tracks(db_, user, playlist_id):
            return [FakeTrack()]

        def fake_track_to_result(t):
            return TidalSearchResult(
                track_id="999",
                title="Tidal Song",
                artist="Tidal Artist",
                album="Album",
                bpm=128.0,
                key="Am",
                duration_seconds=200,
                cover_url="https://resources.tidal.com/x.jpg",
                isrc="QZABC1234567",
            )

        monkeypatch.setattr("app.services.tidal.get_playlist_tracks", fake_get_playlist_tracks)
        monkeypatch.setattr("app.services.tidal._track_to_result", fake_track_to_result)
        cands = pool.candidates_from_tidal(db, test_user, "pl-1")
        assert len(cands) == 1
        assert cands[0].track_id == "tidal:999"
        assert cands[0].isrc == "QZABC1234567"

    def test_beatport_candidates_mapped(self, db, test_user, monkeypatch):
        from app.schemas.beatport import BeatportSearchResult

        def fake_get_playlist_tracks(db_, user, playlist_id):
            return [
                BeatportSearchResult(
                    track_id="42",
                    title="Beat Song",
                    artist="Beat Artist",
                    mix_name="Club Mix",
                    genre="Tech House",
                    bpm=127,
                    key="5A",
                    duration_seconds=300,
                )
            ]

        monkeypatch.setattr("app.services.beatport.get_playlist_tracks", fake_get_playlist_tracks)
        cands = pool.candidates_from_beatport(db, test_user, "42")
        assert len(cands) == 1
        assert cands[0].track_id == "beatport:42"
        assert cands[0].title == "Beat Song (Club Mix)"
        assert cands[0].genre == "Tech House"
