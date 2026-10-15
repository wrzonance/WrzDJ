"""Apple Music catalog search and playlist-track resolution."""

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import apple_music_accounts, apple_music_tokens
from app.services.setbuilder.export_common import ExportTrack
from app.services.track_normalizer import artist_match_score, fuzzy_match_score
from app.services.version_filter import is_unwanted_version

MIN_TITLE_SIMILARITY = 0.85
MIN_ARTIST_SIMILARITY = 0.85
MATCH_THRESHOLD = 0.88
_STOREFRONT_RE = re.compile(r"^[a-z]{2}$")
_APPLE_MUSIC_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _apple_music_id(track: ExportTrack) -> str | None:
    """Return a validated Apple Music catalog ID from a matching namespace."""
    if not track.track_id or not track.track_id.startswith("apple_music:"):
        return None
    value = track.track_id.removeprefix("apple_music:")
    return value if _APPLE_MUSIC_ID_RE.fullmatch(value) else None


@dataclass(frozen=True)
class AppleCatalogSong:
    id: str
    title: str
    artist: str
    isrc: str | None


def _parse_songs(payload: dict[str, object]) -> list[AppleCatalogSong]:
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    songs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        attributes = item.get("attributes")
        if not isinstance(attributes, dict):
            continue
        song_id = item.get("id")
        title = attributes.get("name")
        artist = attributes.get("artistName")
        if (
            not isinstance(song_id, str)
            or not isinstance(title, str)
            or not isinstance(artist, str)
        ):
            continue
        isrc = attributes.get("isrc")
        songs.append(
            AppleCatalogSong(
                id=song_id,
                title=title,
                artist=artist,
                isrc=isrc if isinstance(isrc, str) else None,
            )
        )
    return songs


def search_catalog(
    _db: Session,
    storefront: str,
    term: str,
    *,
    isrc: str | None = None,
    song_id: str | None = None,
) -> list[AppleCatalogSong]:
    """Search Apple Music by ID, ISRC, or title and artist in one DJ storefront."""
    if not _STOREFRONT_RE.fullmatch(storefront):
        return []
    developer_token, _ = apple_music_tokens.create_developer_token()
    if song_id:
        payload = apple_music_tokens.apple_get(
            f"/catalog/{storefront}/songs",
            developer_token,
            params={"ids": song_id, "limit": "1"},
        )
    elif isrc:
        payload = apple_music_tokens.apple_get(
            f"/catalog/{storefront}/songs",
            developer_token,
            params={"filter[isrc]": isrc, "limit": "25"},
        )
    else:
        payload = apple_music_tokens.apple_get(
            f"/catalog/{storefront}/search",
            developer_token,
            params={"term": term, "types": "songs", "limit": "25"},
        )
        results = payload.get("results")
        payload = results.get("songs", {}) if isinstance(results, dict) else {}
    return _parse_songs(payload)


def _search_match(db: Session, track: ExportTrack, storefront: str) -> str | None:
    best_song_id = None
    best_score = 0.0
    for candidate in search_catalog(db, storefront, f"{track.artist} {track.title}"):
        if is_unwanted_version(candidate.title):
            continue
        title_score = fuzzy_match_score(track.title, candidate.title)
        artist_score = artist_match_score(track.artist, candidate.artist)
        score = title_score * 0.7 + artist_score * 0.3
        if (
            title_score >= MIN_TITLE_SIMILARITY
            and artist_score >= MIN_ARTIST_SIMILARITY
            and score >= MATCH_THRESHOLD
            and score > best_score
        ):
            best_song_id = candidate.id
            best_score = score
    return best_song_id


def resolve_tracks(
    db: Session, user: User, tracks: list[ExportTrack]
) -> tuple[list[tuple[ExportTrack, str]], list[ExportTrack]]:
    """Resolve exact ISRCs first, then fuzzy title/artist matches in the DJ storefront."""
    _, storefront = apple_music_accounts.stored_connection(db, user)
    resolved: list[tuple[ExportTrack, str]] = []
    unresolved: list[ExportTrack] = []
    for track in tracks:
        apple_music_id = _apple_music_id(track)
        if apple_music_id:
            exact_id = next(
                (
                    song.id
                    for song in search_catalog(db, storefront, "", song_id=apple_music_id)
                    if song.id == apple_music_id
                ),
                None,
            )
            if exact_id:
                resolved.append((track, exact_id))
                continue
        if not track.has_metadata:
            unresolved.append(track)
            continue
        exact = None
        if track.isrc:
            exact = next(
                (
                    song
                    for song in search_catalog(db, storefront, "", isrc=track.isrc)
                    if song.isrc and song.isrc.casefold() == track.isrc.casefold()
                ),
                None,
            )
        song_id = exact.id if exact else _search_match(db, track, storefront)
        if song_id:
            resolved.append((track, song_id))
        else:
            unresolved.append(track)
    return resolved, unresolved
