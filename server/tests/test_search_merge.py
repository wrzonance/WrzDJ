"""Tests for unified search pipeline: convert, filter, deduplicate, and rank."""

from app.schemas.beatport import BeatportSearchResult
from app.schemas.search import SearchResult
from app.schemas.tidal import TidalSearchResult
from app.services.intent_parser import parse_intent
from app.services.search_merge import (
    _is_compilation,
    build_search_results,
    tidal_to_search_result,
)


def _tidal(
    title: str,
    artist: str,
    popularity: int = 50,
    isrc: str | None = None,
    bpm: float | None = None,
    key: str | None = None,
    version: str | None = None,
) -> TidalSearchResult:
    return TidalSearchResult(
        track_id=f"t_{title.lower().replace(' ', '_')}",
        title=title,
        artist=artist,
        album="Test Album",
        cover_url="https://img.tidal.com/test.jpg",
        tidal_url=f"https://tidal.com/browse/track/{title.lower().replace(' ', '-')}",
        popularity=popularity,
        isrc=isrc,
        bpm=bpm,
        key=key,
        version=version,
    )


def _spotify(
    title: str,
    artist: str,
    popularity: int = 50,
    isrc: str | None = None,
) -> SearchResult:
    return SearchResult(
        title=title,
        artist=artist,
        album="Test Album",
        popularity=popularity,
        spotify_id=f"sp_{title.lower().replace(' ', '_')}",
        source="spotify",
        isrc=isrc,
    )


def _beatport(
    title: str,
    artist: str,
    genre: str | None = None,
    bpm: int | None = None,
    key: str | None = None,
) -> BeatportSearchResult:
    return BeatportSearchResult(
        track_id=f"bp_{title.lower().replace(' ', '_')}",
        title=title,
        artist=artist,
        cover_url="https://img.beatport.com/test.jpg",
        beatport_url=f"https://www.beatport.com/track/{title.lower().replace(' ', '-')}/123",
        genre=genre,
        bpm=bpm,
        key=key,
    )


