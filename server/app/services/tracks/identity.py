"""Canonical identities shared by track storage, imports, and matching."""

import hashlib

from app.services.track_normalizer import normalize_track


def dedupe_signature(artist: str, title: str) -> str:
    """Return the normalized artist/title hash used as the fuzzy dedupe key."""
    normalized_track = normalize_track(title, artist)
    normalized = (
        f"{normalized_track.artist.lower().strip()}:{normalized_track.title.lower().strip()}"
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]
