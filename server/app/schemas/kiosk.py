"""Pydantic schemas for kiosk pairing endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class KioskPairResponse(BaseModel):
    """Returned when a new kiosk pairing session is created."""

    pair_code: str
    session_token: str
    expires_at: datetime


class KioskPairStatusResponse(BaseModel):
    """Returned when polling a pairing code's status."""

    status: str
    event_code: str | None = None
    event_join_code: str | None = None
    event_name: str | None = None


class KioskSessionResponse(BaseModel):
    """Returned when polling a kiosk's current assignment."""

    status: str
    event_code: str | None = None
    event_join_code: str | None = None
    event_name: str | None = None


class KioskCompletePairingRequest(BaseModel):
    """Body for completing a kiosk pairing."""

    event_code: str = Field(..., min_length=1, max_length=10)


class KioskAssignRequest(BaseModel):
    """Body for reassigning a kiosk to a different event."""

    event_code: str = Field(..., min_length=1, max_length=10)


class KioskRenameRequest(BaseModel):
    """Body for renaming a kiosk."""

    name: str | None = Field(default=None, max_length=100)


class KioskOut(BaseModel):
    """Kiosk info for DJ dashboard (no session_token)."""

    id: int
    name: str | None
    event_code: str | None
    event_join_code: str | None = None
    event_name: str | None = None
    status: str
    paired_at: datetime | None
    last_seen_at: datetime | None
