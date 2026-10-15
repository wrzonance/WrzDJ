"""Apple Music playlist export for WrzDJSet."""

import re
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.provider_connection import UserProviderConnection
from app.models.set import Set
from app.models.user import User
from app.services import apple_music_accounts, apple_music_tokens
from app.services.setbuilder.export_common import ExportTrack

_PLAYLIST_ID_RE = re.compile(r"^p\.[A-Za-z0-9_-]{1,128}$")
_GLOBAL_ID_RE = re.compile(r"^pl\.[A-Za-z0-9_-]{1,128}$")


class AppleMusicWriteUncertain(Exception):
    """Apple may have created the playlist, but the response was not conclusive."""


@dataclass(frozen=True)
class AppleMusicExportOutcome:
    playlist_id: str
    playlist_url: str
    added: int


def _playlist_response(payload: dict[str, object]) -> tuple[str, str] | None:
    data = payload.get("data")
    item = data[0] if isinstance(data, list) and data else None
    if not isinstance(item, dict) or item.get("type") != "library-playlists":
        return None
    playlist_id = item.get("id")
    if not isinstance(playlist_id, str) or not _PLAYLIST_ID_RE.fullmatch(playlist_id):
        return None
    attributes = item.get("attributes")
    play_params = attributes.get("playParams") if isinstance(attributes, dict) else None
    global_id = play_params.get("globalId") if isinstance(play_params, dict) else None
    if isinstance(global_id, str) and _GLOBAL_ID_RE.fullmatch(global_id):
        path = f"playlist/{quote(global_id, safe='')}"
    else:
        path = f"library/playlist/{quote(playlist_id, safe='')}"
    return playlist_id, path


def export_to_apple_music(
    db: Session,
    user: User,
    set_obj: Set,
    resolved: list[tuple[ExportTrack, str]],
) -> AppleMusicExportOutcome:
    """Create a complete playlist in one Apple request and persist only confirmed success."""
    if not resolved:
        raise apple_music_tokens.AppleMusicError("No resolved tracks to export")
    connection = (
        db.query(UserProviderConnection)
        .filter_by(user_id=user.id, provider_id="apple_music")
        .one_or_none()
    )
    user_token, storefront = apple_music_accounts.stored_connection(db, user)
    if connection is None:
        raise apple_music_tokens.AppleMusicNotConnected
    generation = connection.authorization_generation
    developer_token, _ = apple_music_tokens.create_developer_token()
    track_data = [{"id": song_id, "type": "songs"} for _, song_id in resolved]
    try:
        payload = apple_music_tokens.apple_request(
            "POST",
            "/me/library/playlists",
            developer_token,
            music_user_token=user_token,
            json_body={
                "attributes": {
                    "name": f"WrzDJ Set: {set_obj.name}",
                    "description": "Exported from WrzDJ Set Builder",
                },
                "relationships": {"tracks": {"data": track_data}},
            },
        )
    except apple_music_tokens.AppleMusicUserAuthorizationError:
        apple_music_accounts.mark_reauthorization_if_current(db, user, generation)
        raise
    except apple_music_tokens.AppleMusicRequestUncertain as exc:
        raise AppleMusicWriteUncertain from exc

    playlist = _playlist_response(payload)
    if playlist is None:
        raise AppleMusicWriteUncertain
    playlist_id, path = playlist
    set_obj.apple_music_playlist_id = playlist_id
    set_obj.exported_at = utcnow()
    set_obj.status = "exported"
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppleMusicWriteUncertain from exc
    return AppleMusicExportOutcome(
        playlist_id=playlist_id,
        playlist_url=f"https://music.apple.com/{storefront}/{path}",
        added=len(track_data),
    )
