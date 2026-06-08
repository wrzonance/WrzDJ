"""Public API endpoints for kiosk display (no authentication required)."""

import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.rate_limit import get_guest_id, limiter
from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.request import Request as SongRequest
from app.models.request import RequestStatus
from app.services.event import (
    EventLookupResult,
    get_event_by_join_code_with_status,
    get_event_by_public_code_with_status,
)
from app.services.now_playing import get_now_playing, is_now_playing_hidden
from app.services.request import get_requests_by_guest

router = APIRouter()
settings = get_settings()


def _build_public_banner(request: Request, event: Event) -> tuple[str | None, list[str] | None]:
    """Build (banner_url, banner_colors) from an event for guest/kiosk responses.
    api_base is the API server's own base URL (http->https when proxied). Colors
    parse is defensive: malformed JSON yields None, never a 500."""
    if not event.banner_filename:
        return None, None
    api_base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https" and api_base.startswith("http://"):
        api_base = "https://" + api_base[len("http://") :]
    banner_url = f"{api_base}/uploads/{event.banner_filename}"
    banner_colors = None
    if event.banner_colors:
        try:
            parsed = json.loads(event.banner_colors)
            if isinstance(parsed, list) and all(isinstance(c, str) for c in parsed):
                banner_colors = parsed
        except (json.JSONDecodeError, TypeError):
            banner_colors = None
    return banner_url, banner_colors


class PublicEventInfo(BaseModel):
    code: str
    name: str


class PublicRequestInfo(BaseModel):
    id: int
    title: str
    artist: str
    artwork_url: str | None
    nickname: str | None = None
    vote_count: int = 0
    bpm: int | None = None
    musical_key: str | None = None
    genre: str | None = None
    requester_verified: bool = False


class GuestRequestInfo(PublicRequestInfo):
    status: Literal["new", "accepted"]


class GuestNowPlaying(BaseModel):
    title: str
    artist: str
    album_art_url: str | None
    source: str


class GuestRequestListResponse(BaseModel):
    event: PublicEventInfo
    requests: list[GuestRequestInfo]
    now_playing: GuestNowPlaying | None = None
    # Full count of NEW/ACCEPTED requests for the event, independent of the
    # page returned in `requests`. Lets the client offer "load more" / show a
    # truthful song count instead of inferring from the (capped) page length.
    total: int = 0


class MyRequestInfo(BaseModel):
    id: int
    title: str
    artist: str
    artwork_url: str | None
    status: Literal["new", "accepted", "playing", "played", "rejected"]
    vote_count: int = 0
    created_at: datetime


class MyRequestsResponse(BaseModel):
    requests: list[MyRequestInfo]


class HasRequestedResponse(BaseModel):
    has_requested: bool


class PublicEventResponse(BaseModel):
    """Guest-safe live-event projection. Deliberately omits event.id and any
    DJ-only fields (see #382 serializer hygiene)."""

    name: str
    collection_code: str
    requests_open: bool
    frictionless_join: bool
    phase: Literal["pre_announce", "collection", "live", "closed"]
    submission_cap_per_guest: int
    banner_url: str | None = None
    banner_colors: list[str] | None = None


class KioskDisplayResponse(BaseModel):
    event: PublicEventInfo
    qr_join_url: str
    accepted_queue: list[PublicRequestInfo]
    now_playing: PublicRequestInfo | None
    now_playing_hidden: bool
    requests_open: bool = True
    kiosk_display_only: bool = False
    updated_at: datetime
    banner_url: str | None = None
    banner_kiosk_url: str | None = None
    banner_colors: list[str] | None = None


