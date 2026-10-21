"""Export and export-recovery routes for WrzDJSet."""

from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.api.setbuilder_common import get_owned_set_or_404 as _get_owned_or_404
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.setbuilder import (
    ExportAppleMusicIn,
    ExportAppleMusicOut,
    ExportAppleMusicRecoveryIn,
    ExportAppleMusicRecoveryOut,
    ExportFileIn,
    ExportPreflightIn,
    ExportPreflightOut,
    ExportSpotifyIn,
    ExportSpotifyOut,
    ExportTidalIn,
    ExportTidalOut,
    UnresolvedTrackOut,
    UnresolvedTracksError,
)
from app.services.apple_music import accounts as apple_music_accounts
from app.services.apple_music import catalog as apple_music_catalog
from app.services.apple_music import tokens as apple_music_tokens
from app.services.setbuilder.exports import (
    export_apple_music,
    export_common,
    export_files,
    export_spotify,
    export_tidal,
)
from app.services.spotify_oauth import refresh_access_token

router = APIRouter()


def _unresolved_out(
    tracks: list[export_common.ExportTrack],
    reason: Literal[
        "no_tidal_match", "no_spotify_match", "no_apple_music_match", "missing_metadata"
    ],
) -> list[UnresolvedTrackOut]:
    return [
        UnresolvedTrackOut(
            position=t.position,
            title=t.title,
            artist=t.artist,
            track_id=t.track_id,
            reason=reason,
        )
        for t in tracks
    ]


def _unresolved_409(unresolved: list[UnresolvedTrackOut]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "unresolved_tracks",
            "unresolved": [u.model_dump() for u in unresolved],
        },
    )


_UNRESOLVED_409_RESPONSE = {
    "model": UnresolvedTracksError,
    "description": "Unresolved tracks — retry with skip_unresolved=true to proceed.",
}


