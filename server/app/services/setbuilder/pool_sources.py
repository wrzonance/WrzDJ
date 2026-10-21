"""Candidate source adapters and provider-specific playlist import mapping."""

import logging
from typing import TypedDict

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.set_pool import SetPoolTrack
from app.models.user import User
from app.services.setbuilder.pool_types import PoolCandidate, PoolImportError, camelot_code

logger = logging.getLogger(__name__)


class PublicPlaylistPreview(TypedDict):
    name: str | None
    owner: str | None
    track_count: int | None


def _candidate_from_pool_track(track: SetPoolTrack) -> PoolCandidate:
    return PoolCandidate(
        title=track.title,
        artist=track.artist,
        track_id=track.track_id,
        album=track.album,
        genre=track.genre,
        bpm=track.bpm,
        key=track.key,
        energy=track.energy,
        isrc=track.isrc,
        duration_sec=track.duration_sec,
        artwork_url=track.artwork_url,
    )


def _apply_candidate_to_pool_track(track: SetPoolTrack, candidate: PoolCandidate) -> None:
    if candidate.album is not None:
        track.album = candidate.album
    if candidate.genre is not None:
        track.genre = candidate.genre
    if candidate.bpm is not None:
        track.bpm = float(candidate.bpm)
    if candidate.key:
        track.key = candidate.key
        track.camelot = camelot_code(candidate.key)
    if candidate.energy is not None:
        track.energy = candidate.energy
    if candidate.duration_sec is not None:
        track.duration_sec = candidate.duration_sec
    if candidate.artwork_url is not None:
        track.artwork_url = candidate.artwork_url


# ---------------------------------------------------------------------------
# Candidate builders (one per import flow)


def candidates_from_event(
    db: Session, user: User, event_id: int
) -> tuple[Event, list[PoolCandidate]] | None:
    """Map a DJ's own event's non-rejected requests to candidates.

    Returns None if the event is missing or not owned by the user (the API
    layer surfaces a 404 to avoid leaking existence).
    """
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.created_by_user_id == user.id)
        .one_or_none()
    )
    if event is None:
        return None
    requests = (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status != RequestStatus.REJECTED.value,
        )
        .order_by(Request.id)
        .all()
    )
    candidates = [
        PoolCandidate(
            track_id=f"request:{r.id}",
            title=r.song_title,
            artist=r.artist,
            genre=r.genre,
            bpm=r.bpm,
            key=r.musical_key,
        )
        for r in requests
    ]
    return event, candidates


def candidates_from_tidal(db: Session, user: User, playlist_id: str) -> list[PoolCandidate]:
    """Fetch a connected-account Tidal playlist's tracks as candidates.

    Raises TidalFetchError on fetch failure (caller maps to 502).
    """
    from app.services.providers.tidal_search import get_playlist_tracks

    results = get_playlist_tracks(db, user, playlist_id)
    candidates: list[PoolCandidate] = []
    for r in results:
        candidates.append(
            PoolCandidate(
                track_id=f"tidal:{r.track_id}",
                title=f"{r.title} ({r.version})" if r.version else r.title,
                artist=r.artist,
                album=r.album,
                bpm=r.bpm,
                key=r.key,
                isrc=r.isrc,
                duration_sec=r.duration_seconds,
                artwork_url=r.cover_url,
            )
        )
    return candidates


