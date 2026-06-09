"""WrzDJSet pool service (issue #388).

The pool is a set's candidate-track surface. Tracks flow in from five
import flows (event requests, Tidal playlist, Beatport playlist, public
playlist URL, manual single-track search); every track is tagged with the
SetPoolSource it came through so removal flows can operate per-source.

Dedupe on import: exact ISRC match against the pool first, then a
normalized artist+title signature (via services/track_normalizer). The
first import wins — the original source tag is preserved.
"""

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.recommendation.camelot import parse_key
from app.services.track_normalizer import normalize_track

logger = logging.getLogger(__name__)


class PoolImportError(Exception):
    """Import failed for a user-presentable reason (message is safe to surface)."""


@dataclass(frozen=True)
class PoolCandidate:
    """A track candidate produced by an import flow, pre-insert."""

    title: str
    artist: str
    track_id: str | None = None
    album: str | None = None
    genre: str | None = None
    bpm: float | None = None
    key: str | None = None
    energy: int | None = None
    isrc: str | None = None
    duration_sec: int | None = None
    artwork_url: str | None = None


def dedupe_signature(artist: str, title: str) -> str:
    """Normalized artist+title hash — the fuzzy fallback dedupe key."""
    n = normalize_track(title, artist)
    normalized = f"{n.artist.lower().strip()}:{n.title.lower().strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def camelot_code(key: str | None) -> str | None:
    """Convert any common key notation to a Camelot code ('8B'), or None."""
    pos = parse_key(key)
    return str(pos) if pos else None


def _normalize_isrc(isrc: str | None) -> str | None:
    if not isrc:
        return None
    cleaned = isrc.strip().upper().replace("-", "")
    return cleaned or None


# ---------------------------------------------------------------------------
# Pool reads


def get_pool(db: Session, set_id: int) -> tuple[list[SetPoolSource], list[SetPoolTrack]]:
    """All sources + tracks for a set, in stable insertion order."""
    sources = (
        db.query(SetPoolSource)
        .filter(SetPoolSource.set_id == set_id)
        .order_by(SetPoolSource.id)
        .all()
    )
    tracks = (
        db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_id).order_by(SetPoolTrack.id).all()
    )
    return sources, tracks


def get_owned_source(db: Session, set_obj: Set, source_id: int) -> SetPoolSource | None:
    """Fetch a source scoped to the set. None if missing or from another set."""
    return (
        db.query(SetPoolSource)
        .filter(SetPoolSource.id == source_id, SetPoolSource.set_id == set_obj.id)
        .one_or_none()
    )


# ---------------------------------------------------------------------------
# Sources + import


def get_or_create_source(
    db: Session,
    set_obj: Set,
    *,
    kind: str,
    external_ref: str | None,
    label: str,
    meta: str | None = None,
) -> SetPoolSource:
    """Find-or-create the source row for (set, kind, external_ref).

    Re-importing the same playlist/event reuses the existing row (label and
    meta are refreshed) so counts stay consistent and no duplicate source
    rows ever appear in the accordion.
    """
    existing = (
        db.query(SetPoolSource)
        .filter(
            SetPoolSource.set_id == set_obj.id,
            SetPoolSource.kind == kind,
            SetPoolSource.external_ref == external_ref,
        )
        .first()
    )
    if existing is not None:
        existing.label = label
        if meta is not None:
            existing.meta = meta
        db.flush()
        return existing
    source = SetPoolSource(
        set_id=set_obj.id, kind=kind, external_ref=external_ref, label=label, meta=meta
    )
    db.add(source)
    db.flush()
    return source


def import_candidates(
    db: Session,
    set_obj: Set,
    source: SetPoolSource,
    candidates: Iterable[PoolCandidate],
) -> tuple[int, int]:
    """Insert candidates into the pool, deduping against existing tracks.

    Returns (added, deduped). Dedupe order: ISRC exact match, then
    normalized artist+title signature. First import wins — existing rows
    keep their original source tag.
    """
    existing = db.query(SetPoolTrack.dedupe_sig, SetPoolTrack.isrc).filter(
        SetPoolTrack.set_id == set_obj.id
    )
    seen_sigs: set[str] = set()
    seen_isrcs: set[str] = set()
    for sig, isrc in existing:
        seen_sigs.add(sig)
        norm = _normalize_isrc(isrc)
        if norm:
            seen_isrcs.add(norm)

    added = 0
    deduped = 0
    for c in candidates:
        title = (c.title or "").strip()
        artist = (c.artist or "").strip()
        if not title or not artist:
            continue
        sig = dedupe_signature(artist, title)
        isrc = _normalize_isrc(c.isrc)
        if sig in seen_sigs or (isrc and isrc in seen_isrcs):
            deduped += 1
            continue
        db.add(
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=source.id,
                track_id=c.track_id,
                title=title[:255],
                artist=artist[:255],
                album=c.album,
                genre=c.genre,
                bpm=c.bpm,
                key=c.key,
                camelot=camelot_code(c.key),
                energy=c.energy,
                isrc=isrc,
                duration_sec=c.duration_sec,
                artwork_url=c.artwork_url,
                dedupe_sig=sig,
            )
        )
        seen_sigs.add(sig)
        if isrc:
            seen_isrcs.add(isrc)
        added += 1

    db.commit()
    return added, deduped


