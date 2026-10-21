"""Deduplication helpers for the recommendation engine.

Prevents recommending tracks that are already requested, appear in the
template playlist, or were returned by multiple search queries.
"""

from __future__ import annotations

from app.models.request import Request
from app.services.track_normalizer import (
    artist_match_score,
    fuzzy_match_score,
    score_track_match,
)
from app.services.tracks.profile import TrackProfile


def deduplicate_against_requests(
    candidates: list[TrackProfile],
    existing_requests: list[Request],
) -> list[TrackProfile]:
    """Remove candidates that are already requested or are likely covers.

    Catches both exact duplicates (same title + artist) and cover/tribute
    versions where the title matches but the artist is different (e.g.,
    "Big" performing "Save A Horse" when "Big & Rich" already has it).
    """
    if not existing_requests:
        return candidates

    deduped = []
    for candidate in candidates:
        is_dupe = False
        is_cover = False
        for req in existing_requests:
            title_score = fuzzy_match_score(candidate.title, req.song_title)
            artist_score = artist_match_score(candidate.artist, req.artist)
            combined = score_track_match(title_score, artist_score)
            if combined >= 0.8:
                is_dupe = True
                break
            # Cover detection: same title but different artist
            if title_score >= 0.85 and artist_score < 0.6:
                is_cover = True
                break
        if not is_dupe and not is_cover:
            deduped.append(candidate)
    return deduped


def deduplicate_against_template(
    candidates: list[TrackProfile],
    template_tracks: list[TrackProfile],
) -> list[TrackProfile]:
    """Remove candidates that already appear in the template playlist."""
    if not template_tracks:
        return candidates

    deduped = []
    for candidate in candidates:
        is_dupe = False
        for tmpl in template_tracks:
            title_score = fuzzy_match_score(candidate.title, tmpl.title)
            artist_score = artist_match_score(candidate.artist, tmpl.artist)
            combined = score_track_match(title_score, artist_score)
            if combined >= 0.8:
                is_dupe = True
                break
        if not is_dupe:
            deduped.append(candidate)
    return deduped


def deduplicate_candidates(candidates: list[TrackProfile]) -> list[TrackProfile]:
    """Remove duplicate candidates (same track from different queries)."""
    seen: list[TrackProfile] = []
    for candidate in candidates:
        is_dupe = False
        for existing in seen:
            title_score = fuzzy_match_score(candidate.title, existing.title)
            artist_score = artist_match_score(candidate.artist, existing.artist)
            combined = score_track_match(title_score, artist_score)
            if combined >= 0.8:
                is_dupe = True
                break
        if not is_dupe:
            seen.append(candidate)
    return seen
