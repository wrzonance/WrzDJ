"""CSV export routes for event requests and play history."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_owned_event
from app.core.rate_limit import limiter
from app.models.event import Event
from app.services.export import (
    export_play_history_to_csv,
    export_requests_to_csv,
    generate_export_filename,
    generate_play_history_export_filename,
)
from app.services.now_playing import get_play_history
from app.services.request import get_requests_for_event

router = APIRouter()

# Keep each export bounded to protect memory and response time.
MAX_EXPORT_REQUESTS = 10000
MAX_EXPORT_PLAY_HISTORY = 10000


def _content_disposition(filename: str) -> str:
    """Build an RFC 6266 Content-Disposition header value for a download."""
    safe_filename = filename.replace('"', '\\"')
    ascii_filename = quote(filename, safe="")
    return f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{ascii_filename}"


@router.get("/{code}/export/csv")
@limiter.limit("5/minute")
def export_event_csv(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export event requests as CSV. Owner can export regardless of event status."""
    requests = get_requests_for_event(db, event, status=None, since=None, limit=MAX_EXPORT_REQUESTS)
    csv_content = export_requests_to_csv(event, requests)
    filename = generate_export_filename(event)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/{code}/export/play-history/csv")
@limiter.limit("5/minute")
def export_play_history_csv(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export play history as CSV. Owner can export regardless of event status."""
    history_items, _ = get_play_history(db, event.id, limit=MAX_EXPORT_PLAY_HISTORY, offset=0)
    csv_content = export_play_history_to_csv(event, history_items)
    filename = generate_play_history_export_filename(event)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": _content_disposition(filename)},
    )