@router.post(
    "/sets/{set_id}/export/preflight",
    response_model=ExportPreflightOut,
    responses={
        502: {"description": "Apple Music catalog lookup failed."},
        503: {"description": "Apple Music is not configured."},
    },
)
@limiter.limit("5/minute")
def export_preflight(
    set_id: int,
    payload: ExportPreflightIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportPreflightOut:
    """Pre-export resolution check (tidal targets do live Tidal matching)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    source, tracks = export_common.collect_export_tracks(set_obj)

    if payload.target == "tidal":
        if not current_user.tidal_access_token:
            return ExportPreflightOut(
                target=payload.target,
                source=source,
                total=len(tracks),
                resolved_count=0,
                unresolved=[],
                tidal_connected=False,
            )
        resolved, unresolved = export_tidal.resolve_for_tidal(db, current_user, tracks)
        return ExportPreflightOut(
            target=payload.target,
            source=source,
            total=len(tracks),
            resolved_count=len(resolved),
            unresolved=_unresolved_out(unresolved, "no_tidal_match"),
            tidal_connected=True,
        )

    if payload.target == "spotify":
        if not refresh_access_token(db, current_user):
            return ExportPreflightOut(
                target=payload.target,
                source=source,
                total=len(tracks),
                resolved_count=0,
                unresolved=[],
                spotify_connected=False,
            )
        resolved, unresolved = export_spotify.resolve_for_spotify(db, current_user, tracks)
        return ExportPreflightOut(
            target=payload.target,
            source=source,
            total=len(tracks),
            resolved_count=len(resolved),
            unresolved=_unresolved_out(unresolved, "no_spotify_match"),
            spotify_connected=True,
        )

    if payload.target == "apple_music":
        if not apple_music_tokens.is_configured():
            raise HTTPException(status_code=503, detail="Apple Music is not configured")
        try:
            apple_music_accounts.stored_connection(db, current_user)
        except apple_music_tokens.AppleMusicNotConnected:
            return ExportPreflightOut(
                target=payload.target,
                source=source,
                total=len(tracks),
                resolved_count=0,
                unresolved=[],
                apple_music_connected=False,
            )
        try:
            resolved, unresolved = apple_music_catalog.resolve_tracks(db, current_user, tracks)
        except apple_music_tokens.AppleMusicNotConfigured:
            raise HTTPException(status_code=503, detail="Apple Music is not configured") from None
        except apple_music_tokens.AppleMusicError:
            raise HTTPException(
                status_code=502, detail="Apple Music catalog lookup failed"
            ) from None
        return ExportPreflightOut(
            target=payload.target,
            source=source,
            total=len(tracks),
            resolved_count=len(resolved),
            unresolved=_unresolved_out(unresolved, "no_apple_music_match"),
            apple_music_connected=True,
        )

    unresolved = export_files.file_unresolved(tracks)
    return ExportPreflightOut(
        target=payload.target,
        source=source,
        total=len(tracks),
        resolved_count=len(tracks) - len(unresolved),
        unresolved=_unresolved_out(unresolved, "missing_metadata"),
    )


@router.post(
    "/sets/{set_id}/export/tidal",
    response_model=ExportTidalOut,
    responses={
        400: {"description": "Tidal account not connected, or no exportable tracks."},
        409: _UNRESOLVED_409_RESPONSE,
        502: {"description": "Upstream Tidal export failed."},
    },
)
@limiter.limit("5/minute")
def export_set_tidal(
    set_id: int,
    payload: ExportTidalIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportTidalOut:
    """Export the setlist to a fresh Tidal playlist (DJ's existing OAuth)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if not current_user.tidal_access_token:
        raise HTTPException(status_code=400, detail="Tidal account not connected")
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    resolved, unresolved = export_tidal.resolve_for_tidal(db, current_user, tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "no_tidal_match"))
    if not resolved:
        raise HTTPException(status_code=400, detail="No resolvable tracks to export")

    try:
        outcome = export_tidal.export_to_tidal(db, current_user, set_obj, resolved)
    except export_tidal.TidalNotConnected:
        raise HTTPException(status_code=400, detail="Tidal account not connected") from None
    except export_tidal.TidalExportError:
        raise HTTPException(status_code=502, detail="Tidal export failed") from None

    return ExportTidalOut(
        playlist_id=outcome.playlist_id,
        playlist_url=outcome.playlist_url,
        added=outcome.added,
        skipped=len(unresolved),
        exported_at=set_obj.exported_at,
        status=set_obj.status,
    )


@router.post(
    "/sets/{set_id}/export/spotify",
    response_model=ExportSpotifyOut,
    responses={
        400: {"description": "Spotify account not connected, or no exportable tracks."},
        409: _UNRESOLVED_409_RESPONSE,
        502: {"description": "Upstream Spotify export failed."},
    },
)
@limiter.limit("5/minute")
def export_set_spotify(
    set_id: int,
    payload: ExportSpotifyIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportSpotifyOut:
    """Export the ordered setlist to a new private Spotify playlist."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if not refresh_access_token(db, current_user):
        raise HTTPException(status_code=400, detail="Spotify account not connected")
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    resolved, unresolved = export_spotify.resolve_for_spotify(db, current_user, tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "no_spotify_match"))
    if not resolved:
        raise HTTPException(status_code=400, detail="No resolvable tracks to export")

    try:
        outcome = export_spotify.export_to_spotify(db, current_user, set_obj, resolved)
    except export_spotify.SpotifyNotConnected:
        raise HTTPException(status_code=400, detail="Spotify account not connected") from None
    except export_spotify.SpotifyExportError:
        raise HTTPException(status_code=502, detail="Spotify export failed") from None

    return ExportSpotifyOut(
        playlist_id=outcome.playlist_id,
        playlist_url=outcome.playlist_url,
        added=outcome.added,
        skipped=len(unresolved),
        exported_at=set_obj.exported_at,
        status=set_obj.status,
    )


@router.post(
    "/sets/{set_id}/export/apple-music",
    response_model=ExportAppleMusicOut,
    responses={
        400: {"description": "Apple Music account not connected, or no exportable tracks."},
        409: {
            **_UNRESOLVED_409_RESPONSE,
            "description": (
                "Unresolved tracks require confirmation, or another export is in progress."
            ),
        },
        503: {"description": "Apple Music is not configured."},
        502: {"description": "Apple Music export failed or its outcome is uncertain."},
    },
)
@limiter.limit("5/minute")
def export_set_apple_music(
    set_id: int,
    payload: ExportAppleMusicIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportAppleMusicOut:
    """Create and verify one ordered Apple Music library playlist."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if not apple_music_tokens.is_configured():
        raise HTTPException(status_code=503, detail="Apple Music is not configured")
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")
    try:
        resolved, unresolved = apple_music_catalog.resolve_tracks(db, current_user, tracks)
    except apple_music_tokens.AppleMusicNotConnected:
        raise HTTPException(status_code=400, detail="Apple Music account not connected") from None
    except apple_music_tokens.AppleMusicNotConfigured:
        raise HTTPException(status_code=503, detail="Apple Music is not configured") from None
    except apple_music_tokens.AppleMusicError:
        raise HTTPException(status_code=502, detail="Apple Music catalog lookup failed") from None
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "no_apple_music_match"))
    if not resolved:
        raise HTTPException(status_code=400, detail="No resolvable tracks to export")
    try:
        outcome = export_apple_music.export_to_apple_music(db, current_user, set_obj, resolved)
    except apple_music_tokens.AppleMusicNotConnected:
        raise HTTPException(status_code=400, detail="Apple Music account not connected") from None
    except export_apple_music.AppleMusicExportInProgress:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "apple_music_export_in_progress",
                "message": "An Apple Music export is already in progress for this set.",
            },
        ) from None
    except export_apple_music.AppleMusicWriteUncertain as exc:
        detail = {
            "code": "apple_music_write_uncertain",
            "message": (
                "Apple Music export could not be confirmed. Check your library before trying again."
            ),
            "playlist_id": exc.playlist_id,
        }
        raise HTTPException(status_code=502, detail=detail) from None
    except apple_music_tokens.AppleMusicUserAuthorizationError:
        raise HTTPException(
            status_code=400,
            detail="Apple Music authorization was rejected. Reconnect your account.",
        ) from None
    except apple_music_tokens.AppleMusicError:
        raise HTTPException(status_code=502, detail="Apple Music export failed") from None
    return ExportAppleMusicOut(
        playlist_id=outcome.playlist_id,
        playlist_url=outcome.playlist_url,
        added=outcome.added,
        skipped=len(unresolved),
        exported_at=set_obj.exported_at,
        status=set_obj.status,
    )


