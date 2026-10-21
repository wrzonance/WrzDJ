"""Recommendation scoring test builder."""

from app.services.tracks.profile import TrackProfile


def _make_scored(title, artist, score, bpm_score=0.5, key_score=0.5, genre_score=0.5):
    """Helper to create a ScoredTrack for diversity tests."""
    from app.services.recommendation.scorer import ScoredTrack

    return ScoredTrack(
        profile=TrackProfile(title=title, artist=artist),
        score=score,
        bpm_score=bpm_score,
        key_score=key_score,
        genre_score=genre_score,
    )
