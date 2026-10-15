"""Apple Music catalog search and playlist-track resolution."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

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
_PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_PLAYLIST_PAGES = 100


@dataclass(frozen=True)
class AppleCatalogSong:
    id: str
    title: str
    artist: str
    isrc: str | None
    album: str | None = None
    duration_ms: int | None = None


def _parse_songs(payload: dict[str, object]) -> list[AppleCatalogSong]:
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    songs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in (None, "songs"):
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
        album = attributes.get("albumName")
        duration_ms = attributes.get("durationInMillis")
        songs.append(
            AppleCatalogSong(
                id=song_id,
                title=title,
                artist=artist,
                isrc=isrc if isinstance(isrc, str) else None,
                album=album if isinstance(album, str) else None,
                duration_ms=duration_ms if isinstance(duration_ms, int) else None,
            )
        )
    return songs


def _public_playlist_resource(storefront: str, playlist_id: str) -> tuple[str, dict[str, object]]:
    if not _STOREFRONT_RE.fullmatch(storefront) or not _PLAYLIST_ID_RE.fullmatch(playlist_id):
        raise apple_music_tokens.AppleMusicError("Apple Music playlist identifier is invalid")
    path = f"/catalog/{storefront}/playlists/{playlist_id}"
    developer_token, _ = apple_music_tokens.create_developer_token()
    payload = apple_music_tokens.apple_get(path, developer_token)
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise apple_music_tokens.AppleMusicError("Apple Music returned an invalid playlist")
    resource = data[0]
    attributes = resource.get("attributes")
    if not isinstance(attributes, dict):
        raise apple_music_tokens.AppleMusicError("Apple Music returned an invalid playlist")
    return developer_token, attributes


def preview_public_playlist(storefront: str, playlist_id: str) -> dict[str, object]:
    """Fetch public playlist metadata using only the Apple catalog developer token."""
    _, attributes = _public_playlist_resource(storefront, playlist_id)
    return {
        "name": attributes.get("name") if isinstance(attributes.get("name"), str) else None,
        "owner": (
            attributes.get("curatorName")
            if isinstance(attributes.get("curatorName"), str)
            else None
        ),
        "track_count": (
            attributes.get("trackCount") if isinstance(attributes.get("trackCount"), int) else None
        ),
    }


def _next_page(next_url: object, *, storefront: str, playlist_id: str) -> dict[str, str] | None:
    if next_url is None:
        return None
    if not isinstance(next_url, str):
        raise apple_music_tokens.AppleMusicError("Apple Music returned an invalid pagination link")
    try:
        split = urlsplit(next_url)
    except ValueError as exc:
        raise apple_music_tokens.AppleMusicError(
            "Apple Music returned an invalid pagination link"
        ) from exc
    expected = f"/v1/catalog/{storefront}/playlists/{playlist_id}/tracks"
    if split.scheme or split.netloc or split.fragment or split.path != expected:
        raise apple_music_tokens.AppleMusicError("Apple Music returned an invalid pagination link")
    pairs = parse_qsl(split.query, keep_blank_values=True)
    keys = [key for key, _ in pairs]
    if (
        not pairs
        or len(keys) != len(set(keys))
        or any(key not in {"offset", "limit"} for key in keys)
        or any(not value.isdigit() for _, value in pairs)
    ):
        raise apple_music_tokens.AppleMusicError("Apple Music returned an invalid pagination link")
    return dict(pairs)


def fetch_public_playlist(
    storefront: str, playlist_id: str
) -> tuple[dict[str, object], list[AppleCatalogSong]]:
    """Fetch public playlist metadata and song pages through Apple's catalog API."""
    developer_token, attributes = _public_playlist_resource(storefront, playlist_id)
    path = f"/catalog/{storefront}/playlists/{playlist_id}/tracks"
    songs: list[AppleCatalogSong] = []
    params = None
    for page_number in range(_MAX_PLAYLIST_PAGES):
        payload = apple_music_tokens.apple_get(path, developer_token, params=params)
        songs.extend(_parse_songs(payload))
        params = _next_page(payload.get("next"), storefront=storefront, playlist_id=playlist_id)
        if params is None:
            break
    else:
        raise apple_music_tokens.AppleMusicError("Apple Music playlist has too many pages")
    metadata = {
        "name": attributes.get("name") if isinstance(attributes.get("name"), str) else None,
        "owner": (
            attributes.get("curatorName")
            if isinstance(attributes.get("curatorName"), str)
            else None
        ),
        "track_count": len(songs),
    }
    return metadata, songs


def search_catalog(
    _db: Session,
    storefront: str,
    term: str,
    *,
    isrc: str | None = None,
) -> list[AppleCatalogSong]:
    """Search Apple Music by ISRC or title and artist in one DJ storefront."""
    if not _STOREFRONT_RE.fullmatch(storefront):
        return []
    developer_token, _ = apple_music_tokens.create_developer_token()
    if isrc:
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