@router.post(
    "/sets/{set_id}/export/apple-music/recovery",
    response_model=ExportAppleMusicRecoveryOut,
)
@limiter.limit("5/minute")
def reconcile_apple_music_export(
    set_id: int,
    payload: ExportAppleMusicRecoveryIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportAppleMusicRecoveryOut:
    """Let the DJ reconcile an ambiguous export after checking their Apple library."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    reconciled = export_apple_music.reconcile_uncertain_export(
        db,
        set_obj,
        playlist_id=payload.playlist_id if payload.action == "playlist_found" else None,
        confirm_playlist_absent=payload.action == "playlist_absent",
    )
    if not reconciled:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "apple_music_recovery_unavailable",
                "message": "This set has no export awaiting reconciliation.",
            },
        )
    return ExportAppleMusicRecoveryOut(
        status="exported" if payload.action == "playlist_found" else "ready_to_retry"
    )


# Engine DJ and Lexicon both import Rekordbox DJ_PLAYLISTS XML — no separate
# native format exists — so they reuse the same renderer under distinct keys.
_FILE_RENDERERS = {
    "rekordbox": (export_files.render_rekordbox_xml, "application/xml", "xml"),
    "enginedj": (export_files.render_rekordbox_xml, "application/xml", "xml"),
    "lexicon": (export_files.render_rekordbox_xml, "application/xml", "xml"),
    "m3u": (export_files.render_m3u, "audio/x-mpegurl", "m3u8"),
    "txt": (export_files.render_txt, "text/plain", "txt"),
}


_FILE_DOWNLOAD_SCHEMA = {"schema": {"type": "string", "format": "binary"}}


@router.post(
    "/sets/{set_id}/export/file",
    response_class=Response,
    responses={
        200: {
            "description": "Setlist file download (Content-Disposition: attachment).",
            "content": {
                "application/xml": _FILE_DOWNLOAD_SCHEMA,
                "audio/x-mpegurl": _FILE_DOWNLOAD_SCHEMA,
                "text/plain": _FILE_DOWNLOAD_SCHEMA,
            },
        },
        400: {"description": "Set has no tracks to export."},
        409: _UNRESOLVED_409_RESPONSE,
    },
)
@limiter.limit("10/minute")
def export_set_file(
    set_id: int,
    payload: ExportFileIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Download the setlist as Rekordbox XML, M3U8, or plaintext."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    unresolved = export_files.file_unresolved(tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "missing_metadata"))
    exportable = [t for t in tracks if t.has_metadata]

    render, media_type, ext = _FILE_RENDERERS[payload.format]
    content = render(set_obj.name, exportable)
    filename = export_files.safe_filename(set_obj.name, ext)
    return Response(
        content=content,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