# ---------------------------------------------------------------------------
# Removal flows


def remove_tracks(db: Session, set_obj: Set, track_ids: list[int]) -> int:
    """Delete pool tracks by id, scoped to the set. Returns rows removed."""
    if not track_ids:
        return 0
    removed = (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_obj.id, SetPoolTrack.id.in_(track_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return removed


def remove_source(db: Session, set_obj: Set, source: SetPoolSource) -> int:
    """Delete a source and exactly its tracks (cascade). Returns track count removed."""
    count = db.query(SetPoolTrack).filter(SetPoolTrack.source_id == source.id).count()
    db.delete(source)
    db.commit()
    return count


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

    Raises tidal.TidalFetchError on fetch failure (caller maps to 502).
    """
    from app.services import tidal

    raw_tracks = tidal.get_playlist_tracks(db, user, playlist_id)
    candidates: list[PoolCandidate] = []
    for raw in raw_tracks:
        r = tidal._track_to_result(raw)
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
    from app.services import beatport

    results = beatport.get_playlist_tracks(db, user, playlist_id)
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


def preview_public_playlist(db: Session, user: User, provider: str, playlist_id: str) -> dict:
    """Lightweight metadata for the validate→preview card. Never fetches the raw URL."""
    if provider == "spotify":
        return _spotify_playlist_preview(playlist_id)
    if provider == "tidal":
        return _tidal_playlist_preview(db, user, playlist_id)
    raise PoolImportError("This provider isn't supported for public playlist import yet")


def candidates_from_public_url(
    db: Session, user: User, provider: str, playlist_id: str
) -> tuple[str, list[PoolCandidate]]:
    """Fetch all tracks of a public playlist. Returns (playlist_name, candidates)."""
    if provider == "spotify":
        return _spotify_playlist_candidates(playlist_id)
    if provider == "tidal":
        return _tidal_playlist_candidates(db, user, playlist_id)
    raise PoolImportError("This provider isn't supported for public playlist import yet")


def _spotify_client():
    from app.services.spotify import _get_spotify_client

    try:
        return _get_spotify_client()
    except ValueError as e:
        raise PoolImportError("Spotify is not configured on this server") from e


def _spotify_playlist_preview(playlist_id: str) -> dict:
    sp = _spotify_client()
    try:
        data = sp.playlist(playlist_id, fields="name,owner.display_name,tracks.total")
    except Exception as e:
        logger.warning("Spotify playlist preview failed: %s", type(e).__name__)
        raise PoolImportError("Couldn't fetch that Spotify playlist — is it public?") from e
    return {
        "name": data.get("name"),
        "owner": (data.get("owner") or {}).get("display_name"),
        "track_count": (data.get("tracks") or {}).get("total"),
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
    from app.services import tidal

    session = tidal.get_tidal_session(db, user)
    if session is None:
        raise PoolImportError("Connect your Tidal account to import Tidal playlist URLs")
    return session


def _tidal_playlist_preview(db: Session, user: User, playlist_id: str) -> dict:
    session = _tidal_session_or_error(db, user)
    try:
        playlist = session.playlist(playlist_id)
        return {
            "name": playlist.name,
            "owner": None,
            "track_count": getattr(playlist, "num_tracks", None),
        }
    except Exception as e:
        logger.warning("Tidal playlist preview failed: %s", type(e).__name__)
        raise PoolImportError("Couldn't fetch that Tidal playlist — is it public?") from e


def _tidal_playlist_candidates(
    db: Session, user: User, playlist_id: str
) -> tuple[str, list[PoolCandidate]]:
    from app.services import tidal

    preview = _tidal_playlist_preview(db, user, playlist_id)
    try:
        candidates = candidates_from_tidal(db, user, playlist_id)
    except tidal.TidalFetchError as e:
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
    """Build a candidate from a manual search pick (validated at the API layer)."""
    track_id = None
    if source_track_id and source_service != "manual":
        track_id = f"{source_service}:{source_track_id}"
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
