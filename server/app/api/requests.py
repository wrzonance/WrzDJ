from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.request import RequestStatus
from app.models.user import User
from app.schemas.request import RequestOut, RequestUpdate
from app.services.event_bus import publish_event
from app.services.now_playing import (
    add_manual_play,
    clear_manual_now_playing,
    set_manual_now_playing,
)
from app.services.request import (
    InvalidStatusTransitionError,
    clear_other_playing_requests,
    clear_request_metadata,
    delete_request,
    get_request_by_id,
    update_request_status,
)
from app.services.sync.orchestrator import enrich_request_metadata, sync_request_to_services
from app.services.sync.registry import get_connected_adapters
from app.services.tidal import remove_track_from_collection_playlist

router = APIRouter()


def _request_to_out(r) -> RequestOut:
    return RequestOut(
        id=r.id,
        event_id=r.event_id,
        song_title=r.song_title,
        artist=r.artist,
        source=r.source,
        source_url=r.source_url,
        artwork_url=r.artwork_url,
        note=r.note,
        nickname=r.nickname,
        status=r.status,
        created_at=r.created_at,
        updated_at=r.updated_at,
        raw_search_query=r.raw_search_query,
        sync_results_json=r.sync_results_json,
        vote_count=r.vote_count,
        genre=r.genre,
        bpm=r.bpm,
        musical_key=r.musical_key,
    )


@router.patch("/{request_id}", response_model=RequestOut)
@limiter.limit("30/minute")
def update_request(
    request_id: int,
    update_data: RequestUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RequestOut:
    request = get_request_by_id(db, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    # Verify ownership through event
    if request.event.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this request")

    try:
        updated = update_request_status(db, request, update_data.status)
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Sync to connected services when request is accepted (non-blocking background task)
    if update_data.status == RequestStatus.ACCEPTED:
        if get_connected_adapters(request.event.created_by):
            background_tasks.add_task(sync_request_to_services, db, request)

    # Remove from Tidal collection playlist when a synced collection request is rejected.
    # Requires bidirectional sync to be enabled — tidal_sync_enabled alone is not enough.
    if (
        update_data.status == RequestStatus.REJECTED
        and request.submitted_during_collection
        and request.tidal_collection_track_id
        and request.event.tidal_sync_enabled
        and request.event.tidal_collection_bidirectional
    ):
        background_tasks.add_task(
            remove_track_from_collection_playlist,
            db,
            request.event.created_by,
            request.event,
            request.tidal_collection_track_id,
        )

    # Auto-set now_playing when a request is set to "playing"
    if update_data.status == RequestStatus.PLAYING:
        clear_other_playing_requests(db, request.event_id, request.id)
        set_manual_now_playing(db, request.event_id, request)
    # Clear now_playing when the current song is marked as "played" and add to history
    elif update_data.status == RequestStatus.PLAYED:
        clear_manual_now_playing(db, request.event_id, request.id)
        add_manual_play(db, request.event, request)

    publish_event(
        request.event.code,
        "request_status_changed",
        {
            "request_id": updated.id,
            "status": updated.status,
            "title": updated.song_title,
            "artist": updated.artist,
        },
    )

    return _request_to_out(updated)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_request_endpoint(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete a single request. Ownership verified via event."""
    song_request = get_request_by_id(db, request_id)
    if not song_request:
        raise HTTPException(status_code=404, detail="Request not found")

    if song_request.event.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this request")

    delete_request(db, song_request)


@router.post("/{request_id}/refresh-metadata", response_model=RequestOut)
@limiter.limit("10/minute")
def refresh_request_metadata(
    request_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RequestOut:
    """Clear existing metadata and re-enrich from external services."""
    song_request = get_request_by_id(db, request_id)
    if not song_request:
        raise HTTPException(status_code=404, detail="Request not found")

    if song_request.event.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this request")

    cleared = clear_request_metadata(db, song_request)
    background_tasks.add_task(enrich_request_metadata, db, cleared.id)

    return _request_to_out(cleared)