def candidates_from_beatport(db: Session, user: User, playlist_id: str) -> list[PoolCandidate]:
    """Fetch a connected-account Beatport playlist's tracks as candidates."""
    from app.services.providers.beatport_playlists import get_playlist_tracks

    results = get_playlist_tracks(db, user, playlist_id)
    candidates: list[PoolCandidate] = []
    for r in results:
        title = r.title
        if r.mix_name and r.mix_name.strip().lower() not in ("original mix", "original"):
            title = f"{r.title} ({r.mix_name})"
        candidates.append(
            PoolCandidate(
                track_id=f"beatport:{r.track_id}",
                title=title,
                artist=r.artist,
                genre=r.genre,
                bpm=float(r.bpm) if r.bpm is not None else None,
                key=r.key,
                duration_sec=r.duration_seconds,
                artwork_url=r.cover_url,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Public playlist URL (Spotify via client credentials, Tidal via DJ session)

_SPOTIFY_PAGE_SIZE = 100


def preview_public_playlist(
    db: Session, user: User, provider: str, playlist_id: str, storefront: str | None = None
) -> PublicPlaylistPreview:
    """Lightweight metadata for the validate→preview card. Never fetches the raw URL."""
    if provider == "spotify":
        return _spotify_playlist_preview(playlist_id)
    if provider == "tidal":
        return _tidal_playlist_preview(db, user, playlist_id)
    if provider == "apple_music":
        from app.services.apple_music import catalog as apple_music_catalog
        from app.services.apple_music.tokens import AppleMusicError

        try:
            if storefront is None:
                raise PoolImportError("Apple Music playlist URL is missing its storefront")
            metadata = apple_music_catalog.preview_public_playlist(storefront, playlist_id)
            name = metadata.get("name")
            owner = metadata.get("owner")
            track_count = metadata.get("track_count")
            return {
                "name": name if isinstance(name, str) else None,
                "owner": owner if isinstance(owner, str) else None,
                "track_count": (
                    track_count
                    if isinstance(track_count, int) and not isinstance(track_count, bool)
                    else None
                ),
            }
        except AppleMusicError as e:
            logger.warning("Apple Music playlist preview failed: %s", type(e).__name__)
            raise PoolImportError(
                "Couldn't fetch that Apple Music playlist — is it public in this storefront?"
            ) from e
    raise PoolImportError("This provider isn't supported for public playlist import yet")


def candidates_from_public_url(
    db: Session, user: User, provider: str, playlist_id: str, storefront: str | None = None
) -> tuple[str, list[PoolCandidate]]:
    """Fetch all tracks of a public playlist. Returns (playlist_name, candidates)."""
    if provider == "spotify":
        return _spotify_playlist_candidates(playlist_id)
    if provider == "tidal":
        return _tidal_playlist_candidates(db, user, playlist_id)
    if provider == "apple_music":
        return _apple_music_playlist_candidates(playlist_id, storefront)
    raise PoolImportError("This provider isn't supported for public playlist import yet")


def _apple_music_playlist_candidates(
    playlist_id: str, storefront: str | None
) -> tuple[str, list[PoolCandidate]]:
    from app.services.apple_music import catalog as apple_music_catalog
    from app.services.apple_music.tokens import AppleMusicError

    if storefront is None:
        raise PoolImportError("Apple Music playlist URL is missing its storefront")
    try:
        metadata, songs = apple_music_catalog.fetch_public_playlist(storefront, playlist_id)
    except AppleMusicError as e:
        logger.warning("Apple Music playlist fetch failed: %s", type(e).__name__)
        raise PoolImportError(
            "Couldn't fetch that Apple Music playlist — is it public in this storefront?"
        ) from e
    candidates = [
        PoolCandidate(
            track_id=f"apple_music:{song.id}",
            title=song.title,
            artist=song.artist,
            album=song.album,
            isrc=song.isrc,
            duration_sec=song.duration_ms // 1000 if song.duration_ms else None,
        )
        for song in songs
    ]
    return metadata.get("name") or "Apple Music playlist", candidates


def _spotify_client():
    from app.services.providers.spotify import get_spotify_client

    try:
        return get_spotify_client()
    except ValueError as e:
        raise PoolImportError("Spotify is not configured on this server") from e


def _spotify_playlist_preview(playlist_id: str) -> PublicPlaylistPreview:
    sp = _spotify_client()
    try:
        data = sp.playlist(playlist_id, fields="name,owner.display_name,tracks.total")
    except Exception as e:
        logger.warning("Spotify playlist preview failed: %s", type(e).__name__)
        raise PoolImportError("Couldn't fetch that Spotify playlist — is it public?") from e
    if not isinstance(data, dict):
        data = {}
    owner = data.get("owner")
    tracks = data.get("tracks")
    name = data.get("name")
    display_name = owner.get("display_name") if isinstance(owner, dict) else None
    track_count = tracks.get("total") if isinstance(tracks, dict) else None
    return {
        "name": name if isinstance(name, str) else None,
        "owner": display_name if isinstance(display_name, str) else None,
        "track_count": (
            track_count
            if isinstance(track_count, int) and not isinstance(track_count, bool)
            else None
        ),
    }


def _spotify_playlist_candidates(playlist_id: str) -> tuple[str, list[PoolCandidate]]:
    sp = _spotify_client()
    preview = _spotify_playlist_preview(playlist_id)
    candidates: list[PoolCandidate] = []
    offset = 0
    try:
        while True:
            page = sp.playlist_items(
                playlist_id,
                limit=_SPOTIFY_PAGE_SIZE,
                offset=offset,
                fields=(
                    "items(track(id,name,duration_ms,external_ids.isrc,"
                    "artists.name,album(name,images))),next"
                ),
                additional_types=("track",),
            )

            items = page.get("items") or []
            for item in items:
                track = item.get("track") or {}
                name = track.get("name")
                artists = ", ".join(
                    a.get("name", "") for a in (track.get("artists") or []) if a.get("name")
                )
                if not name or not artists:
                    continue
                album = track.get("album") or {}
                images = album.get("images") or []
                duration_ms = track.get("duration_ms")
                candidates.append(
                    PoolCandidate(
                        track_id=f"spotify:{track.get('id')}" if track.get("id") else None,
                        title=name,
                        artist=artists,
                        album=album.get("name"),
                        isrc=(track.get("external_ids") or {}).get("isrc"),
                        duration_sec=int(duration_ms / 1000) if duration_ms else None,
                        artwork_url=images[0].get("url") if images else None,
                    )
                )
            if not page.get("next") or not items:
                break
            offset += _SPOTIFY_PAGE_SIZE
    except PoolImportError:
        raise
    except Exception as e:
        logger.warning("Spotify playlist fetch failed: %s", type(e).__name__)
        raise PoolImportError("Couldn't fetch that Spotify playlist — is it public?") from e
    return preview.get("name") or "Spotify playlist", candidates


def _tidal_session_or_error(db: Session, user: User):
    from app.services.providers.tidal_account import get_tidal_session

    session = get_tidal_session(db, user)
    if session is None:
        raise PoolImportError("Connect your Tidal account to import Tidal playlist URLs")
    return session


def _tidal_playlist_preview(db: Session, user: User, playlist_id: str) -> PublicPlaylistPreview:
    session = _tidal_session_or_error(db, user)
    try:
        playlist = session.playlist(playlist_id)
        name = getattr(playlist, "name", None)
        track_count = getattr(playlist, "num_tracks", None)
        return {
            "name": name if isinstance(name, str) else None,
            "owner": None,
            "track_count": (
                track_count
                if isinstance(track_count, int) and not isinstance(track_count, bool)
                else None
            ),
        }
    except Exception as e:
        logger.warning("Tidal playlist preview failed: %s", type(e).__name__)
        raise PoolImportError("Couldn't fetch that Tidal playlist — is it public?") from e


def _tidal_playlist_candidates(
    db: Session, user: User, playlist_id: str
) -> tuple[str, list[PoolCandidate]]:
    from app.services.providers.tidal_catalog import TidalFetchError

    preview = _tidal_playlist_preview(db, user, playlist_id)
    try:
        candidates = candidates_from_tidal(db, user, playlist_id)
    except TidalFetchError as e:
        raise PoolImportError("Couldn't fetch that Tidal playlist — is it public?") from e
    return preview.get("name") or "Tidal playlist", candidates


def candidate_from_manual(
    *,
    title: str,
    artist: str,
    album: str | None = None,
    genre: str | None = None,
    bpm: float | None = None,
    key: str | None = None,
    isrc: str | None = None,
    duration_sec: int | None = None,
    artwork_url: str | None = None,
    source_service: str = "manual",
    source_track_id: str | None = None,
) -> PoolCandidate:
    """Build a candidate from a manual search pick (validated at the API layer).

    ``source_service``/``source_track_id`` are CLIENT input, so this must NEVER mint
    an authoritative ``beatport:``/``tidal:`` track_id from them — that prefix is the
    authority signal ``_candidate_source`` trusts, and forging it would let a crafted
    request write fabricated provider-grade data into the shared, multi-tenant store
    (#554 P1). Authoritative beatport/tidal prefixes come ONLY from the server-side
    playlist builders (``candidates_from_beatport``/``candidates_from_tidal``), which
    mint them from the DJ's OAuth'd server-side fetch — never from this path.

    We keep ONLY a non-authoritative ``spotify:<id>`` reference (Spotify resolves to
    ``legacy`` in ``_candidate_source`` regardless, and it is the one provider the FE
    actually sends an id for). Everything else stays ``track_id=None`` → ``legacy``."""
    track_id = None
    if source_track_id and source_service == "spotify":
        track_id = f"spotify:{source_track_id}"
    return PoolCandidate(
        track_id=track_id,
        title=title,
        artist=artist,
        album=album,
        genre=genre,
        bpm=bpm,
        key=key,
        isrc=isrc,
        duration_sec=duration_sec,
        artwork_url=artwork_url,
    )