class TestBuildSearchResults:
    """Tests for the unified build_search_results() pipeline."""

    def test_tidal_only(self):
        """Tidal results are converted and returned."""
        tidal = [_tidal("Strobe", "deadmau5", popularity=80)]
        result = build_search_results(tidal_results=tidal)
        assert len(result) == 1
        assert result[0].source == "tidal"
        assert result[0].popularity == 80

    def test_spotify_fallback(self):
        """Spotify results work when Tidal is empty."""
        spotify = [_spotify("Strobe", "deadmau5", popularity=75)]
        result = build_search_results(spotify_results=spotify)
        assert len(result) == 1
        assert result[0].source == "spotify"

    def test_popularity_sorting(self):
        """Results are sorted by popularity DESC."""
        tidal = [
            _tidal("Low Pop", "Artist A", popularity=20),
            _tidal("High Pop", "Artist B", popularity=90),
            _tidal("Mid Pop", "Artist C", popularity=50),
        ]
        result = build_search_results(tidal_results=tidal)
        assert result[0].title == "High Pop"
        assert result[1].title == "Mid Pop"
        assert result[2].title == "Low Pop"

    def test_isrc_dedup_merges_tidal_and_spotify(self):
        """Same ISRC from Tidal and Spotify → single result with best metadata."""
        tidal = [_tidal("Strobe", "deadmau5", popularity=80, isrc="USRC12345", bpm=128)]
        spotify = [_spotify("Strobe", "deadmau5", popularity=75, isrc="USRC12345")]
        result = build_search_results(tidal_results=tidal, spotify_results=spotify)
        assert len(result) == 1
        # Higher popularity wins
        assert result[0].popularity == 80
        assert result[0].bpm == 128

    def test_isrc_dedup_merges_metadata(self):
        """ISRC merge fills missing metadata from the other copy."""
        tidal = [_tidal("Strobe", "deadmau5", popularity=80, isrc="USRC12345")]
        spotify = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                popularity=60,
                isrc="USRC12345",
                source="spotify",
                album_art="https://spotify.com/art.jpg",
            )
        ]
        result = build_search_results(tidal_results=tidal, spotify_results=spotify)
        assert len(result) == 1
        # Tidal has higher popularity, but Spotify had album art
        assert result[0].album_art in (
            "https://img.tidal.com/test.jpg",
            "https://spotify.com/art.jpg",
        )

    def test_junk_filter_rejects_workout(self):
        """Workout compilation titles are filtered out."""
        tidal = [
            _tidal("Strobe", "deadmau5", popularity=80),
            _tidal("Workout Electronica Mix Vol. 3", "Various Artists", popularity=60),
        ]
        result = build_search_results(tidal_results=tidal)
        assert len(result) == 1
        assert result[0].title == "Strobe"

    def test_junk_filter_rejects_cardio(self):
        """Cardio titles are filtered out."""
        tidal = [_tidal("Cardio Dance Party Hits", "Various Artists", popularity=40)]
        result = build_search_results(tidal_results=tidal)
        assert len(result) == 0

    def test_junk_filter_rejects_karaoke_version(self):
        """Karaoke versions are filtered out via version_filter."""
        tidal = [_tidal("Strobe (Karaoke Version)", "deadmau5", popularity=20)]
        result = build_search_results(tidal_results=tidal)
        assert len(result) == 0

    def test_junk_filter_rejects_pt_series(self):
        """Pt. N series indicators are filtered."""
        tidal = [_tidal("Electronic Hits Pt. 30", "Various", popularity=30)]
        result = build_search_results(tidal_results=tidal)
        assert len(result) == 0

    def test_junk_filter_respects_intent_live(self):
        """When user searches for 'live', live versions are NOT filtered."""
        tidal = [_tidal("Strobe (Live)", "deadmau5", popularity=60)]
        intent = parse_intent("strobe live")
        result = build_search_results(tidal_results=tidal, intent=intent)
        assert len(result) == 1
        assert result[0].title == "Strobe (Live)"

    def test_beatport_bypasses_junk_filter(self):
        """Beatport results are NOT junk-filtered (DJ-curated catalog)."""
        beatport = [_beatport("Workout Bass", "DJ Pierre", genre="House", bpm=126)]
        result = build_search_results(beatport_results=beatport)
        assert len(result) == 1

    def test_beatport_appended_after_main(self):
        """Unique Beatport tracks appear after main results."""
        tidal = [_tidal("Strobe", "deadmau5", popularity=80)]
        beatport = [_beatport("Acid Phase", "DJ Pierre")]
        result = build_search_results(tidal_results=tidal, beatport_results=beatport)
        assert len(result) == 2
        assert result[0].source == "tidal"
        assert result[1].source == "beatport"

    def test_beatport_deduped_against_main(self):
        """Beatport duplicate of main result is removed."""
        tidal = [_tidal("Strobe", "deadmau5", popularity=80)]
        beatport = [_beatport("Strobe", "deadmau5")]
        result = build_search_results(tidal_results=tidal, beatport_results=beatport)
        assert len(result) == 1
        assert result[0].source == "tidal"

    def test_max_beatport_extras(self):
        """Beatport extras capped at max_beatport_extras."""
        # Use very distinct names to avoid fuzzy dedup
        names = [
            ("Acid Phase", "DJ Pierre"),
            ("Strobe", "deadmau5"),
            ("Levels", "Avicii"),
            ("Titanium", "David Guetta"),
            ("Sandstorm", "Darude"),
            ("Blue Monday", "New Order"),
            ("Born Slippy", "Underworld"),
            ("Insomnia", "Faithless"),
            ("Papua New Guinea", "Future Sound"),
            ("Windowlicker", "Aphex Twin"),
        ]
        beatport = [_beatport(t, a) for t, a in names]
        result = build_search_results(beatport_results=beatport, max_beatport_extras=3)
        assert len(result) == 3

    def test_beatport_metadata_preserved(self):
        """Beatport genre/bpm/key pass through to merged SearchResult."""
        beatport = [_beatport("Acid Phase", "DJ Pierre", genre="Acid House", bpm=126, key="Fm")]
        result = build_search_results(beatport_results=beatport)
        assert result[0].genre == "Acid House"
        assert result[0].bpm == 126
        assert result[0].key == "Fm"

    def test_fuzzy_dedup_within_main(self):
        """Fuzzy dedup removes near-duplicate titles within main results."""
        tidal = [
            _tidal("Strobe", "deadmau5", popularity=80),
            _tidal("Strobe (Original Mix)", "deadmau5", popularity=70),
        ]
        result = build_search_results(tidal_results=tidal, dedup_threshold=0.6)
        assert len(result) == 1
        assert result[0].popularity == 80

    def test_fuzzy_dedup_keeps_most_popular_track_across_providers(self):
        """Popularity ranking selects the representative before fuzzy dedup."""
        tidal = [_tidal("Strobe", "deadmau5", popularity=10)]
        spotify = [_spotify("Strobe", "deadmau5", popularity=90)]

        result = build_search_results(tidal_results=tidal, spotify_results=spotify)

        assert len(result) == 1
        assert result[0].title == "Strobe"
        assert result[0].source == "spotify"
        assert result[0].popularity == 90

    def test_isrc_dedup_keeps_tidal_on_equal_popularity_and_merges_metadata(self):
        """Exact ISRC matches retain Tidal-first tie handling and fill metadata."""
        tidal = [_tidal("Strobe", "deadmau5", popularity=75, isrc="USRC12345")]
        spotify = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                popularity=75,
                isrc="USRC12345",
                source="spotify",
                bpm=128,
            )
        ]

        result = build_search_results(tidal_results=tidal, spotify_results=spotify)

        assert len(result) == 1
        assert result[0].source == "tidal"
        assert result[0].popularity == 75
        assert result[0].bpm == 128

    def test_empty_inputs(self):
        """All empty inputs returns empty list."""
        result = build_search_results()
        assert result == []

    def test_tidal_converts_bpm(self):
        """Tidal BPM float is converted to int in SearchResult."""
        tidal = [_tidal("Test", "Artist", bpm=128.5)]
        result = build_search_results(tidal_results=tidal)
        assert result[0].bpm == 128

    def test_tidal_isrc_carried_through(self):
        """Tidal ISRC is preserved in converted SearchResult."""
        tidal = [_tidal("Test", "Artist", isrc="USRC99999")]
        result = build_search_results(tidal_results=tidal)
        assert result[0].isrc == "USRC99999"

    def test_junk_filter_rejects_tribute(self):
        """Tribute album titles are filtered."""
        tidal = [_tidal("Tribute to Deadmau5", "Tribute Band", popularity=10)]
        result = build_search_results(tidal_results=tidal)
        assert len(result) == 0

    def test_junk_filter_rejects_dj_mix(self):
        """DJ Mix compilation titles are filtered."""
        tidal = [_tidal("Ministry of Sound DJ Mix 2026", "Various", popularity=40)]
        result = build_search_results(tidal_results=tidal)
        assert len(result) == 0


class TestIsCompilation:
    """Tests for the _is_compilation helper."""

    def test_workout(self):
        assert _is_compilation("Workout Dance Hits 2026") is True

    def test_cardio(self):
        assert _is_compilation("Cardio Electronica Mix") is True

    def test_tribute(self):
        assert _is_compilation("Tribute to Daft Punk") is True

    def test_pt_series(self):
        assert _is_compilation("Deep House Sessions Pt. 42") is True

    def test_dj_mix(self):
        assert _is_compilation("Summer DJ Mix") is True

    def test_normal_title(self):
        assert _is_compilation("Strobe") is False

    def test_normal_title_with_parens(self):
        assert _is_compilation("Strobe (Extended Mix)") is False

    def test_megamix(self):
        assert _is_compilation("80s Non-Stop Mix") is True


class TestTidalToSearchResult:
    """Tests for tidal_to_search_result conversion."""

    def test_converts_popularity(self):
        t = _tidal("Strobe", "deadmau5", popularity=85)
        result = tidal_to_search_result(t)
        assert result.popularity == 85

    def test_converts_isrc(self):
        t = _tidal("Strobe", "deadmau5", isrc="USRC12345")
        result = tidal_to_search_result(t)
        assert result.isrc == "USRC12345"
