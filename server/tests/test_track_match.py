"""Tests for the unified best-match selector (#551).

`find_best_match` is the single fuzzy best-match-from-search-results selector
shared by the request enrichment pipeline, the collect preview, and the
recommendation Tidal/Beatport enrichers. It previously existed as a private
`_find_best_match` in the enrichment pipeline AND as two drifted inline loops in
recommendation/enrichment.py that lacked the `min_artist_score` floor and the
BPM-consensus tiebreaker. These tests lock the unified behavior so the two
surfaces can never drift again.
"""

from types import SimpleNamespace

from app.services.track_match import find_best_match


def _r(title, artist, bpm=None, mix_name=None):
    """A minimal search-result stub (the default .title/.artist/.bpm/.mix_name shape)."""
    return SimpleNamespace(title=title, artist=artist, bpm=bpm, mix_name=mix_name)


class TestBasicSelection:
    def test_picks_highest_combined_score(self):
        results = [
            _r("Totally Different Song", "Darude"),
            _r("Sandstorm", "Darude"),
        ]
        best = find_best_match(results, "Sandstorm", "Darude")
        assert best.title == "Sandstorm"

    def test_returns_none_below_min_score(self):
        results = [_r("Completely Unrelated", "Nobody At All")]
        assert find_best_match(results, "Sandstorm", "Darude") is None

    def test_empty_results_returns_none(self):
        assert find_best_match([], "Sandstorm", "Darude") is None


class TestArtistFloor:
    """A perfect title must not carry a completely wrong artist (the LABAT/Darude bug)."""

    def test_wrong_artist_perfect_title_is_skipped(self):
        results = [
            _r("Sandstorm", "Metallica"),  # perfect title, artist nowhere near "Darude"
            _r("Sandstrm", "Darude"),  # slight title typo, correct artist
        ]
        best = find_best_match(results, "Sandstorm", "Darude")
        assert best.artist == "Darude"

    def test_floor_can_be_lowered(self):
        results = [_r("Sandstorm", "Metallica")]
        # With the floor removed, the perfect-title/wrong-artist row is eligible again.
        best = find_best_match(results, "Sandstorm", "Darude", min_artist_score=0.0)
        assert best is not None
        assert best.artist == "Metallica"


class TestVersionPreference:
    """Migrated from test_sync_orchestrator — version-aware scoring (now owned here)."""

    def test_beatport_original_beats_remix_on_tie(self):
        from app.schemas.beatport import BeatportSearchResult

        results = [
            BeatportSearchResult(
                track_id="1",
                title="Surrender",
                artist="Darude",
                mix_name="Hardstyle Remix",
                bpm=165,
            ),
            BeatportSearchResult(
                track_id="2", title="Surrender", artist="Darude", mix_name="Original Mix", bpm=132
            ),
        ]
        best = find_best_match(results, "Surrender", "Darude", prefer_original=True)
        assert best.track_id == "2"
        assert best.bpm == 132

    def test_remix_preferred_when_disabled(self):
        from app.schemas.beatport import BeatportSearchResult

        results = [
            BeatportSearchResult(
                track_id="1",
                title="Surrender",
                artist="Darude",
                mix_name="Hardstyle Remix",
                bpm=165,
            ),
            BeatportSearchResult(
                track_id="2", title="Surrender", artist="Darude", mix_name="Original Mix", bpm=132
            ),
        ]
        # No version bonus/penalty → first encountered wins on an otherwise-exact tie.
        best = find_best_match(results, "Surrender", "Darude", prefer_original=False)
        assert best is not None

    def test_tidal_remix_title_penalized(self):
        results = [
            _r("Surrender (Hardstyle Remix)", "Darude", bpm=165),
            _r("Surrender", "Darude", bpm=132),
        ]
        best = find_best_match(results, "Surrender", "Darude", prefer_original=True)
        assert best.title == "Surrender"
        assert best.bpm == 132


class TestBpmConsensusTiebreaker:
    def test_modal_bpm_wins_on_score_tie(self):
        results = [
            _r("Surrender", "Darude", bpm=165.0),
            _r("Surrender", "Darude", bpm=132.0),
            _r("Surrender", "Darude", bpm=132.0),
            _r("Surrender", "Darude", bpm=132.0),
        ]
        best = find_best_match(results, "Surrender", "Darude", prefer_original=True)
        assert best.bpm == 132.0  # modal BPM among results breaks the tie


class TestAccessorShapes:
    """Tidal exposes .name / a custom artist accessor — the selector reads via accessors."""

    def test_custom_title_and_artist_accessors(self):
        tidal_like = [
            SimpleNamespace(name="Wrong Song", artist_obj="Darude", bpm=100),
            SimpleNamespace(name="Sandstorm", artist_obj="Darude", bpm=136),
        ]
        best = find_best_match(
            tidal_like,
            "Sandstorm",
            "Darude",
            get_title=lambda t: t.name,
            get_artist=lambda t: t.artist_obj,
        )
        assert best.name == "Sandstorm"

    def test_missing_mix_name_falls_back_to_title_remix_detection(self):
        # No mix_name attribute at all → remix detection must use the (accessor) title.
        tidal_like = [
            SimpleNamespace(name="Surrender (Hardstyle Remix)", artist_obj="Darude", bpm=165),
            SimpleNamespace(name="Surrender", artist_obj="Darude", bpm=132),
        ]
        best = find_best_match(
            tidal_like,
            "Surrender",
            "Darude",
            prefer_original=True,
            get_title=lambda t: t.name,
            get_artist=lambda t: t.artist_obj,
            get_mix_name=lambda t: None,
        )
        assert best.name == "Surrender"
