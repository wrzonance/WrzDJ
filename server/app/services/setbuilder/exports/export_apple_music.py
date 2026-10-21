"""Apple Music playlist export for WrzDJSet."""

import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.provider_connection import UserProviderConnection
from app.models.set import Set
from app.models.user import User
from app.services.apple_music import accounts as apple_music_accounts
from app.services.apple_music import tokens as apple_music_tokens
from app.services.setbuilder.exports.export_common import ExportTrack

_PLAYLIST_ID_RE = re.compile(r"^p\.[A-Za-z0-9_-]{1,98}$")
_GLOBAL_ID_RE = re.compile(r"^pl\.[A-Za-z0-9_-]{1,128}$")
_VERIFY_DELAYS_SECONDS = (0.0, 0.25, 0.75, 1.5, 3.0)
logger = logging.getLogger(__name__)


class AppleMusicWriteUncertain(Exception):
    """Apple may have created the playlist, but the response was not conclusive."""

    def __init__(self, playlist_id: str | None = None):
        super().__init__("Apple Music playlist creation could not be confirmed")
        self.playlist_id = playlist_id


class AppleMusicExportInProgress(apple_music_tokens.AppleMusicError):
    """Another request already owns the one-shot playlist creation claim."""


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
            relationships = item.get("relationships")
            catalog = relationships.get("catalog") if isinstance(relationships, dict) else None
            catalog_data = catalog.get("data") if isinstance(catalog, dict) else None
            catalog_id = catalog_data.get("id") if isinstance(catalog_data, dict) else None
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
    page_limit = max(1, len(expected_ids))
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


