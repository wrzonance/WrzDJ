"""HTTP mapping for event lookup results shared by event routers."""

from fastapi import HTTPException

from app.services.event import EventLookupResult


def raise_for_unavailable_event(result: EventLookupResult) -> None:
    """Raise the public HTTP error corresponding to a non-active event lookup."""
    if result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")
    if result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")
    if result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")
