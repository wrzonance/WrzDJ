"""Tidal API integration for playlist sync to SC6000 decks.

Uses tidalapi with device code OAuth flow for full API access.
Third-party OAuth scopes don't have access to playlist creation,
so we use tidalapi's device login which has first-party credentials.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import tidalapi
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus, TidalSyncStatus
from app.models.user import User
from app.schemas.tidal import TidalSearchResult, TidalSyncResult
from app.services.track_normalizer import artist_match_score, primary_artist

logger = logging.getLogger(__name__)

# Device login state expiration (10 minutes)
DEVICE_LOGIN_TTL_MINUTES = 10


@dataclass
class DeviceLoginState:
    """State for device OAuth flow."""

    user_id: int
    session: tidalapi.Session
    login_info: Any  # tidalapi.LinkLogin
    future: Any  # concurrent.futures.Future
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# In-memory device login storage
_device_logins: dict[int, DeviceLoginState] = {}
_login_lock = threading.Lock()


def _cleanup_expired_device_logins() -> None:
    """Remove device logins older than TTL."""
    cutoff = datetime.now(UTC) - timedelta(minutes=DEVICE_LOGIN_TTL_MINUTES)
    with _login_lock:
        expired = [uid for uid, state in _device_logins.items() if state.created_at < cutoff]
        for uid in expired:
            del _device_logins[uid]


def start_device_login(user: User) -> dict[str, str]:
    """Start Tidal device login flow.

    Returns dict with verification_url and user_code for the user to visit.
    """
    _cleanup_expired_device_logins()

    session = tidalapi.Session()
    login, future = session.login_oauth()

    with _login_lock:
        _device_logins[user.id] = DeviceLoginState(
            user_id=user.id,
            session=session,
            login_info=login,
            future=future,
        )

    # Ensure URL has https:// prefix (tidalapi may omit it)
    url = login.verification_uri_complete
    if url and not url.startswith("http"):
        url = f"https://{url}"

    return {
        "verification_url": url,
        "user_code": login.user_code,
    }


def check_device_login(db: Session, user: User) -> dict[str, Any]:
    """Check if device login is complete.

    Returns status dict with 'complete' bool and optionally 'error'.
    """
    with _login_lock:
        state = _device_logins.get(user.id)

    if not state:
        return {"complete": False, "error": "No pending login"}

    # Check if future is done
    if not state.future.done():
        url = state.login_info.verification_uri_complete
        if url and not url.startswith("http"):
            url = f"https://{url}"
        return {
            "complete": False,
            "pending": True,
            "verification_url": url,
            "user_code": state.login_info.user_code,
        }

    try:
        # Future completed - check result
        state.future.result(timeout=0)

        # Login succeeded - save tokens
        session = state.session
        user.tidal_access_token = session.access_token
        user.tidal_refresh_token = session.refresh_token
        user.tidal_token_expires_at = session.expiry_time
        user.tidal_user_id = str(session.user.id) if session.user else ""

        db.commit()
        logger.info(f"Tidal device login completed for user {user.id}")

        # Cleanup
        with _login_lock:
            _device_logins.pop(user.id, None)

        return {"complete": True, "user_id": user.tidal_user_id}

    except Exception as e:
        logger.error(f"Tidal device login failed: {e}")
        with _login_lock:
            _device_logins.pop(user.id, None)
        return {"complete": False, "error": "Tidal login failed. Please try again."}


def cancel_device_login(user: User) -> None:
    """Cancel a pending device login."""
    with _login_lock:
        _device_logins.pop(user.id, None)


def get_tidal_session(db: Session, user: User) -> tidalapi.Session | None:
    """Get authenticated tidalapi session for user."""
    if not user.tidal_access_token:
        return None

    session = tidalapi.Session()

    try:
        # Load tokens into session
        session.load_oauth_session(
            token_type="Bearer",  # nosec B106 - OAuth token type, not a password
            access_token=user.tidal_access_token,
            refresh_token=user.tidal_refresh_token,
            expiry_time=user.tidal_token_expires_at,
        )

        # Check if session needs refresh
        if not session.check_login():
            if session.token_refresh(user.tidal_refresh_token):
                # Save new tokens
                user.tidal_access_token = session.access_token
                user.tidal_refresh_token = session.refresh_token
                user.tidal_token_expires_at = session.expiry_time
                db.commit()
                logger.info(f"Tidal token refreshed for user {user.id}")
            else:
                logger.error("Failed to refresh Tidal session")
                return None

        return session

    except Exception as e:
        logger.error(f"Failed to load Tidal session: {e}")
        return None


def _get_artist_name(track: tidalapi.Track) -> str:
    """Get the full artist name from a Tidal track.

    tidalapi's ``track.artist`` is only the *primary* artist (first in
    the list).  For multi-artist tracks like "Big & Rich", Tidal stores
    separate artist objects and ``track.artist.name`` returns just "Big".
    We join all artist names to preserve the full credit.
    """
    if hasattr(track, "artists") and track.artists:
        names = [a.name for a in track.artists if a and a.name]
        if names:
            return ", ".join(names)
    return track.artist.name if track.artist else "Unknown"


def _track_to_result(track: tidalapi.Track) -> TidalSearchResult:
    """Convert tidalapi Track to TidalSearchResult."""
    cover_url = None
    try:
        if track.album:
            cover_url = track.album.image(640)
    except Exception:  # nosec B110 — cover art is optional, failure is non-critical
        pass

    bpm = None
    try:
        bpm = float(track.bpm) if hasattr(track, "bpm") and track.bpm else None
    except (TypeError, ValueError):
        pass  # nosec B110

    key = None
    try:
        key = track.key if hasattr(track, "key") and track.key else None
    except (TypeError, AttributeError):
        pass  # nosec B110

    popularity = 0
    try:
        raw_pop = getattr(track, "popularity", None)
        if isinstance(raw_pop, (int, float)):
            popularity = int(raw_pop)
    except (TypeError, ValueError):
        pass  # nosec B110

    isrc = None
    try:
        raw_isrc = getattr(track, "isrc", None)
        if isinstance(raw_isrc, str) and raw_isrc:
            isrc = raw_isrc
    except (TypeError, AttributeError):
        pass  # nosec B110

    version = None
    try:
        raw_version = getattr(track, "version", None)
        if isinstance(raw_version, str) and raw_version:
            version = raw_version
    except (TypeError, AttributeError):
        pass  # nosec B110

    explicit = False
    try:
        raw_explicit = getattr(track, "explicit", None)
        if isinstance(raw_explicit, bool):
            explicit = raw_explicit
    except (TypeError, AttributeError):
        pass  # nosec B110

    return TidalSearchResult(
        track_id=str(track.id),
        title=track.name or "Unknown",
        artist=_get_artist_name(track),
        album=track.album.name if track.album else None,
        bpm=bpm,
        key=key,
        duration_seconds=track.duration if track.duration else None,
        cover_url=cover_url,
        tidal_url=f"https://tidal.com/browse/track/{track.id}",
        popularity=popularity,
        isrc=isrc,
        version=version,
        explicit=explicit,
    )


def search_track(
    db: Session,
    user: User,
    artist: str,
    title: str,
) -> TidalSearchResult | None:
    """Search Tidal for a track."""
    session = get_tidal_session(db, user)
    if not session:
        return None

    try:
        query = f"{primary_artist(artist)} {title}"
        results = session.search(query, models=[tidalapi.media.Track], limit=10)

        tracks = results.get("tracks", [])
        if not tracks:
            return None

        # Find best match using multi-artist-aware scoring
        title_lower = title.lower()

        for track in tracks:
            track_artist = _get_artist_name(track)
            track_title = (track.name or "").lower()

            if artist_match_score(artist, track_artist) >= 0.7 and title_lower in track_title:
                return _track_to_result(track)

        return _track_to_result(tracks[0])

    except Exception as e:
        logger.error(f"Tidal search failed: {e}")
        return None


def create_event_playlist(
    db: Session,
    user: User,
    event: Event,
) -> str | None:
    """Create a Tidal playlist for an event."""
    if event.tidal_playlist_id:
        return event.tidal_playlist_id

    session = get_tidal_session(db, user)
    if not session:
        return None

    try:
        playlist_name = f"WrzDJ: {event.code} – {event.name}"
        description = f"Song requests for {event.name}"

        playlist = session.user.create_playlist(playlist_name, description)

        event.tidal_playlist_id = str(playlist.id)
        db.commit()

        logger.info(f"Created Tidal playlist {playlist.id} for event {event.code}")
        return event.tidal_playlist_id

    except Exception as e:
        logger.error(f"Failed to create Tidal playlist: {e}")
        return None


def ensure_collection_playlist(
    db: Session,
    user: User,
    event: Event,
) -> str | None:
    """Create (or reuse) the pre-event collection Tidal playlist for an event.

    Kept separate from create_event_playlist so collection suggestions and
    live-event accepted requests land in two distinct Tidal playlists.
    """
    if event.tidal_collection_playlist_id:
        return event.tidal_collection_playlist_id

    session = get_tidal_session(db, user)
    if not session:
        return None

    try:
        playlist_name = f"WrzDJ: {event.code} – {event.name} (pre-event)"
        description = f"Pre-event song suggestions for {event.name}"

        playlist = session.user.create_playlist(playlist_name, description)

        event.tidal_collection_playlist_id = str(playlist.id)
        db.commit()

        logger.info(f"Created Tidal collection playlist {playlist.id} for event {event.code}")
        return event.tidal_collection_playlist_id

    except Exception as e:
        logger.error(f"Failed to create Tidal collection playlist: {e}")
        return None


def sync_collection_requests_batch(
    db: Session,
    user: User,
    event: Event,
    requests: list,
) -> None:
    """Batch-sync pre-event collection requests to the collection playlist.

    Searches tracks sequentially, adds all found IDs in one API call, and
    stores the matched Tidal track ID on each request for bidirectional sync.
    Tidal's allow_duplicates=False deduplicates silently at the API layer.
    """
    if not requests:
        return

    playlist_id = ensure_collection_playlist(db, user, event)
    if not playlist_id:
        return

    track_ids: list[str] = []
    matched: list[tuple] = []  # (request, track_id)
    for req in requests:
        try:
            results = search_tidal_tracks(db, user, f"{req.song_title} {req.artist}")
            if results:
                track_id = results[0].track_id
                track_ids.append(track_id)
                matched.append((req, track_id))
        except Exception as e:
            logger.error(f"Collection sync search failed for '{req.song_title}': {e}")

    if track_ids:
        if add_tracks_to_playlist(db, user, playlist_id, track_ids):
            for req, track_id in matched:
                req.tidal_collection_track_id = track_id
            db.commit()


def add_track_to_playlist(
    db: Session,
    user: User,
    playlist_id: str,
    track_id: str,
) -> bool:
    """Add a track to a Tidal playlist."""
    return add_tracks_to_playlist(db, user, playlist_id, [track_id])


def add_tracks_to_playlist(
    db: Session,
    user: User,
    playlist_id: str,
    track_ids: list[str],
) -> bool:
    """Add multiple tracks to a Tidal playlist in one batch API call.

    Duplicates are automatically skipped by Tidal's API (allow_duplicates=False).
    """
    if not track_ids:
        return True

    session = get_tidal_session(db, user)
    if not session:
        return False

    try:
        playlist = session.playlist(playlist_id)
        playlist.add(track_ids)  # allow_duplicates=False by default → skips dupes
        logger.info(f"Added {len(track_ids)} track(s) to playlist {playlist_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to add tracks to playlist: {e}")
        return False


def remove_track_from_collection_playlist(
    db: Session,
    user: User,
    event: Event,
    track_id: str,
) -> bool:
    """Remove a single track from the event's Tidal collection playlist.

    Returns True on success, False if the playlist doesn't exist or the API call fails.
    Failures are logged but not raised — removal is best-effort.
    """
    playlist_id = event.tidal_collection_playlist_id
    if not playlist_id:
        return False

    session = get_tidal_session(db, user)
    if not session:
        return False

    try:
        playlist = session.playlist(playlist_id)
        return bool(playlist.remove_by_id(track_id))
    except Exception as e:
        logger.error(f"Failed to remove track {track_id} from collection playlist: {e}")
        return False


def remove_collection_tracks_batch(
    db: Session,
    user: User,
    event: Event,
    track_ids: list[str],
) -> None:
    """Remove multiple tracks from the collection playlist, one by one.

    Best-effort: logs failures per track but does not abort on error.
    """
    for track_id in track_ids:
        remove_track_from_collection_playlist(db, user, event, track_id)


def poll_tidal_collection_removals(db: Session, event: Event) -> int:
    """Detect tracks removed from the Tidal collection playlist and reject them in WrzDJ.

    Fetches current playlist contents, finds collection requests whose
    tidal_collection_track_id is no longer present, and marks them rejected.
    Only runs when the event has a collection playlist configured.

    Returns the count of newly rejected requests.
    """
    if not event.tidal_collection_playlist_id:
        return 0

    user = event.created_by
    playlist_tracks = get_playlist_tracks(db, user, event.tidal_collection_playlist_id)
    current_ids = {str(t.id) for t in playlist_tracks}

    synced = (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.submitted_during_collection == True,  # noqa: E712
            Request.tidal_collection_track_id.isnot(None),
            Request.status != RequestStatus.REJECTED.value,
        )
        .all()
    )

    count = 0
    for req in synced:
        if req.tidal_collection_track_id not in current_ids:
            req.status = RequestStatus.REJECTED.value
            count += 1

    if count > 0:
        db.commit()
        logger.info("Tidal poll: rejected %d removed track(s) for event %s", count, event.code)

    return count


def sync_request_to_tidal(
    db: Session,
    request: Request,
) -> TidalSyncResult:
    """Sync an accepted request to Tidal playlist."""
    event = request.event
    user = event.created_by

    if not event.tidal_sync_enabled:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Tidal sync not enabled for this event",
        )

    if not user.tidal_access_token:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Tidal account not linked",
        )

    playlist_id = create_event_playlist(db, user, event)
    if not playlist_id:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Failed to create Tidal playlist",
        )

    track = search_track(db, user, request.artist, request.song_title)
    if not track:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.NOT_FOUND,
            error="Track not found on Tidal",
        )

    if add_track_to_playlist(db, user, playlist_id, track.track_id):
        db.commit()
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.SYNCED,
            tidal_track_id=track.track_id,
        )
    else:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Failed to add track to playlist",
        )


def manual_link_track(
    db: Session,
    request: Request,
    tidal_track_id: str,
) -> TidalSyncResult:
    """Manually link a Tidal track to a request."""
    event = request.event
    user = event.created_by

    if not user.tidal_access_token:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Tidal account not linked",
        )

    playlist_id = event.tidal_playlist_id
    if not playlist_id:
        playlist_id = create_event_playlist(db, user, event)
        if not playlist_id:
            return TidalSyncResult(
                request_id=request.id,
                status=TidalSyncStatus.ERROR,
                error="Failed to create Tidal playlist",
            )

    if add_track_to_playlist(db, user, playlist_id, tidal_track_id):
        db.commit()
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.SYNCED,
            tidal_track_id=tidal_track_id,
        )
    else:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Failed to add track to playlist",
        )


@dataclass
class TidalPlaylistInfo:
    """Tidal playlist metadata."""

    id: str
    name: str
    num_tracks: int
    description: str | None = None
    cover_url: str | None = None
    source: str = "tidal"


def list_user_playlists(db: Session, user: User) -> list[TidalPlaylistInfo]:
    """List all playlists owned by the user on Tidal."""
    session = get_tidal_session(db, user)
    if not session:
        return []

    try:
        playlists = session.user.playlists()
        result = []
        for p in playlists:
            cover_url = None
            try:
                cover_url = p.image(480)
            except Exception:  # nosec B110 - cover art is optional
                pass
            result.append(
                TidalPlaylistInfo(
                    id=str(p.id),
                    name=p.name or "",
                    num_tracks=p.num_tracks or 0,
                    description=p.description,
                    cover_url=cover_url,
                )
            )
        return result
    except Exception as e:
        logger.error(f"Failed to list Tidal playlists: {e}")
        return []


def get_playlist_tracks(db: Session, user: User, playlist_id: str) -> list:
    """Get tracks from a Tidal playlist. Returns raw tidalapi.Track objects."""
    session = get_tidal_session(db, user)
    if not session:
        return []

    try:
        playlist = session.playlist(playlist_id)
        return playlist.tracks() or []
    except Exception as e:
        logger.error(f"Failed to get Tidal playlist tracks: {e}")
        return []


def search_tidal_by_isrc(
    db: Session,
    user: User,
    isrc: str,
) -> TidalSearchResult | None:
    """Look up a Tidal track by ISRC (exact match, no fuzzy needed).

    ISRC (International Standard Recording Code) uniquely identifies a
    recording across services. When we have a Spotify ISRC, this gives
    us the exact same recording on Tidal — bypassing fuzzy matching.
    """
    session = get_tidal_session(db, user)
    if not session:
        return None

    try:
        tracks = session.get_tracks_by_isrc(isrc)
        if tracks:
            return _track_to_result(tracks[0])
        return None
    except Exception as e:
        logger.error("Tidal ISRC lookup failed for %s: %s", isrc, type(e).__name__)
        return None


def get_tidal_track_by_id(
    db: Session,
    user: User,
    track_id: str,
) -> TidalSearchResult | None:
    """Fetch a single Tidal track by its ID (direct lookup, no search)."""
    session = get_tidal_session(db, user)
    if not session:
        return None

    try:
        track = session.track(int(track_id))
        if track:
            return _track_to_result(track)
        return None
    except Exception as e:
        logger.error("Tidal track fetch failed for %s: %s", track_id, type(e).__name__)
        return None


def search_tidal_tracks(
    db: Session,
    user: User,
    query: str,
    limit: int = 10,
) -> list[TidalSearchResult]:
    """Search Tidal for tracks."""
    session = get_tidal_session(db, user)
    if not session:
        return []

    try:
        results = session.search(query, models=[tidalapi.media.Track], limit=limit)
        return [_track_to_result(track) for track in results.get("tracks", [])]

    except Exception as e:
        logger.error(f"Tidal search failed: {e}")
        return []


def disconnect_tidal(db: Session, user: User) -> None:
    """Unlink Tidal account from user."""
    user.tidal_access_token = None
    user.tidal_refresh_token = None
    user.tidal_token_expires_at = None
    user.tidal_user_id = None
    db.commit()

    # Cancel any pending device login
    with _login_lock:
        _device_logins.pop(user.id, None)

    logger.info(f"Tidal disconnected for user {user.id}")
