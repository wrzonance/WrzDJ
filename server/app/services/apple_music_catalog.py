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
APPLE_CATALOG_ID_BATCH_SIZE = 300
_STOREFRONT_RE = re.compile(r"^[a-z]{2}$")
_APPLE_MUSIC_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_PLAYLIST_PAGES = 100


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
    album: str | None = None
    duration_ms: int | None = None


def _parse_songs(payload: dict[str, object]) -> list[AppleCatalogSong]:
    if not isinstance(payload, dict):
        return []
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
    developer_token, attributes = _public_playlist_resource(storefront, playlist_id)
    track_payload = apple_music_tokens.apple_get(
        f"/catalog/{storefront}/playlists/{playlist_id}/tracks",
        developer_token,
        params={"limit": "1"},
    )
    track_meta = track_payload.get("meta")
    track_count = track_meta.get("total") if isinstance(track_meta, dict) else None
    if not isinstance(track_count, int) or isinstance(track_count, bool) or track_count < 0:
        track_count = attributes.get("trackCount")
    if not isinstance(track_count, int) or isinstance(track_count, bool) or track_count < 0:
        track_count = None
    return {
        "name": attributes.get("name") if isinstance(attributes.get("name"), str) else None,
        "owner": (
            attributes.get("curatorName")
            if isinstance(attributes.get("curatorName"), str)
            else None
        ),
        "track_count": track_count,
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
    resource_count = 0
    provider_total: int | None = None
    params = None
    for page_number in range(_MAX_PLAYLIST_PAGES):
        payload = apple_music_tokens.apple_get(path, developer_token, params=params)
        page_songs, page_total = _parse_public_playlist_tracks(payload)
        songs.extend(page_songs)
        resource_count += len(page_songs)
        if provider_total is None:
            provider_total = page_total
        elif page_total is not None and page_total != provider_total:
            raise apple_music_tokens.AppleMusicError("Apple Music playlist changed during import")
        params = _next_page(payload.get("next"), storefront=storefront, playlist_id=playlist_id)
        if params is None:
            break
        if not page_songs:
            raise apple_music_tokens.AppleMusicError(
                "Apple Music returned incomplete playlist tracks"
            )
    else:
        raise apple_music_tokens.AppleMusicError("Apple Music playlist has too many pages")
    if provider_total is not None and resource_count != provider_total:
        raise apple_music_tokens.AppleMusicError("Apple Music returned incomplete playlist tracks")
    metadata = {
        "name": attributes.get("name") if isinstance(attributes.get("name"), str) else None,
        "owner": (
            attributes.get("curatorName")
            if isinstance(attributes.get("curatorName"), str)
            else None
        ),
        "track_count": provider_total if provider_total is not None else resource_count,
    }
    return metadata, songs


def _parse_public_playlist_tracks(
    payload: dict[str, object],
) -> tuple[list[AppleCatalogSong], int | None]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise apple_music_tokens.AppleMusicError("Apple Music returned invalid playlist tracks")
    for item in data:
        if not isinstance(item, dict):
            raise apple_music_tokens.AppleMusicError(
                "Apple Music returned an invalid playlist track"
            )
        if item.get("type") != "songs":
            raise apple_music_tokens.AppleMusicError(
                "Apple Music playlist contains an unsupported track type"
            )
    songs = _parse_songs(payload)
    if len(songs) != len(data):
        raise apple_music_tokens.AppleMusicError("Apple Music returned an invalid playlist track")
    meta = payload.get("meta")
    if meta is None:
        return songs, None
    if not isinstance(meta, dict):
        raise apple_music_tokens.AppleMusicError("Apple Music returned invalid playlist metadata")
    total = meta.get("total")
    if total is None:
        return songs, None
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise apple_music_tokens.AppleMusicError("Apple Music returned invalid playlist metadata")
    return songs, total


def search_catalog(
    _db: Session,
    storefront: str,
    term: str,
    *,
    isrc: str | None = None,
    song_id: str | None = None,
    song_ids: list[str] | None = None,
) -> list[AppleCatalogSong]:
    """Search Apple Music by ID, ISRC, or title and artist in one DJ storefront."""
    if not _STOREFRONT_RE.fullmatch(storefront):
        raise apple_music_tokens.AppleMusicError("Apple Music storefront is invalid")
    developer_token, _ = apple_music_tokens.create_developer_token()
    if song_ids:
        payload = apple_music_tokens.apple_get(
            f"/catalog/{storefront}/songs",
            developer_token,
            params={"ids": ",".join(song_ids), "limit": str(len(song_ids))},
        )
    elif song_id:
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
        songs = results.get("songs") if isinstance(results, dict) else None
        payload = songs if isinstance(songs, dict) else {}
    return _parse_songs(payload)


def _search_match(db: Session, track: ExportTrack, storefront: str) -> str | None:
    best_song_id = None
    best_score = 0.0
    for candidate in search_catalog(db, storefront, f"{track.artist} {track.title}"):
        score = _track_match_score(track, candidate)
        if score is not None and score > best_score:
            best_song_id = candidate.id
            best_score = score
    return best_song_id


def _track_match_score(track: ExportTrack, candidate: AppleCatalogSong) -> float | None:
    """Return a conservative identity score for one catalog result."""
    if not track.has_metadata or is_unwanted_version(candidate.title):
        return None
    if track.isrc and candidate.isrc and track.isrc.casefold() != candidate.isrc.casefold():
        return None
    title_score = fuzzy_match_score(track.title, candidate.title)
    artist_score = artist_match_score(track.artist, candidate.artist)
    score = title_score * 0.7 + artist_score * 0.3
    if (
        title_score < MIN_TITLE_SIMILARITY
        or artist_score < MIN_ARTIST_SIMILARITY
        or score < MATCH_THRESHOLD
    ):
        return None
    return score


def _catalog_id_chunks(song_ids: list[str]) -> list[list[str]]:
    return [
        song_ids[index : index + APPLE_CATALOG_ID_BATCH_SIZE]
        for index in range(0, len(song_ids), APPLE_CATALOG_ID_BATCH_SIZE)
    ]


def resolve_tracks(
    db: Session, user: User, tracks: list[ExportTrack]
) -> tuple[list[tuple[ExportTrack, str]], list[ExportTrack]]:
    """Resolve exact ISRCs first, then fuzzy title/artist matches in the DJ storefront."""
    _, storefront = apple_music_accounts.stored_connection(db, user)
    apple_music_ids = list(
        dict.fromkeys(
            apple_music_id
            for track in tracks
            if (apple_music_id := _apple_music_id(track)) is not None
        )
    )
    catalog_songs_by_id: dict[str, AppleCatalogSong] = {}
    for chunk in _catalog_id_chunks(apple_music_ids):
        try:
            catalog_songs = search_catalog(db, storefront, "", song_ids=chunk)
        except apple_music_tokens.AppleMusicNotFound:
            continue
        catalog_songs_by_id.update((song.id, song) for song in catalog_songs)

    resolved: list[tuple[ExportTrack, str]] = []
    unresolved: list[ExportTrack] = []
    for track in tracks:
        apple_music_id = _apple_music_id(track)
        if apple_music_id:
            candidate = catalog_songs_by_id.get(apple_music_id)
            if candidate and _track_match_score(track, candidate) is not None:
                resolved.append((track, candidate.id))
                continue
        if not track.has_metadata:
            unresolved.append(track)
            continue
        try:
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
        except apple_music_tokens.AppleMusicError:
            unresolved.append(track)
            continue
        if song_id:
            resolved.append((track, song_id))
        else:
            unresolved.append(track)
    return resolved, unresolved