def _persist_created_playlist_id(
    db: Session, set_obj: Set, attempt_id: str, playlist_id: str
) -> None:
    """Persist recovery identity only while this attempt still owns the claim."""
    try:
        result = db.execute(
            update(Set)
            .where(
                Set.id == set_obj.id,
                Set.apple_music_export_pending.is_(True),
                Set.apple_music_export_attempt_id == attempt_id,
            )
            .values(apple_music_export_recovery_playlist_id=playlist_id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            raise AppleMusicWriteUncertain(playlist_id)
        db.commit()
    except AppleMusicWriteUncertain:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise AppleMusicWriteUncertain(playlist_id) from None


def _claim_export(db: Session, set_obj: Set) -> str | None:
    """Atomically reserve a set before a create request, including stale callers."""
    attempt_id = uuid4().hex
    try:
        result = db.execute(
            update(Set)
            .where(
                Set.id == set_obj.id,
                Set.apple_music_export_pending.is_(False),
            )
            .values(
                apple_music_export_pending=True,
                apple_music_export_uncertain=False,
                apple_music_export_attempt_id=attempt_id,
                apple_music_export_recovery_playlist_id=None,
            )
            .execution_options(synchronize_session=False)
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise apple_music_tokens.AppleMusicError("Could not reserve this set for export") from exc
    if result.rowcount != 1:
        db.rollback()
        return None
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise apple_music_tokens.AppleMusicError("Could not reserve this set for export") from None
    return attempt_id


def _existing_claim(db: Session, set_obj: Set) -> tuple[bool, str | None]:
    claim = db.execute(
        select(Set.apple_music_export_uncertain, Set.apple_music_export_recovery_playlist_id).where(
            Set.id == set_obj.id, Set.apple_music_export_pending.is_(True)
        )
    ).first()
    return (bool(claim[0]), claim[1]) if claim else (False, None)


def _mark_export_uncertain(
    db: Session, set_obj: Set, attempt_id: str, playlist_id: str | None = None
) -> None:
    set_id = set_obj.id
    values: dict[str, object] = {"apple_music_export_uncertain": True}
    if playlist_id is not None:
        values["apple_music_export_recovery_playlist_id"] = playlist_id
    try:
        result = db.execute(
            update(Set)
            .where(
                Set.id == set_obj.id,
                Set.apple_music_export_pending.is_(True),
                Set.apple_music_export_attempt_id == attempt_id,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            db.commit()
        else:
            db.rollback()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not record Apple Music export uncertainty for set %s", set_id)


def reconcile_uncertain_export(
    db: Session,
    set_obj: Set,
    *,
    playlist_id: str | None = None,
    confirm_playlist_absent: bool = False,
) -> bool:
    """Apply the user's explicit finding after an ambiguous Apple Music write."""
    if playlist_id is None and not confirm_playlist_absent:
        return False
    if playlist_id is not None and not _PLAYLIST_ID_RE.fullmatch(playlist_id):
        return False
    values: dict[str, object] = {
        "apple_music_export_pending": False,
        "apple_music_export_uncertain": False,
        "apple_music_export_attempt_id": None,
        "apple_music_export_recovery_playlist_id": None,
    }
    if playlist_id is not None:
        values.update(
            apple_music_playlist_id=playlist_id,
            exported_at=utcnow(),
            status="exported",
        )
    try:
        result = db.execute(
            update(Set)
            .where(
                Set.id == set_obj.id,
                Set.apple_music_export_pending.is_(True),
                Set.apple_music_export_uncertain.is_(True),
                Set.apple_music_export_attempt_id.is_not(None),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            return False
        db.commit()
        db.refresh(set_obj)
        return True
    except SQLAlchemyError:
        db.rollback()
        raise apple_music_tokens.AppleMusicError("Could not reconcile Apple Music export") from None


def _release_claim(db: Session, set_obj: Set, attempt_id: str) -> None:
    set_id = set_obj.id
    try:
        db.execute(
            update(Set)
            .where(
                Set.id == set_obj.id,
                Set.apple_music_export_pending.is_(True),
                Set.apple_music_export_attempt_id == attempt_id,
            )
            .values(
                apple_music_export_pending=False,
                apple_music_export_uncertain=False,
                apple_music_export_attempt_id=None,
                apple_music_export_recovery_playlist_id=None,
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not release Apple Music export claim for set %s", set_id)


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
    attempt_id = _claim_export(db, set_obj)
    if attempt_id is None:
        is_uncertain, recovery_id = _existing_claim(db, set_obj)
        if is_uncertain:
            raise AppleMusicWriteUncertain(recovery_id)
        raise AppleMusicExportInProgress("An Apple Music export is already in progress")
    track_data = [{"id": song_id, "type": "songs"} for _, song_id in resolved]
    try:
        payload = apple_music_tokens.apple_post(
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
        _release_claim(db, set_obj, attempt_id)
        apple_music_accounts.mark_reauthorization_if_current(db, user, generation)
        raise
    except apple_music_tokens.AppleMusicRequestUncertain as exc:
        _mark_export_uncertain(db, set_obj, attempt_id)
        raise AppleMusicWriteUncertain from exc
    except apple_music_tokens.AppleMusicError:
        _release_claim(db, set_obj, attempt_id)
        raise

    playlist = _playlist_response(payload)
    if playlist is None:
        playlist_id = _playlist_id(payload)
        if playlist_id:
            try:
                _persist_created_playlist_id(db, set_obj, attempt_id, playlist_id)
            except AppleMusicWriteUncertain:
                _mark_export_uncertain(db, set_obj, attempt_id, playlist_id)
                raise
        _mark_export_uncertain(db, set_obj, attempt_id, playlist_id)
        raise AppleMusicWriteUncertain(playlist_id)
    playlist_id, path = playlist
    try:
        _persist_created_playlist_id(db, set_obj, attempt_id, playlist_id)
    except AppleMusicWriteUncertain:
        _mark_export_uncertain(db, set_obj, attempt_id, playlist_id)
        raise
    expected_ids = [song_id for _, song_id in resolved]
    verified = False
    for delay in _VERIFY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            verified = _tracks_match(db, developer_token, user_token, playlist_id, expected_ids)
        except apple_music_tokens.AppleMusicUserAuthorizationError:
            apple_music_accounts.mark_reauthorization_if_current(db, user, generation)
            _mark_export_uncertain(db, set_obj, attempt_id, playlist_id)
            raise AppleMusicWriteUncertain(playlist_id) from None
        except apple_music_tokens.AppleMusicError:
            verified = False
        if verified:
            break
    if not verified:
        _mark_export_uncertain(db, set_obj, attempt_id, playlist_id)
        raise AppleMusicWriteUncertain(playlist_id)
    completed_at = utcnow()
    try:
        result = db.execute(
            update(Set)
            .where(
                Set.id == set_obj.id,
                Set.apple_music_export_pending.is_(True),
                Set.apple_music_export_attempt_id == attempt_id,
                Set.apple_music_export_recovery_playlist_id == playlist_id,
            )
            .values(
                apple_music_playlist_id=playlist_id,
                apple_music_export_pending=False,
                apple_music_export_uncertain=False,
                apple_music_export_attempt_id=None,
                apple_music_export_recovery_playlist_id=None,
                exported_at=completed_at,
                status="exported",
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise AppleMusicWriteUncertain(playlist_id)
        db.commit()
    except AppleMusicWriteUncertain:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        _mark_export_uncertain(db, set_obj, attempt_id, playlist_id)
        raise AppleMusicWriteUncertain(playlist_id) from exc
    db.refresh(set_obj)
    return AppleMusicExportOutcome(
        playlist_id=playlist_id,
        playlist_url=f"https://music.apple.com/{storefront}/{path}" if path else None,
        added=len(expected_ids),
    )
