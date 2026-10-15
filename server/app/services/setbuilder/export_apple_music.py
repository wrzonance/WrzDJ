"""Apple Music playlist export for WrzDJSet."""

import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.provider_connection import UserProviderConnection
from app.models.set import Set
from app.models.user import User
from app.services import apple_music_accounts, apple_music_tokens
from app.services.setbuilder.export_common import ExportTrack

_PLAYLIST_ID_RE = re.compile(r"^p\.[A-Za-z0-9_-]{1,98}$")
_GLOBAL_ID_RE = re.compile(r"^pl\.[A-Za-z0-9_-]{1,128}$")
_VERIFY_DELAYS_SECONDS = (0.0, 0.25, 0.75)


class AppleMusicWriteUncertain(Exception):
    """Apple may have created the playlist, but the response was not conclusive."""

    def __init__(self, playlist_id: str | None = None):
        super().__init__("Apple Music playlist creation could not be confirmed")
        self.playlist_id = playlist_id


@dataclass(frozen=True)
class AppleMusicExportOutcome:
    playlist_id: str
    playlist_url: str | None
    added: int


def _playlist_id(payload: dict[str, object]) -> str | None:
    data = payload.get("data")
    item = data[0] if isinstance(data, list) and data else None
    if not isinstance(item, dict) or item.get("type") != "library-playlists":
        return None
    playlist_id = item.get("id")
    if not isinstance(playlist_id, str) or not _PLAYLIST_ID_RE.fullmatch(playlist_id):
        return None
    return playlist_id


def _playlist_response(
    payload: dict[str, object],
) -> tuple[str, str | None] | None:
    playlist_id = _playlist_id(payload)
    if playlist_id is None:
        return None
    data = payload.get("data")
    item = data[0]
    attributes = item.get("attributes")
    play_params = attributes.get("playParams") if isinstance(attributes, dict) else None
    global_id = play_params.get("globalId") if isinstance(play_params, dict) else None
    if isinstance(global_id, str) and _GLOBAL_ID_RE.fullmatch(global_id):
        path = f"playlist/{quote(global_id, safe='')}"
    else:
        path = None
    return playlist_id, path


def _catalog_ids(payload: dict[str, object]) -> tuple[list[str], str | None] | None:
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    ids: list[str] = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "library-songs":
            return None
        attributes = item.get("attributes")
        play_params = attributes.get("playParams") if isinstance(attributes, dict) else None
        catalog_id = play_params.get("catalogId") if isinstance(play_params, dict) else None
        if not isinstance(catalog_id, str):
            return None
        ids.append(catalog_id)
    next_page = payload.get("next")
    return ids, next_page if isinstance(next_page, str) else None


def _tracks_match(
    db: Session,
    developer_token: str,
    music_user_token: str,
    playlist_id: str,
    expected_ids: list[str],
) -> bool:
    collected: list[str] = []
    offset: str | None = None
    page_limit = max(1, (len(expected_ids) + 99) // 100)
    for _ in range(page_limit):
        params = {"include": "catalog", "limit": "100"}
        if offset:
            params["offset"] = offset
        payload = apple_music_tokens.apple_get(
            f"/me/library/playlists/{playlist_id}/tracks",
            developer_token,
            music_user_token=music_user_token,
            params=params,
        )
        parsed = _catalog_ids(payload)
        if parsed is None:
            return False
        page_ids, next_page = parsed
        collected.extend(page_ids)
        if len(collected) > len(expected_ids):
            return False
        if not next_page:
            return collected == expected_ids
        next_parts = urlsplit(next_page)
        expected_path = f"/v1/me/library/playlists/{playlist_id}/tracks"
        if next_parts.path != expected_path:
            return False
        next_offsets = parse_qs(next_parts.query).get("offset")
        if not next_offsets or not next_offsets[0]:
            return False
        offset = next_offsets[0]
    return False


def _persist_uncertain_playlist_id(db: Session, set_obj: Set, playlist_id: str) -> None:
    set_obj.apple_music_playlist_id = playlist_id
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()


def export_to_apple_music(
    db: Session,
    user: User,
    set_obj: Set,
    resolved: list[tuple[ExportTrack, str]],
) -> AppleMusicExportOutcome:
    """Create a complete playlist in one Apple request and persist only confirmed success."""
    if not resolved:
        raise apple_music_tokens.AppleMusicError("No resolved tracks to export")
    if set_obj.apple_music_playlist_id:
        raise AppleMusicWriteUncertain(set_obj.apple_music_playlist_id)
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
        playlist_id = _playlist_id(payload)
        if playlist_id:
            _persist_uncertain_playlist_id(db, set_obj, playlist_id)
        raise AppleMusicWriteUncertain(playlist_id)
    playlist_id, path = playlist
    expected_ids = [song_id for _, song_id in resolved]
    verified = False
    for delay in _VERIFY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            verified = _tracks_match(db, developer_token, user_token, playlist_id, expected_ids)
        except apple_music_tokens.AppleMusicUserAuthorizationError:
            apple_music_accounts.mark_reauthorization_if_current(db, user, generation)
            _persist_uncertain_playlist_id(db, set_obj, playlist_id)
            raise AppleMusicWriteUncertain(playlist_id) from None
        except apple_music_tokens.AppleMusicError:
            verified = False
        if verified:
            break
    if not verified:
        _persist_uncertain_playlist_id(db, set_obj, playlist_id)
        raise AppleMusicWriteUncertain(playlist_id)
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
        playlist_url=f"https://music.apple.com/{storefront}/{path}" if path else None,
        added=len(expected_ids),
    )
