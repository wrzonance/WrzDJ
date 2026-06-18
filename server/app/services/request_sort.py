"""Sorting + pagination for the authenticated DJ request list (issue #478).

Field sorts the database can express (date/upvotes/bpm/title/artist) run as
efficient ``ORDER BY ... LIMIT/OFFSET`` with a true ``COUNT``. Sorts needing
domain logic the DB can't express run in Python: ``key`` (harmonic Camelot
order) here, and ``best_match`` (priority scoring) in the endpoint. Every sort
ends with a deterministic ``id DESC`` tie-breaker so pages never duplicate or
skip rows as values reorder between polls.
"""

from datetime import datetime

from sqlalchemy import nullslast
from sqlalchemy.orm import Query, Session
from sqlalchemy.sql import func

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.schemas.request import RequestSort, SortDirection
from app.services.recommendation.camelot import parse_key

# Default direction per field when the client does not pass one explicitly.
DEFAULT_SORT_DIRECTION: dict[RequestSort, SortDirection] = {
    RequestSort.DATE_REQUESTED: SortDirection.DESC,
    RequestSort.DATE_ACCEPTED: SortDirection.DESC,
    RequestSort.UPVOTES: SortDirection.DESC,
    RequestSort.BPM: SortDirection.ASC,
    RequestSort.KEY: SortDirection.ASC,
    RequestSort.TITLE: SortDirection.ASC,
    RequestSort.ARTIST: SortDirection.ASC,
    RequestSort.BEST_MATCH: SortDirection.DESC,
}

# SQL columns for field sorts the database can order directly.
_SORT_COLUMNS = {
    RequestSort.DATE_REQUESTED: Request.created_at,
    RequestSort.DATE_ACCEPTED: Request.accepted_at,
    RequestSort.UPVOTES: Request.vote_count,
    RequestSort.BPM: Request.bpm,
    RequestSort.TITLE: func.lower(Request.song_title),
    RequestSort.ARTIST: func.lower(Request.artist),
}

# Sorts whose column is nullable — nulls always sort last, both directions.
_NULLABLE_SORTS = {RequestSort.DATE_ACCEPTED, RequestSort.BPM}


def filtered_requests_query(
    db: Session,
    event: Event,
    status: RequestStatus | None,
    since: datetime | None,
) -> Query:
    """Base query for an event's requests with the existing status/since filters."""
    query = db.query(Request).filter(Request.event_id == event.id)
    if status:
        query = query.filter(Request.status == status.value)
    if since:
        query = query.filter(Request.created_at > since)
    return query


def status_counts(db: Session, event: Event) -> dict[str, int]:
    """True per-status counts for an event, independent of pagination/filters.

    Backs the dashboard status-filter tabs (issue #478): a single
    ``GROUP BY status`` over the whole event, always returning all six keys
    (``all`` plus each status, 0 when absent). ``all`` is the cross-status total.
    """
    counts = {"all": 0, "new": 0, "accepted": 0, "playing": 0, "played": 0, "rejected": 0}
    rows = (
        db.query(Request.status, func.count(Request.id))
        .filter(Request.event_id == event.id)
        .group_by(Request.status)
        .all()
    )
    for status, count in rows:
        if status in counts:
            counts[status] = count
        counts["all"] += count
    return counts


def _camelot_ordinal(musical_key: str | None) -> int | None:
    """Map a key to a sortable harmonic ordinal (1A=2, 1B=3, ... 12B=25)."""
    pos = parse_key(musical_key)
    if pos is None:
        return None
    return pos.number * 2 + (1 if pos.letter == "B" else 0)


def key_sorted(rows: list[Request], direction: SortDirection) -> list[Request]:
    """Sort by harmonic key in Python; null/unparseable keys always last."""
    desc = direction == SortDirection.DESC

    def key_fn(r: Request) -> tuple:
        ordinal = _camelot_ordinal(r.musical_key)
        is_null = ordinal is None
        primary = (-ordinal if desc else ordinal) if ordinal is not None else 0
        return (
            is_null,
            primary,
            (r.song_title or "").lower(),
            (r.artist or "").lower(),
            -r.id,
        )

    return sorted(rows, key=key_fn)


def apply_field_sort(query: Query, sort: RequestSort, direction: SortDirection) -> Query:
    """Apply ``ORDER BY`` for a SQL-expressible field sort.

    Adds nulls-last for nullable columns and a deterministic ``id DESC``
    tie-breaker. Not valid for ``KEY`` (harmonic, Python-sorted via
    :func:`key_sorted`) or ``BEST_MATCH`` (priority-scored in the endpoint).
    """
    column = _SORT_COLUMNS[sort]
    ordering = column.asc() if direction == SortDirection.ASC else column.desc()
    if sort in _NULLABLE_SORTS:
        ordering = nullslast(ordering)
    return query.order_by(ordering, Request.id.desc())


def get_sorted_requests(
    db: Session,
    event: Event,
    *,
    status: RequestStatus | None,
    since: datetime | None,
    sort: RequestSort,
    direction: SortDirection,
    limit: int,
    offset: int,
) -> tuple[list[Request], int]:
    """Return ``(page_rows, true_total)`` for a field sort (not best_match)."""
    base = filtered_requests_query(db, event, status, since)
    total = base.count()

    if sort == RequestSort.KEY:
        ordered = key_sorted(base.all(), direction)
        return ordered[offset : offset + limit], total

    page = apply_field_sort(base, sort, direction).offset(offset).limit(limit).all()
    return page, total