@router.get("/events/{code}/display", response_model=KioskDisplayResponse)
@limiter.limit("180/minute")
def get_kiosk_display(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> KioskDisplayResponse:
    """Get public kiosk display data for an event."""
    event, lookup_result = get_event_by_join_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    if lookup_result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")

    if lookup_result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")

    # Build join URL using PUBLIC_URL if set, otherwise use request base
    if settings.public_url:
        base_url = settings.public_url.rstrip("/")
    else:
        base_url = str(request.base_url).rstrip("/")
    qr_join_url = f"{base_url}/join/{event.join_code}"

    # Get accepted requests (status = 'accepted') sorted by vote_count desc, then updated_at asc
    accepted_requests = [r for r in event.requests if r.status == RequestStatus.ACCEPTED.value]
    accepted_requests.sort(key=lambda r: (-r.vote_count, r.updated_at))

    accepted_queue = [
        PublicRequestInfo(
            id=r.id,
            title=r.song_title,
            artist=r.artist,
            artwork_url=r.artwork_url,
            nickname=r.nickname,
            vote_count=r.vote_count,
        )
        for r in accepted_requests
    ]

    # Get now playing from NowPlaying table (single source of truth)
    now_playing = None
    np = get_now_playing(db, event.id)
    if np and np.matched_request_id:
        matched_req = db.query(SongRequest).filter(SongRequest.id == np.matched_request_id).first()
        if matched_req:
            now_playing = PublicRequestInfo(
                id=matched_req.id,
                title=matched_req.song_title,
                artist=matched_req.artist,
                artwork_url=matched_req.artwork_url,
                nickname=matched_req.nickname,
            )

    # Check if now playing should be hidden (using per-event timeout)
    now_playing_is_hidden = is_now_playing_hidden(
        db, event.id, auto_hide_minutes=event.now_playing_auto_hide_minutes
    )

    # Build banner URLs using the API server's own base URL (not PUBLIC_URL, which is the frontend)
    banner_url, banner_colors = _build_public_banner(request, event)
    banner_kiosk_url = None
    if banner_url is not None:
        stem = event.banner_filename.rsplit(".", 1)[0]
        api_base = banner_url.rsplit("/uploads/", 1)[0]
        banner_kiosk_url = f"{api_base}/uploads/{stem}_kiosk.webp"

    return KioskDisplayResponse(
        event=PublicEventInfo(code=event.join_code, name=event.name),
        qr_join_url=qr_join_url,
        accepted_queue=accepted_queue,
        now_playing=now_playing,
        now_playing_hidden=now_playing_is_hidden,
        requests_open=event.requests_open,
        kiosk_display_only=event.kiosk_display_only,
        updated_at=utcnow(),
        banner_url=banner_url,
        banner_kiosk_url=banner_kiosk_url,
        banner_colors=banner_colors,
    )


@router.get("/events/{code}", response_model=PublicEventResponse)
@limiter.limit("120/minute")
def get_public_event(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> PublicEventResponse:
    """Guest-safe event info for the live /join page. Resolves by EITHER public
    code; never emits event.id. Replaces the join page's use of the DJ EventOut
    endpoint (which leaks the private id) and folds in phase + frictionless_join."""
    event, lookup_result = get_event_by_public_code_with_status(db, code)
    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")
    if lookup_result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")
    if lookup_result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")

    banner_url, banner_colors = _build_public_banner(request, event)

    return PublicEventResponse(
        name=event.name,
        collection_code=event.code,
        requests_open=event.requests_open,
        frictionless_join=event.frictionless_join,
        phase=event.phase,
        submission_cap_per_guest=event.submission_cap_per_guest,
        banner_url=banner_url,
        banner_colors=banner_colors,
    )


@router.get("/events/{code}/requests", response_model=GuestRequestListResponse)
@limiter.limit("60/minute")
def get_public_requests(
    code: str,
    request: Request,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> GuestRequestListResponse:
    """Get publicly visible requests for an event (NEW and ACCEPTED only)."""
    event, lookup_result = get_event_by_public_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    if lookup_result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")

    if lookup_result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")

    base_q = (
        db.query(SongRequest, Guest.email_verified_at)
        .outerjoin(Guest, SongRequest.guest_id == Guest.id)
        .filter(
            SongRequest.event_id == event.id,
            SongRequest.status.in_([RequestStatus.NEW.value, RequestStatus.ACCEPTED.value]),
        )
    )
    # Count before ordering/pagination so the client gets the true total.
    total = base_q.count()
    requests_with_verified = (
        base_q.order_by(SongRequest.vote_count.desc(), SongRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Include now-playing if not hidden
    guest_now_playing = None
    if not is_now_playing_hidden(
        db, event.id, auto_hide_minutes=event.now_playing_auto_hide_minutes
    ):
        np = get_now_playing(db, event.id)
        if np:
            guest_now_playing = GuestNowPlaying(
                title=np.title,
                artist=np.artist,
                album_art_url=np.album_art_url,
                source=np.source,
            )

    return GuestRequestListResponse(
        event=PublicEventInfo(code=event.join_code, name=event.name),
        requests=[
            GuestRequestInfo(
                id=r.id,
                title=r.song_title,
                artist=r.artist,
                artwork_url=r.artwork_url,
                nickname=r.nickname,
                vote_count=r.vote_count,
                status=r.status,
                bpm=int(r.bpm) if r.bpm is not None else None,
                musical_key=r.musical_key,
                genre=r.genre,
                requester_verified=email_verified_at is not None,
            )
            for r, email_verified_at in requests_with_verified
        ],
        now_playing=guest_now_playing,
        total=total,
    )


@router.get("/events/{code}/has-requested", response_model=HasRequestedResponse)
@limiter.limit("30/minute")
def check_has_requested(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HasRequestedResponse:
    """Check if the current client has submitted any requests for this event."""
    event, lookup_result = get_event_by_public_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    if lookup_result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")

    if lookup_result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")

    guest_id = get_guest_id(request, db)

    if guest_id is None:
        return HasRequestedResponse(has_requested=False)

    has_requested = (
        db.query(SongRequest)
        .filter(SongRequest.event_id == event.id, SongRequest.guest_id == guest_id)
        .first()
        is not None
    )
    return HasRequestedResponse(has_requested=has_requested)


@router.get("/events/{code}/my-requests", response_model=MyRequestsResponse)
@limiter.limit("30/minute")
def get_my_requests(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> MyRequestsResponse:
    """Get all requests submitted by the current client for this event."""
    event, lookup_result = get_event_by_public_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    if lookup_result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")

    if lookup_result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")

    guest_id = get_guest_id(request, db)

    if guest_id is None:
        return MyRequestsResponse(requests=[])

    requests_list = get_requests_by_guest(db, event.id, guest_id)

    return MyRequestsResponse(
        requests=[
            MyRequestInfo(
                id=r.id,
                title=r.song_title,
                artist=r.artist,
                artwork_url=r.artwork_url,
                status=r.status,
                vote_count=r.vote_count,
                created_at=r.created_at,
            )
            for r in requests_list
        ]
    )
