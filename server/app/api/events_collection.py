"""Collection scheduling, review, and bulk-enrichment routes for events."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_event_for_dj_or_admin
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.rate_limit import limiter
from app.models.event import Event
from app.models.request import RequestStatus
from app.schemas.collect import (
    BulkReviewRequest,
    BulkReviewResponse,
    CollectionSettingsResponse,
    PendingReviewResponse,
    PendingReviewRow,
    UpdateCollectionSettings,
)
from app.schemas.request import RequestSort, SortDirection
from app.services.collect import (
    collection_settings_payload,
    execute_bulk_review,
    get_sorted_pending_review,
    update_collection_settings,
)
from app.services.providers.tidal import remove_collection_tracks_batch
from app.services.request_sort import DEFAULT_SORT_DIRECTION
from app.services.sync.orchestrator import (
    enrich_with_fresh_session,
    sync_collection_requests_with_fresh_session,
    sync_requests_with_fresh_session,
)
from app.services.system_settings import get_system_settings

router = APIRouter()


@router.get("/{code}/collection", response_model=CollectionSettingsResponse)
def get_collection_settings(
    event: Event = Depends(get_event_for_dj_or_admin),
) -> CollectionSettingsResponse:
    """Get pre-event collection scheduling settings."""
    return collection_settings_payload(event)


@router.patch("/{code}/collection", response_model=CollectionSettingsResponse)
def update_collection_settings_endpoint(
    payload: UpdateCollectionSettings,
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),
) -> CollectionSettingsResponse:
    """Update pre-event collection scheduling settings."""
    update_collection_settings(db, event, payload)
    return collection_settings_payload(event)


@router.post("/{code}/collection/sync-tidal")
@limiter.limit("5/minute")
def sync_collection_to_tidal(
    request: Request,
    background_tasks: BackgroundTasks,
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Sync all non-rejected collection-phase requests to the DJ's Tidal playlist.

    Includes pending (new) and accepted requests so the DJ can listen to guest
    suggestions on Tidal before the review step.  Already-synced tracks are
    silently skipped inside sync_requests_batch.
    """
    sys_settings = get_system_settings(db)
    if not sys_settings.tidal_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tidal integration is currently unavailable",
        )

    user = event.created_by
    if not user.tidal_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidal account not linked",
        )

    if not event.tidal_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidal sync not enabled for this event",
        )

    eligible = [
        r
        for r in event.requests
        if r.submitted_during_collection and r.status != RequestStatus.REJECTED.value
    ]

    if eligible:
        # Pass IDs so the task re-queries in a fresh session instead of holding
        # the request-scoped connection through the Tidal API calls (issue #505).
        background_tasks.add_task(
            sync_collection_requests_with_fresh_session, event.id, [r.id for r in eligible]
        )

    return {"queued": len(eligible)}


@router.get("/{code}/pending-review", response_model=PendingReviewResponse)
def pending_review(
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    sort: RequestSort | None = None,
    direction: SortDirection | None = None,
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),
) -> PendingReviewResponse:
    """Paginated pending-review source for DJ bulk-review (issue #478).

    ``total`` is the true count of pending rows before pagination, so the
    Pre-Event tab never shows a capped page length as the queue size. Default
    ordering stays the vote-ranked review order; bulk actions still operate
    server-side against the full filtered set, not the loaded page.
    """
    # Resolve the direction up front so the response metadata reflects what was
    # actually applied: when sort is omitted (default review order) there is no
    # direction, even if the client passed one (issue #478).
    resolved = (direction or DEFAULT_SORT_DIRECTION[sort]) if sort else None
    rows, total = get_sorted_pending_review(
        db, event.id, sort=sort, direction=resolved, limit=limit, offset=offset
    )
    return PendingReviewResponse(
        requests=[
            PendingReviewRow(
                id=r.id,
                song_title=r.song_title,
                artist=r.artist,
                artwork_url=r.artwork_url,
                vote_count=r.vote_count,
                nickname=r.nickname,
                created_at=r.created_at,
                note=r.note,
                status=r.status,
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=resolved,
    )


@router.post("/{code}/bulk-review", response_model=BulkReviewResponse)
def bulk_review(
    payload: BulkReviewRequest,
    background_tasks: BackgroundTasks,
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),
) -> BulkReviewResponse:
    accepted, rejected, accepted_rows, rejected_rows = execute_bulk_review(db, event.id, payload)
    # Enrich + sync accepted requests. Guest-collect submissions arrive without
    # BPM/key/genre. enrich_request_metadata fills those in directly (Tidal/
    # Beatport/MusicBrainz cascade) — this works regardless of whether the DJ
    # has any sync adapters connected. sync_requests_batch only adds to a
    # connected user's playlists; if no adapters, it returns early as a no-op.
    # Pass IDs through the fresh-session helpers so each task opens and closes its
    # own connection instead of pinning the request-scoped one across N enrich
    # calls + the batch sync (issue #505).
    if accepted_rows:
        for row in accepted_rows:
            background_tasks.add_task(enrich_with_fresh_session, row.id)
        background_tasks.add_task(sync_requests_with_fresh_session, [r.id for r in accepted_rows])

    # Direction 1: remove rejected+synced tracks from the Tidal collection playlist.
    # Requires bidirectional sync to be enabled — tidal_sync_enabled alone is not enough.
    if event.tidal_sync_enabled and event.tidal_collection_bidirectional:
        track_ids_to_remove = [
            r.tidal_collection_track_id for r in rejected_rows if r.tidal_collection_track_id
        ]
        if track_ids_to_remove:
            background_tasks.add_task(
                _remove_collection_tracks_with_fresh_session,
                event.id,
                track_ids_to_remove,
            )

    return BulkReviewResponse(accepted=accepted, rejected=rejected, unchanged=0)


ENRICH_ALL_BATCH_LIMIT = 25


def _remove_collection_tracks_with_fresh_session(event_id: int, track_ids: list[str]) -> None:
    """Run remove_collection_tracks_batch in its own DB session.

    Re-queries the event (for its DJ + collection playlist) by ID so no
    request-scoped session is pinned during the Tidal removal calls (issue #505).
    """
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        event = session.get(Event, event_id)
        if not event:
            return
        remove_collection_tracks_batch(session, event.created_by, event, track_ids)
    finally:
        session.close()


@router.post("/{code}/enrich-all")
def enrich_all_requests(
    background_tasks: BackgroundTasks,
    event: Event = Depends(get_event_for_dj_or_admin),
) -> dict[str, int]:
    """Queue enrichment for up to ENRICH_ALL_BATCH_LIMIT requests missing BPM, key, or genre.

    Batched to avoid exhausting the connection pool when many tracks need enrichment.
    Returns `remaining` so the caller can re-invoke until 0.
    """
    candidates = [
        r for r in event.requests if r.bpm is None or r.musical_key is None or r.genre is None
    ]
    batch = candidates[:ENRICH_ALL_BATCH_LIMIT]
    for row in batch:
        background_tasks.add_task(enrich_with_fresh_session, row.id)
    return {"queued": len(batch), "remaining": max(0, len(candidates) - len(batch))}
