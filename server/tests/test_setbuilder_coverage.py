"""Pre-build pool coverage check (#542).

`pool_coverage` reports per-field completeness of the five required
pool→builder contract fields (bpm, key, genre, duration, energy) plus an
overall ready signal, so the build endpoint and the agent autobuild path can
surface a soft, overridable warning before generating a set.
"""

from app.models.set_pool import SetPoolTrack
from app.services.setbuilder.coverage import REQUIRED_FIELDS, pool_coverage


def _track(**kwargs) -> SetPoolTrack:
    """A detached pool track carrying only the fields under test."""
    base = dict(title="T", artist="A", dedupe_sig="sig")
    base.update(kwargs)
    return SetPoolTrack(**base)


class TestPoolCoverage:
    def test_empty_pool_is_ready_with_zero_tracks(self):
        cov = pool_coverage([])
        assert cov["pool_size"] == 0
        assert cov["fully_covered_count"] == 0
        assert cov["ready"] is True
        assert all(cov["missing"][f] == 0 for f in REQUIRED_FIELDS)

    def test_fully_enriched_pool_is_ready(self):
        tracks = [
            _track(bpm=124.0, camelot="8A", genre="House", duration_sec=200, energy=6),
            _track(bpm=126.0, camelot="9A", genre="Techno", duration_sec=210, energy=7),
        ]
        cov = pool_coverage(tracks)
        assert cov["pool_size"] == 2
        assert cov["fully_covered_count"] == 2
        assert cov["ready"] is True
        assert all(cov["missing"][f] == 0 for f in REQUIRED_FIELDS)

    def test_counts_each_missing_field(self):
        tracks = [
            _track(bpm=124.0, camelot="8A", genre="House", duration_sec=200, energy=6),
            _track(bpm=None, camelot="9A", genre=None, duration_sec=210, energy=None),
        ]
        cov = pool_coverage(tracks)
        assert cov["pool_size"] == 2
        assert cov["fully_covered_count"] == 1
        assert cov["missing"]["bpm"] == 1
        assert cov["missing"]["genre"] == 1
        assert cov["missing"]["energy"] == 1
        assert cov["missing"]["key"] == 0
        assert cov["missing"]["duration"] == 0
        assert cov["ready"] is False

    def test_raw_key_counts_as_keyed_when_no_camelot(self):
        # The builder reads `camelot or key`, so a raw `key` with no camelot still
        # counts as covered — mirror that here so coverage agrees with the engine.
        tracks = [_track(bpm=124.0, key="F minor", genre="House", duration_sec=200, energy=6)]
        cov = pool_coverage(tracks)
        assert cov["missing"]["key"] == 0
        assert cov["fully_covered_count"] == 1
        assert cov["ready"] is True

    def test_below_threshold_is_not_ready(self):
        # 1 of 4 fully covered = 25% < the 80% readiness threshold.
        tracks = [
            _track(bpm=124.0, camelot="8A", genre="House", duration_sec=200, energy=6),
            _track(bpm=None),
            _track(bpm=None),
            _track(bpm=None),
        ]
        cov = pool_coverage(tracks)
        assert cov["fully_covered_count"] == 1
        assert cov["ready"] is False
