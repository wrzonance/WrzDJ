"""Small shared builders for public collection endpoint tests."""

from datetime import timedelta

from app.core.time import utcnow
from app.models.event import Event


def _enable_collection(db, event: Event):
    now = utcnow()
    event.collection_opens_at = now - timedelta(hours=1)
    event.live_starts_at = now + timedelta(hours=1)
    db.commit()
    db.refresh(event)


def _make_collection_requests(db, event: Event, count: int) -> None:
    """Create `count` collection-phase NEW requests titled 'Song NNN', 0 votes.

    Titled with zero-padded indices so the "all" tab's alphabetical sort is
    deterministic for offset/limit assertions.
    """
    from app.models.request import Request, RequestStatus

    now = utcnow()
    for i in range(count):
        db.add(
            Request(
                event_id=event.id,
                song_title=f"Song {i:03d}",
                artist=f"Artist {i:03d}",
                source="spotify",
                status=RequestStatus.NEW.value,
                vote_count=0,
                dedupe_key=f"pg_dk_{i}",
                submitted_during_collection=True,
                created_at=now,
            )
        )
    db.commit()


def _human_cookie_for(guest_id: int) -> str:
    """Mint a wrzdj_human cookie value for the given guest_id."""
    from fastapi import Response

    from app.services.human_verification import issue_human_cookie

    resp = Response()
    issue_human_cookie(resp, guest_id)
    raw = resp.headers.get("set-cookie", "")
    return raw.split("=", 1)[1].split(";", 1)[0] if "=" in raw else ""
