"""Public Tidal provider API; implementations live in responsibility-specific modules."""

from app.schemas.tidal import TidalSearchResult, TidalSyncResult
from app.services.providers.tidal_account import (
    DEVICE_LOGIN_TTL_MINUTES,
    cancel_device_login,
    check_device_login,
    disconnect_tidal,
    get_tidal_session,
    start_device_login,
)
from app.services.providers.tidal_catalog import TidalFetchError, TidalPlaylistInfo
from app.services.providers.tidal_playlists import (
    add_track_to_playlist,
    add_tracks_to_playlist,
    create_event_playlist,
    ensure_collection_playlist,
    poll_tidal_collection_removals,
    remove_collection_tracks_batch,
    remove_track_from_collection_playlist,
)
from app.services.providers.tidal_request_sync import (
    manual_link_track,
    sync_collection_requests_batch,
    sync_request_to_tidal,
)
from app.services.providers.tidal_results import get_artist_name
from app.services.providers.tidal_search import (
    get_playlist_tracks,
    get_tidal_track_by_id,
    list_user_playlists,
    search_tidal_by_isrc,
    search_tidal_tracks,
    search_track,
)

__all__ = [
    "DEVICE_LOGIN_TTL_MINUTES",
    "TidalFetchError",
    "TidalPlaylistInfo",
    "TidalSearchResult",
    "TidalSyncResult",
    "add_track_to_playlist",
    "add_tracks_to_playlist",
    "cancel_device_login",
    "check_device_login",
    "create_event_playlist",
    "disconnect_tidal",
    "ensure_collection_playlist",
    "get_artist_name",
    "get_playlist_tracks",
    "get_tidal_session",
    "get_tidal_track_by_id",
    "list_user_playlists",
    "manual_link_track",
    "poll_tidal_collection_removals",
    "remove_collection_tracks_batch",
    "remove_track_from_collection_playlist",
    "search_track",
    "search_tidal_by_isrc",
    "search_tidal_tracks",
    "start_device_login",
    "sync_collection_requests_batch",
    "sync_request_to_tidal",
]
